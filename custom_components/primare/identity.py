"""Model name as the device itself reports it (UPnP).

Ohne Home-Assistant-Importe, damit eigenständig testbar.

1. SSDP M-SEARCH an die IP des Geräts (unicast, zusätzlich multicast; es zählen
   nur Antworten von genau dieser IP) → LOCATION der Gerätebeschreibung.
2. Die Beschreibung per HTTP GET lesen (nur lesen, max. 64 KB).
3. <modelName> herausziehen – nie <friendlyName>, denn den vergibt der Nutzer.
   (<serialNumber> ist bei Primare ein Platzhalter und wird nicht genutzt.)
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import re
import socket
from urllib.parse import urljoin, urlsplit

_LOGGER = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
MAX_DESCRIPTION = 65536
_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 1\r\n"
    "ST: upnp:rootdevice\r\n"
    "\r\n"
).encode("ascii")


class _Responder(asyncio.DatagramProtocol):
    def __init__(self, host: str) -> None:
        self.host = host
        self.location: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr) -> None:
        if addr[0] != self.host or self.location.done():
            return
        for line in data.decode("utf-8", "replace").split("\r\n"):
            key, _, value = line.partition(":")
            if key.strip().lower() == "location" and value.strip():
                location = value.strip()
                if urlsplit(location).hostname == self.host:
                    self.location.set_result(location)
                return


async def async_find_location(
    host: str, *, timeout: float = 3.0, port: int = SSDP_PORT, multicast: bool = True
) -> str | None:
    """Ask the device where its UPnP description lives."""
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _Responder(host), local_addr=("0.0.0.0", 0), family=socket.AF_INET
        )
    except OSError as err:
        _LOGGER.debug("SSDP socket failed: %s", err)
        return None
    try:
        transport.sendto(_SEARCH, (host, port))
        if multicast:
            with contextlib.suppress(OSError):
                transport.sendto(_SEARCH, (SSDP_ADDR, port))
        try:
            return await asyncio.wait_for(asyncio.shield(protocol.location), timeout)
        except TimeoutError:
            return None
    finally:
        transport.close()


async def async_fetch(url: str, *, timeout: float = 5.0) -> str | None:
    """Plain HTTP/1.0 GET, read-only, size-limited."""
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        return None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(parts.hostname, parts.port or 80)
            try:
                writer.write(
                    f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\nConnection: close\r\n\r\n".encode("ascii")
                )
                await writer.drain()
                data = await reader.read(MAX_DESCRIPTION)
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
    except (OSError, TimeoutError, UnicodeEncodeError) as err:
        _LOGGER.debug("UPnP description %s not readable: %s", url, err)
        return None
    head, _, body = data.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/") or b" 200 " not in head.split(b"\r\n", 1)[0] + b" ":
        return None
    return body.decode("utf-8", "replace")


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>\s*([^<]{{1,100}}?)\s*</{name}>", text)
    if not match:
        return None
    value = html.unescape(match.group(1)).strip()
    return value or None


def parse_description(text: str) -> dict[str, str]:
    """modelName and manufacturer of the root device."""
    info: dict[str, str] = {}
    for key, tag in (("model", "modelName"), ("manufacturer", "manufacturer")):
        if value := _field(text, tag):
            info[key] = value
    return info


async def async_read_identity(host: str, location: str | None = None) -> dict[str, str]:
    """Model (and the description's address) of the device at host.

    A known location is fetched directly – plain HTTP, reliable. The UDP search,
    whose answers can get lost, only runs when that fails or nothing is known yet.
    """
    if location and urlsplit(location).hostname == host:
        text = await async_fetch(location)
        if text is not None and (info := parse_description(text)).get("model"):
            return {**info, "location": location}
    for _ in range(2):
        if found := await async_find_location(host, timeout=5):
            text = await async_fetch(found)
            if text is not None and (info := parse_description(text)).get("model"):
                _LOGGER.debug("%s: UPnP identity %s", host, info)
                return {**info, "location": found}
    _LOGGER.debug("%s: no UPnP identity", host)
    return {}


# --------------------------------------------------------------------------------------
# Playback state from the device's own UPnP renderer (read-only).
#
# Over LUCI the Pre35 can report "idle" while it plays a stream that was replaced via
# UPnP (18.11.2026: Radio BOB station switched by an automation). Its UPnP renderer
# still knows – ask it, only in that case. Two read-only actions, no commands:
# GetTransportInfo (state) and GetMediaInfo (title of what is loaded).

AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
_CONTROL_URLS: dict[str, str] = {}


def parse_av_transport_url(text: str, location: str) -> str | None:
    """Control URL of the AVTransport service, only on the device's own host."""
    for block in re.findall(r"<service>(.*?)</service>", text, re.S):
        if _field(block, "serviceType") == AV_TRANSPORT and (path := _field(block, "controlURL")):
            url = urljoin(location, path)
            if urlsplit(url).hostname == urlsplit(location).hostname:
                return url
    return None


def parse_transport_state(text: str) -> str | None:
    return _field(text, "CurrentTransportState")


def parse_media_title(text: str) -> str | None:
    """dc:title from GetMediaInfo's CurrentURIMetaData (DIDL-Lite, escaped inside SOAP)."""
    match = re.search(r"<CurrentURIMetaData>(.*?)</CurrentURIMetaData>", text, re.S)
    if not match:
        return None
    didl = html.unescape(match.group(1))
    title = re.search(r"<dc:title>\s*([^<]{1,200}?)\s*</dc:title>", didl)
    if not title:
        return None
    return html.unescape(title.group(1)).strip() or None


async def async_soap(url: str, action: str, *, timeout: float = 3.0) -> str | None:
    """One read-only AVTransport action (InstanceID 0); plain HTTP/1.0, size-limited."""
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        return None
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{AV_TRANSPORT}"><InstanceID>0</InstanceID></u:{action}>'
        "</s:Body></s:Envelope>"
    ).encode()
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    request = (
        f"POST {path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
        'Content-Type: text/xml; charset="utf-8"\r\n'
        f'SOAPACTION: "{AV_TRANSPORT}#{action}"\r\n'
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(parts.hostname, parts.port or 80)
            try:
                writer.write(request)
                await writer.drain()
                data = await reader.read(MAX_DESCRIPTION)
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
    except (OSError, TimeoutError, UnicodeEncodeError) as err:
        _LOGGER.debug("UPnP %s at %s failed: %s", action, url, err)
        return None
    head, _, response = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0]
    if not head.startswith(b"HTTP/") or b" 200 " not in status + b" ":
        _LOGGER.debug("UPnP %s at %s: %r %r", action, url, status[:80], response[:200])
        return None
    if b"chunked" in head.lower():
        response = _dechunk(response)
    return response.decode("utf-8", "replace")


