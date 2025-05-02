import asyncio
import logging

_LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 50006

class PrimareDataCoordinator:
    def __init__(self, ip_address: str, device_name: str, loop, hass, entry_id):
        self._ip_address = ip_address
        self._device_name = device_name
        self._loop = loop
        self._hass = hass
        self._entry_id = entry_id
        self._listeners = []
        self.data = {
            "volume": None,
            "power": None,
            "mute": None,
            "input": None,
            "dsp": None,
        }
        self._running = False
        self._reader = None
        self._writer = None
        self._listen_task = None
        self._send_lock = asyncio.Lock()

    def async_add_listener(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    async def async_start(self):
        self._running = True
        try:
            _LOGGER.debug("Coordinator: Verbinde zu %s:%s", self._ip_address, DEFAULT_PORT)
            self._reader, self._writer = await asyncio.open_connection(self._ip_address, DEFAULT_PORT)
        except Exception as e:
            _LOGGER.error("Verbindungsaufbau fehlgeschlagen: %s", e)
            return

        for cmd in ["!1pow.?", "!1mut.?", "!1inp.?", "!1sur.?", "!1vol.?"]:
            _LOGGER.debug("Initiale Abfrage: Sende %s", cmd)
            await self.async_send_command(cmd)
            await asyncio.sleep(0.3)
            try:
                data = await asyncio.wait_for(self._reader.read(1024), timeout=0.5)
                self._process_response(data.decode('utf-8', errors='replace'))
            except asyncio.TimeoutError:
                _LOGGER.debug("Keine Antwort bei initialer Abfrage für %s", cmd)

        self._listen_task = self._loop.create_task(self._listen())

    async def async_stop(self):
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def async_send_command(self, command: str):
        async with self._send_lock:
            try:
                _LOGGER.debug("Sende Befehl: %s", command)
                self._writer.write((command + "\r\n").encode())
                await self._writer.drain()
            except Exception as e:
                _LOGGER.error("Fehler beim Senden von %s: %s", command, e)

    async def _listen(self):
        while self._running:
            try:
                data = await self._reader.read(1024)
                if not data:
                    await asyncio.sleep(0.1)
                    continue
                text = data.decode('utf-8', errors='replace')
                _LOGGER.debug("Listener empfängt: %s", text)
                self._process_response(text)
            except Exception as e:
                _LOGGER.error("Fehler im Listener: %s", e)
                await asyncio.sleep(1)

    def _process_response(self, response: str):
        parts = response.split("!1")
        for part in parts:
            if not part:
                continue
            msg = "!1" + part.strip()
            _LOGGER.debug("Verarbeite Nachricht: %s", msg)
            if msg.startswith("!1vol."):
                try:
                    vol_val = int(msg[len("!1vol."):].strip())
                    self.data["volume"] = vol_val
                    _LOGGER.debug("Volume aktualisiert: %s", vol_val)
                except ValueError:
                    _LOGGER.error("Fehler beim Parsen von Volume: %s", msg)
            elif msg.startswith("!1pow."):
                pow_str = msg[len("!1pow."):].strip()
                if pow_str.startswith("1"):
                    self.data["power"] = 1
                elif pow_str.startswith("0"):
                    self.data["power"] = 0
                else:
                    _LOGGER.error("Fehler beim Parsen von Power: %s", msg)
            elif msg.startswith("!1mut."):
                mut_str = msg[len("!1mut."):].strip()
                if mut_str.startswith("0") or mut_str.startswith("1"):
                    self.data["mute"] = int(mut_str[0])
                else:
                    _LOGGER.error("Unbekannter Mute-Wert in: %s", msg)
            elif msg.startswith("!1inp."):
                try:
                    inp_val = int(msg[len("!1inp."):].strip())
                    entry_data = self._hass.data.get("primare", {}).get(self._entry_id, {})
                    input_map = entry_data.get("input_map", {})
                    self.data["input"] = input_map.get(inp_val, inp_val)
                    _LOGGER.debug("Input aktualisiert: %s", self.data["input"])
                except ValueError:
                    _LOGGER.error("Fehler beim Parsen von Input: %s", msg)
            elif msg.startswith("!1sur."):
                try:
                    sur_val = int(msg[len("!1sur."):].strip())
                    from .const import DSP_MAP
                    self.data["dsp"] = DSP_MAP.get(sur_val, sur_val)
                    _LOGGER.debug("DSP aktualisiert: %s", self.data["dsp"])
                except ValueError:
                    _LOGGER.error("Fehler beim Parsen von DSP: %s", msg)

        for callback in self._listeners:
            callback()
