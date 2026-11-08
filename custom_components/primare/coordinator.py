"""Maintain the Primare control connection and publish complete replies."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
import logging

from homeassistant.exceptions import HomeAssistantError

from .const import DSP_MAP

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 50006
CONNECT_TIMEOUT = 3
INITIAL_REPLY_TIMEOUT = 0.5
COMMAND_TIMEOUT = 2
RECONNECT_DELAY = 1
MAX_RECONNECT_DELAY = 30
HEARTBEAT_INTERVAL = 30
_FIELDS = {"pow": "power", "mut": "mute", "inp": "input", "sur": "dsp", "vol": "volume"}


class PrimareDataCoordinator:
    """Read control status and serialize commands on one TCP session."""

    def __init__(self, host: str, input_map: dict[int, str], multichannel: bool):
        self._host = host
        self._input_map = input_map
        self._queries = tuple(key for key in _FIELDS if key != "sur" or multichannel)
        self.data: dict[str, int | str | None] = dict.fromkeys(_FIELDS.values())
        self._reported: set[str] = set()
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ready = False
        self._send_lock = asyncio.Lock()
        self._pending: tuple[str, int | None, asyncio.Future[None]] | None = None

    def async_add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def available(self, field: str) -> bool:
        return self._ready and field in self._reported

    def async_start(self, hass, entry) -> None:
        self._task = entry.async_create_background_task(
            hass, self._run(), "primare_controls"
        )

    async def async_stop(self, _event=None) -> None:
        task, self._task = self._task, None
        if task is not None:
            if not task.cancelling():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        delay = RECONNECT_DELAY
        while True:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    reader, writer = await asyncio.open_connection(
                        self._host, DEFAULT_PORT, limit=1024
                    )
                self._writer = writer
                read_task = asyncio.create_task(self._read(reader))
                try:
                    for key in self._queries:
                        with suppress(TimeoutError):
                            await self._exchange(writer, key, timeout=INITIAL_REPLY_TIMEOUT)
                    if read_task.done():
                        await read_task
                    self._ready = True
                    delay = RECONNECT_DELAY
                    self._notify()
                    while not (await asyncio.wait({read_task}, timeout=HEARTBEAT_INTERVAL))[0]:
                        await self._exchange(writer, "pow")
                    await read_task
                finally:
                    self._ready = False
                    self._writer = None
                    self._reported.clear()
                    self.data.update(dict.fromkeys(self.data))
                    writer.close()
                    read_task.cancel()
                    await asyncio.gather(read_task, return_exceptions=True)
                    self._notify()
                    with suppress(OSError, TimeoutError):
                        async with asyncio.timeout(1):
                            await writer.wait_closed()
            except (OSError, EOFError, asyncio.LimitOverrunError) as err:
                _LOGGER.debug("Primare control connection to %s ended: %s", self._host, err)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _read(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                line = await reader.readuntil(b"\r\n")
                self._apply_reply(line[:-2])
        except (OSError, EOFError, asyncio.LimitOverrunError) as err:
            if self._pending is not None and not self._pending[2].done():
                self._pending[2].set_exception(err)
            raise

    def _apply_reply(self, line: bytes) -> None:
        key, separator, raw = line.removeprefix(b"!1").partition(b".")
        if not line.startswith(b"!1") or not separator or not raw.isdigit():
            return
        field = _FIELDS.get(key.decode("ascii", errors="replace"))
        if field is None:
            return
        value = int(raw)
        if (field in ("power", "mute") and value not in (0, 1)) or (
            field == "volume" and value > 99
        ):
            return
        state = value
        if field == "input":
            state = self._input_map.get(value)
        elif field == "dsp":
            state = DSP_MAP.get(value)
        changed = field not in self._reported or self.data[field] != state
        self._reported.add(field)
        self.data[field] = state

        if self._pending is not None:
            expected_key, expected_value, reply = self._pending
            if key == expected_key.encode("ascii") and not reply.done() and (
                expected_value is None or expected_value == value
            ):
                reply.set_result(None)
        if self._ready and changed:
            self._notify()

    async def _exchange(
        self,
        writer: asyncio.StreamWriter,
        key: str,
        value: int | None = None,
        *,
        timeout: float = COMMAND_TIMEOUT,
    ) -> None:
        async with self._send_lock:
            if writer is not self._writer or writer.is_closing():
                raise ConnectionError("Primare control connection closed")
            future = asyncio.get_running_loop().create_future()
            self._pending = (key, value, future)
            suffix = "?" if value is None else str(value)
            try:
                async with asyncio.timeout(timeout):
                    writer.write(f"!1{key}.{suffix}\r\n".encode("ascii"))
                    await writer.drain()
                    await future
            finally:
                self._pending = None
                if future.done() and not future.cancelled():
                    future.exception()
                else:
                    future.cancel()

    async def async_set(self, key: str, value: int) -> None:
        writer = self._writer
        if writer is None or not self.available(_FIELDS[key]):
            raise HomeAssistantError("Primare is not available for this control")
        try:
            await self._exchange(writer, key, value)
        except TimeoutError as err:
            raise HomeAssistantError("Primare did not confirm the requested value") from err
        except (OSError, EOFError, asyncio.LimitOverrunError) as err:
            raise HomeAssistantError("Primare control connection was lost") from err