def _dechunk(data: bytes) -> bytes:
    out, rest = b"", data
    while rest:
        size_line, _, rest = rest.partition(b"\r\n")
        try:
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
        except ValueError:
            return out + rest
        if size == 0:
            break
        out, rest = out + rest[:size], rest[size + 2 :]
    return out


async def async_read_transport(location: str) -> dict[str, str | None] | None:
    """{"state": "PLAYING"|…, "title": …} from the device's UPnP renderer, or None."""
    control = _CONTROL_URLS.get(location)
    if control is None:
        text = await async_fetch(location)
        if text is None:
            _LOGGER.debug("UPnP description %s not readable", location)
            return None
        if (control := parse_av_transport_url(text, location)) is None:
            _LOGGER.debug("No AVTransport control URL in %s", location)
            return None
        _LOGGER.debug("UPnP AVTransport control URL %s", control)
        _CONTROL_URLS[location] = control
    info = await async_soap(control, "GetTransportInfo")
    if info is None:
        return None
    if (state := parse_transport_state(info)) is None:
        _LOGGER.debug("No transport state in UPnP answer %r", info[:200])
        return None
    media = await async_soap(control, "GetMediaInfo") if state == "PLAYING" else None
    return {"state": state, "title": parse_media_title(media) if media else None}
