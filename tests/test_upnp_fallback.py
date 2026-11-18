"""LUCI says idle while UPnP plays (Pre35, station switched by automation, 18.11.2026)."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from ha_stub import install

install()

from custom_components.primare.luci import Playback  # noqa: E402
from custom_components.primare.playback import apply_upnp  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/identity.py"
_SPEC = importlib.util.spec_from_file_location("primare_test_identity_upnp", _PATH)
identity = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = identity
_SPEC.loader.exec_module(identity)

DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
  <modelName>PRE35 Prisma</modelName>
  <serviceList>
    <service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
      <controlURL>/upnp/control/rendercontrol1</controlURL></service>
    <service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
      <controlURL>/upnp/control/rendertransport1</controlURL></service>
  </serviceList>
</device></root>"""

TRANSPORT = """<s:Envelope><s:Body><u:GetTransportInfoResponse>
<CurrentTransportState>PLAYING</CurrentTransportState>
<CurrentTransportStatus>OK</CurrentTransportStatus></u:GetTransportInfoResponse></s:Body></s:Envelope>"""

MEDIA = """<s:Envelope><s:Body><u:GetMediaInfoResponse><CurrentURIMetaData>
&lt;DIDL-Lite&gt;&lt;item&gt;&lt;dc:title&gt;Radio BOB! Hard Rock&lt;/dc:title&gt;&lt;/item&gt;&lt;/DIDL-Lite&gt;
</CurrentURIMetaData></u:GetMediaInfoResponse></s:Body></s:Envelope>"""


class ParseTest(unittest.TestCase):
    def test_control_url(self):
        url = identity.parse_av_transport_url(DESCRIPTION, "http://192.0.2.5:49152/description.xml")
        self.assertEqual(url, "http://192.0.2.5:49152/upnp/control/rendertransport1")

    def test_control_url_on_another_host_is_refused(self):
        foreign = DESCRIPTION.replace("/upnp/control/rendertransport1", "http://203.0.113.9/x")
        self.assertIsNone(identity.parse_av_transport_url(foreign, "http://192.0.2.5/d.xml"))

    def test_chunked_answer(self):
        body = TRANSPORT.encode()
        chunked = b"%x\r\n" % 40 + body[:40] + b"\r\n" + b"%x\r\n" % (len(body) - 40) + body[40:] + b"\r\n0\r\n\r\n"
        self.assertEqual(identity._dechunk(chunked), body)

    def test_state_and_title(self):
        self.assertEqual(identity.parse_transport_state(TRANSPORT), "PLAYING")
        self.assertEqual(identity.parse_media_title(MEDIA), "Radio BOB! Hard Rock")
        self.assertIsNone(identity.parse_media_title("<CurrentURIMetaData></CurrentURIMetaData>"))


class ReadTransportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.state = "PLAYING"
        self.server = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.location = f"http://127.0.0.1:{port}/description.xml"
        identity._CONTROL_URLS.clear()

    async def asyncTearDown(self):
        self.server.close()

    async def serve(self, reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        length = next((int(line.split(b":")[1]) for line in head.split(b"\r\n")
                       if line.lower().startswith(b"content-length")), 0)
        body = await reader.readexactly(length) if length else b""
        self.requests.append(head.split(b"\r\n")[0] + b" " + body)
        if head.startswith(b"GET"):
            reply = DESCRIPTION
        elif b"GetTransportInfo" in body:
            reply = TRANSPORT.replace("PLAYING", self.state)
        else:
            reply = MEDIA
        # Headers and body in separate packets, as some devices send them
        writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
        await writer.drain()
        await asyncio.sleep(0.01)
        writer.write(reply.encode())
        await writer.drain()
        writer.close()

    def find(self, result):
        return patch.object(identity, "async_find_location", AsyncMock(return_value=result))

    async def test_playing_with_title(self):
        with self.find(None):
            info, location = await identity.async_read_transport("127.0.0.1", self.location)
        self.assertEqual(info, {"state": "PLAYING", "title": "Radio BOB! Hard Rock"})
        self.assertEqual(location, self.location)
        # Only read-only actions are sent
        actions = [r for r in self.requests if r.startswith(b"POST")]
        self.assertTrue(all(b"GetTransportInfo" in r or b"GetMediaInfo" in r for r in actions))

    async def test_stopped_asks_no_title_and_description_is_cached(self):
        self.state = "STOPPED"
        with self.find(None):
            info, _ = await identity.async_read_transport("127.0.0.1", self.location)
            self.assertEqual(info, {"state": "STOPPED", "title": None})
            await identity.async_read_transport("127.0.0.1", self.location)
        self.assertEqual(sum(r.startswith(b"GET") for r in self.requests), 1)
        self.assertFalse(any(b"GetMediaInfo" in r for r in self.requests))

    async def test_unreachable_device(self):
        with self.find(None) as find:
            info, location = await identity.async_read_transport("127.0.0.1", "http://127.0.0.1:9/description.xml")
        self.assertIsNone(info)
        self.assertEqual(location, "http://127.0.0.1:9/description.xml")
        find.assert_awaited_once()

    async def test_old_address_is_searched_again(self):
        """After a restart the renderer answers on a new port: find it and use it."""
        with self.find(self.location) as find:
            info, location = await identity.async_read_transport("127.0.0.1", "http://127.0.0.1:9/description.xml")
        find.assert_awaited_once()
        self.assertEqual(location, self.location)
        self.assertEqual(info["state"], "PLAYING")

    async def test_no_known_address_is_searched(self):
        with self.find(self.location):
            info, location = await identity.async_read_transport("127.0.0.1", None)
        self.assertEqual((info["state"], location), ("PLAYING", self.location))

    async def test_address_of_another_host_is_not_used(self):
        with self.find(None):
            info, _ = await identity.async_read_transport("192.0.2.1", self.location)
        self.assertIsNone(info)
        self.assertEqual(self.requests, [])

    async def test_refused_description_is_logged(self):
        async def refuse(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(refuse, "127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/description.xml"
        try:
            with self.assertLogs(identity._LOGGER, "DEBUG") as logs:
                self.assertIsNone(await identity.async_fetch(url))
        finally:
            server.close()
        self.assertTrue(any("404 Not Found" in line for line in logs.output))

    async def test_failed_control_request_forgets_the_cached_url(self):
        with self.find(None):
            await identity.async_read_transport("127.0.0.1", self.location)
            self.assertIn(self.location, identity._CONTROL_URLS)
            self.server.close()
            await self.server.wait_closed()
            info, _ = await identity.async_read_transport("127.0.0.1", self.location)
        self.assertIsNone(info)
        self.assertNotIn(self.location, identity._CONTROL_URLS)


class ApplyTest(unittest.TestCase):
    def test_idle_but_upnp_plays(self):
        result = apply_upnp(Playback(1, source_id=2), {"state": "PLAYING", "title": "Radio BOB! Hard Rock"})
        self.assertEqual((result.state, result.title, result.source_id), (0, "Radio BOB! Hard Rock", 2))

    def test_luci_wins_when_it_knows(self):
        playing = Playback(0, title="Zebra")
        self.assertIs(apply_upnp(playing, {"state": "PLAYING", "title": "x"}), playing)

    def test_no_upnp_answer_keeps_idle(self):
        idle = Playback(1)
        self.assertIs(apply_upnp(idle, None), idle)


if __name__ == "__main__":
    unittest.main()
