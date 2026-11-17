"""TCP-Client für das Primare-IP-Protokoll (Port 50006, ``!1xxx.yy<CR><LF>``).

Bewusst ohne Home-Assistant-Importe, damit er sich eigenständig testen lässt.

Aufgaben:
- Verbindung halten und nach jedem Abbruch selbst neu aufbauen
  (Wartezeit steigt 1 s → 60 s).
- Stille Verbindungsabbrüche erkennen: Kommt 30 s nichts, wird ``!1pow.?``
  gesendet; kommt darauf in weiteren 30 s keine Antwort, wird neu verbunden.
- Antworten zeilenweise (und zusätzlich an ``!1`` getrennt) zerlegen, damit
  Meldungen, die auf zwei TCP-Pakete verteilt ankommen, nicht verloren gehen.
- Pro Gerät höchstens eine laufende Überblendung; jeder neue
  Lautstärke-Befehl bricht eine laufende ab.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import logging
import re

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 50006
VOLUME_MAX = 99  # laut Primare-API: 0 … 99

CONNECT_TIMEOUT = 10.0
KEEPALIVE_INTERVAL = 30.0
RECONNECT_DELAYS = (1, 2, 5, 10, 30, 60)
REQUERY_DELAY_AFTER_POWER_ON = 1.5

_MSG = re.compile(r"!1([a-z]{3})\.([^\r\n!]*)")


class PrimareNotConnected(Exception):
    """Befehl konnte nicht gesendet werden, weil keine Verbindung besteht."""


def _ease(t: float, kind: str) -> float:
    if kind == "ease_in":
        return t * t
    if kind == "ease_out":
        return 1 - (1 - t) * (1 - t)
    if kind == "ease_in_out":
        return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
    return t


def clamp_volume(value: float) -> int:
    return max(0, min(VOLUME_MAX, int(round(value))))


async def async_probe(host: str, port: int, timeout: float = 5.0) -> None:
    """Einmal verbinden und wieder trennen. Wirft OSError/TimeoutError bei Fehler."""
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout
    )
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


class PrimareClient:
    """Hält die Verbindung zu einem Primare-Gerät und dessen letzten Zustand."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        queries: tuple[str, ...] = ("pow", "mut", "vol", "inp", "sur"),
        name: str | None = None,
        max_volume: int = VOLUME_MAX,
    ) -> None:
        self.host = host
        self.port = port
        self.name = name or host
        self._queries = queries
        # Obergrenze für alles, was HA sendet (Gerät selbst kann höher stehen)
        self.max_volume = max(0, min(VOLUME_MAX, int(max_volume)))

        # Rohwerte vom Gerät; None = noch nicht gemeldet
        self.power: bool | None = None
        self.mute: bool | None = None
        self.volume: int | None = None
        self.input: int | None = None
        self.dsp: int | None = None

        self.connected = False
        self._listeners: list[Callable[[], None]] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._send_lock = asyncio.Lock()
        self._run_task: asyncio.Task | None = None
        self._fade_task: asyncio.Task | None = None
        self._requery_task: asyncio.Task | None = None
        self._buf = ""
        self._stopping = False
        self._connected_once = asyncio.Event()

    # ------------------------------------------------------------------ Listener
    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def _remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return _remove

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 – ein defekter Listener darf den Client nicht stoppen
                _LOGGER.exception("%s: Fehler in Listener", self.name)

    # ---------------------------------------------------------------- Lebenszyklus
    async def start(self, wait: float = 0.0) -> None:
        """Hintergrund-Verbindung starten; optional kurz auf die erste Verbindung warten."""
        self._stopping = False
        self._run_task = asyncio.get_running_loop().create_task(
            self._run(), name=f"primare_{self.name}"
        )
        if wait > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._connected_once.wait(), wait)

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._fade_task, self._requery_task, self._run_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        await self._close()
        self._set_connected(False)

    async def _close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            self._notify()

    async def _run(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
                )
            except (OSError, TimeoutError) as err:
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                log = _LOGGER.warning if attempt == 0 else _LOGGER.debug
                log(
                    "%s: Keine Verbindung zu %s:%s (%s) – neuer Versuch in %s s",
                    self.name, self.host, self.port, err or type(err).__name__, delay,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue

            if attempt:
                _LOGGER.info("%s: Verbindung wiederhergestellt", self.name)
            attempt = 0
            self._buf = ""
            self._set_connected(True)
            self._connected_once.set()
            try:
                await self._query_all()
                await self._read_loop()
            except (
                OSError,
                ConnectionError,
                asyncio.IncompleteReadError,
                PrimareNotConnected,  # Schreiben auf eine gerade geschlossene Verbindung
            ) as err:
                if not self._stopping:
                    _LOGGER.warning("%s: Verbindung verloren (%s)", self.name, err)
            except Exception:  # noqa: BLE001 – die Schleife darf nie aufgeben
                _LOGGER.exception("%s: Unerwarteter Fehler – verbinde neu", self.name)
            finally:
                await self._close()
                self._set_connected(False)
            if not self._stopping:
                await asyncio.sleep(RECONNECT_DELAYS[0])

    async def _read_loop(self) -> None:
        assert self._reader is not None
        probe_pending = False
        while not self._stopping:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(1024), KEEPALIVE_INTERVAL
                )
            except TimeoutError:
                if probe_pending:
                    raise ConnectionError("keine Antwort auf Keepalive") from None
                probe_pending = True
                await self._write("!1pow.?")
                continue
            if not data:
                raise ConnectionError("Gegenstelle hat die Verbindung geschlossen")
            probe_pending = False
            self._feed(data.decode("ascii", errors="replace"))

    async def _query_all(self) -> None:
        for key in self._queries:
            await self._write(f"!1{key}.?")
            await asyncio.sleep(0.05)

    # ------------------------------------------------------------------ Parser
    def _feed(self, text: str) -> None:
        buf = self._buf + text
        cut = max(buf.rfind("\r"), buf.rfind("\n"))
        complete = buf[: cut + 1] if cut >= 0 else ""
        rest = buf[cut + 1 :]
        # Falls das Gerät ohne Zeilenende sendet: alles vor dem letzten "!1" ist fertig
        last = rest.rfind("!1")
        if last > 0:
            complete += rest[:last]
            rest = rest[last:]
        self._buf = rest if len(rest) < 256 else ""

        changed = False
        for match in _MSG.finditer(complete):
            changed |= self._apply(match.group(1), match.group(2).strip())
        if changed:
            self._notify()

    def _apply(self, key: str, raw: str) -> bool:
        _LOGGER.debug("%s: empfangen !1%s.%s", self.name, key, raw)
        try:
            value = int(raw)
        except ValueError:
            _LOGGER.debug("%s: nicht auswertbar: !1%s.%s", self.name, key, raw)
            return False

        if key == "pow":
            new = value == 1
            if new and self.power is False:
                self._schedule_requery()
            changed, self.power = self.power != new, new
        elif key == "mut":
            new = value == 1
            changed, self.mute = self.mute != new, new
        elif key == "vol":
            changed, self.volume = self.volume != value, value
        elif key == "inp":
            changed, self.input = self.input != value, value
        elif key == "sur":
            changed, self.dsp = self.dsp != value, value
        else:
            return False
        return changed

    def _schedule_requery(self) -> None:
        """Nach dem Einschalten den übrigen Zustand neu abfragen."""

        async def _requery() -> None:
            await asyncio.sleep(REQUERY_DELAY_AFTER_POWER_ON)
            with contextlib.suppress(PrimareNotConnected, OSError):
                for key in self._queries:
                    if key != "pow":
                        await self._write(f"!1{key}.?")
                        await asyncio.sleep(0.05)

        if self._requery_task and not self._requery_task.done():
            self._requery_task.cancel()
        self._requery_task = asyncio.get_running_loop().create_task(_requery())

    # ------------------------------------------------------------------ Senden
    async def _write(self, command: str) -> None:
        async with self._send_lock:
            writer = self._writer
            if writer is None or writer.is_closing():
                raise PrimareNotConnected(f"{self.name}: keine Verbindung")
            _LOGGER.debug("%s: sende %s", self.name, command)
            writer.write(f"{command}\r\n".encode("ascii"))
            await writer.drain()

    async def send(self, command: str) -> None:
        try:
            await self._write(command)
        except (OSError, ConnectionError) as err:
            # Leseschleife merkt den Abbruch und verbindet neu
            raise PrimareNotConnected(f"{self.name}: Senden fehlgeschlagen ({err})") from err

    # ------------------------------------------------------------ Komfortbefehle
    async def set_power(self, on: bool) -> None:
        await self.send(f"!1pow.{1 if on else 0}")

    async def set_mute(self, on: bool) -> None:
        await self.send(f"!1mut.{1 if on else 0}")

    async def set_input(self, number: int) -> None:
        await self.send(f"!1inp.{number}")

    async def set_dsp(self, number: int) -> None:
        await self.send(f"!1sur.{number}")

    def limit_volume(self, value: float) -> int:
        """Auf 0 … max_volume begrenzen."""
        return min(self.max_volume, clamp_volume(value))

    async def set_volume(self, value: float) -> None:
        self.cancel_fade()
        await self.send(f"!1vol.{self.limit_volume(value)}")

    async def volume_up(self) -> None:
        self.cancel_fade()
        if self.volume is not None and self.volume >= self.max_volume:
            _LOGGER.debug("%s: lauter ignoriert – Obergrenze %s erreicht", self.name, self.max_volume)
            return
        await self.send("!1vol.u")

    async def volume_down(self) -> None:
        self.cancel_fade()
        await self.send("!1vol.d")

    async def step_volume(self, delta: int, delay: float) -> None:
        """Lautstärke in ``delta`` Einzelschritten (!1vol.u/d) ändern."""
        self.cancel_fade()
        await self._steps(delta, delay)

    async def _steps(self, delta: int, delay: float) -> None:
        if delta > 0:
            if self.volume is not None:
                delta = min(delta, self.max_volume - self.volume)
            if delta <= 0:
                _LOGGER.debug("%s: lauter ignoriert – Obergrenze %s erreicht", self.name, self.max_volume)
                return
        cmd = "!1vol.u" if delta > 0 else "!1vol.d"
        for i in range(abs(delta)):
            await self.send(cmd)
            if delay > 0 and i < abs(delta) - 1:
                await asyncio.sleep(delay)

    # ---------------------------------------------------------------- Überblenden
    def cancel_fade(self) -> None:
        if self._fade_task and not self._fade_task.done():
            self._fade_task.cancel()

    async def fade(
        self,
        target: int,
        duration: float,
        *,
        easing: str = "linear",
        steps: int = 10,
        mode: str = "absolute",
        step_delay: float = 0.04,
    ) -> None:
        """Von der aktuellen Lautstärke auf ``target`` überblenden.

        Eine bereits laufende Überblendung wird abgebrochen. Wird diese
        Überblendung selbst abgebrochen, kehrt der Aufruf ohne Fehler zurück.
        """
        self.cancel_fade()
        task = asyncio.get_running_loop().create_task(
            self._fade(self.limit_volume(target), duration, easing, max(1, steps), mode, step_delay)
        )
        self._fade_task = task
        await asyncio.wait({task})
        if not task.cancelled() and task.exception():
            raise task.exception()

    async def _fade(
        self, target: int, duration: float, easing: str, steps: int, mode: str, step_delay: float
    ) -> None:
        start = self.volume
        if start is None:
            _LOGGER.debug("%s: Überblenden abgebrochen – Lautstärke unbekannt", self.name)
            return
        if start == target:
            return
        pause = max(0.0, duration / steps)
        last = start
        for i in range(1, steps + 1):
            value = round(start + (target - start) * _ease(i / steps, easing))
            if value != last:
                if mode == "steps":
                    await self._steps(value - last, step_delay)
                else:
                    await self.send(f"!1vol.{value}")
                last = value
            if i < steps:
                await asyncio.sleep(pause)
