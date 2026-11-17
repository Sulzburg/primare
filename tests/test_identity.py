"""Model name from the device's own UPnP description."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/identity.py"
_SPEC = importlib.util.spec_from_file_location("primare_test_identity", _PATH)
identity = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = identity
_SPEC.loader.exec_module(identity)

DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Pre35</friendlyName>
    <manufacturer>Primare</manufacturer>
    <modelName>PRE35 Prisma</modelName>
    <serialNumber>PR35-0012345</serialNumber>
  </device>
</root>"""


class IdentityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = "200 OK"
        self.body = DESCRIPTION
        self.http = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        self.http_port = self.http.sockets[0].getsockname()[1]
        self.location = f"http://127.0.0.1:{self.http_port}/description.xml"
        self.searches = []
        test = self

        class Ssdp(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                test.searches.append(data)
                if test.location:
                    self.transport.sendto(
                        f"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nLOCATION: {test.location}\r\n\r\n".encode(),
                        addr,
                    )

        loop = asyncio.get_running_loop()
        self.ssdp, _ = await loop.create_datagram_endpoint(Ssdp, local_addr=("127.0.0.1", 0))
        self.ssdp_port = self.ssdp.get_extra_info("sockname")[1]

    async def asyncTearDown(self):
        self.ssdp.close()
        self.http.close()

    async def serve(self, reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(f"HTTP/1.1 {self.status}\r\nContent-Type: text/xml\r\n\r\n{self.body}".encode())
        await writer.drain()
        writer.close()

    async def find(self):
        return await identity.async_find_location(
            "127.0.0.1", port=self.ssdp_port, multicast=False, timeout=1
        )

    async def test_reads_model_not_the_user_name_or_serial(self):
        location = await self.find()
        self.assertEqual(location, self.location)
        self.assertIn(b"M-SEARCH", self.searches[0])
        info = identity.parse_description(await identity.async_fetch(location))
        self.assertEqual(
            info, {"model": "PRE35 Prisma", "manufacturer": "Primare"}
        )

    async def test_known_location_is_read_without_searching(self):
        info = await identity.async_read_identity("127.0.0.1", self.location)
        self.assertEqual(
            info, {"model": "PRE35 Prisma", "manufacturer": "Primare", "location": self.location}
        )
        self.assertEqual(self.searches, [])

    async def test_location_on_another_host_is_ignored(self):
        self.location = f"http://192.0.2.1:{self.http_port}/description.xml"
        self.assertIsNone(await self.find())

    async def test_no_answer_returns_none(self):
        self.location = None
        self.assertIsNone(await self.find())

    async def test_http_error_returns_none(self):
        self.status = "404 Not Found"
        self.assertIsNone(await identity.async_fetch(self.location))

    def test_missing_serial_and_escaped_text(self):
        info = identity.parse_description(
            "<root><device><manufacturer>Primare</manufacturer>"
            "<modelName>NP5 Prisma MK2 &amp; more</modelName></device></root>"
        )
        self.assertEqual(info, {"model": "NP5 Prisma MK2 & more", "manufacturer": "Primare"})


if __name__ == "__main__":
    unittest.main()
