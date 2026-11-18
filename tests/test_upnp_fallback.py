"""LUCI says idle while UPnP plays (Pre35, station switched by automation, 18.11.2026)."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest

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
        writer.write(f"HTTP/1.1 200 OK\r\n\r\n{reply}".encode())
        await writer.drain()
        writer.close()

    async def test_playing_with_title(self):
        info = await identity.async_read_transport(self.location)
        self.assertEqual(info, {"state": "PLAYING", "title": "Radio BOB! Hard Rock"})
        # Only read-only actions are sent
        actions = [r for r in self.requests if r.startswith(b"POST")]
        self.assertTrue(all(b"GetTransportInfo" in r or b"GetMediaInfo" in r for r in actions))

    async def test_stopped_asks_no_title_and_description_is_cached(self):
        self.state = "STOPPED"
        self.assertEqual(await identity.async_read_transport(self.location), {"state": "STOPPED", "title": None})
        await identity.async_read_transport(self.location)
        self.assertEqual(sum(r.startswith(b"GET") for r in self.requests), 1)
        self.assertFalse(any(b"GetMediaInfo" in r for r in self.requests))

    async def test_unreachable_device(self):
        self.assertIsNone(await identity.async_read_transport("http://127.0.0.1:9/description.xml"))


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
