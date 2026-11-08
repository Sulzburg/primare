"""Read and control playback on the Primare streaming module (LUCI)."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
import json
import logging
import struct
from urllib.parse import urlsplit

PORT = 7777
REGISTER = 0x03
TRANSPORT = 0x28
PLAY_VIEW = 0x2A
POSITION = 0x31
PLAY_STATE = 0x33
REPLY = 1
MAX_PAYLOAD = 5120
IDLE_TIMEOUT = 30
_LOGGER = logging.getLogger(__name__)


class LuciRefused(ValueError):
    """A matching LUCI reply explicitly rejected the request."""


@dataclass(frozen=True)
class Playback:
    state: int
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    position: float | None = None
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    audio_format: str | None = None
    bit_rate_bps: int | None = None
    cover_art_url: str | None = None
    source_app: str | None = None
    can_next: bool = False
    can_previous: bool = False
    can_seek: bool = False


def _text(value):
    return (value.strip() or None) if isinstance(value, str) else None


def _cover_url(value):
    url = _text(value)
    if url is None:
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme in ("http", "https")
            and parts.hostname
            and parts.username is None
        ):
            return url
    except ValueError:
        pass
    return None


def _number(value):
    if type(value) is int:
        return value
    if (
        isinstance(value, str)
        and len(value) < 12
        and value.isascii()
        and value.isdecimal()
    ):
        return int(value)
    return None


def _positive(value):
    number = _number(value)
    return number if number is not None and number > 0 else None


def _playback(payload: bytes, state: int) -> Playback:
    try:
        view = json.loads(payload.rstrip(b"\0"))["Window CONTENTS"]
    except (ValueError, TypeError, KeyError) as err:
        raise ValueError("Invalid LUCI PlayView response") from err
    if not isinstance(view, dict):
        raise ValueError("Invalid LUCI PlayView contents")

    duration = _positive(view.get("TotalTime"))
    position = _number(view.get("Current_time"))
    return Playback(
        state,
        title=_text(view.get("TrackName")),
        artist=_text(view.get("Artist")),
        album=_text(view.get("Album")),
        duration=duration / 1000 if duration is not None else None,
        position=position / 1000 if position is not None and position >= 0 else None,
        sample_rate_hz=_positive(view.get("SampleRate")),
        bit_depth=_positive(view.get("BitDepth")),
        audio_format=_text(view.get("Mime")),
        bit_rate_bps=_positive(view.get("BitRate")),
        cover_art_url=_cover_url(view.get("CoverArtUrl")),
        source_app=_text(view.get("CastContentApp")),
        can_next=view.get("Next") is True,
        can_previous=view.get("Prev") is True,
        can_seek=view.get("Seek") is True,
    )


def _ascii(payload: bytes) -> str:
    return payload.decode("ascii", errors="replace").strip(" \t\r\n\v\f\0")


def _position(payload: bytes) -> float | None:
    try:
        position = int(_ascii(payload))
    except ValueError:
        return None
    return position / 1000 if position >= 0 else None


class LuciPlaybackClient:
    """Serialize polling and transport on one LUCI session."""

    def __init__(self, host: str, port: int = PORT) -> None:
        self._host = host
        self._port = port
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._idle_handle: asyncio.TimerHandle | None = None
        self._pending_frame: tuple[int, int, int] | None = None
        self._pushed_position: bytes | None = None
        self._position_push_seen = False
        self._position_query_supported = True
        self._stopping = False
        self._transport_ack_pending = False

    def _cancel_idle(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def _arm_idle(self) -> None:
        if self._writer is not None:
            self._idle_handle = asyncio.get_running_loop().call_later(
                IDLE_TIMEOUT, self.close
            )

    def _disconnect(self) -> asyncio.StreamWriter | None:
        self._cancel_idle()
        writer = self._writer
        self._reader = self._writer = None
        self._pending_frame = None
        self._pushed_position = None
        self._position_push_seen = False
        self._position_query_supported = True
        self._transport_ack_pending = False
        if writer is not None:
            writer.close()
        return writer

    def close(self) -> None:
        self._disconnect()

    async def async_shutdown(self) -> None:
        self._stopping = True
        await self.async_disconnect()

    async def async_disconnect(self) -> None:
        async with self._lock:
            if (writer := self._disconnect()) is not None:
                with suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()

    async def _send(self, kind: int, box: int, payload: bytes = b"") -> None:
        assert self._writer is not None
        self._writer.write(
            struct.pack("<HBHBHH", 0, kind, box, 0, 0, len(payload)) + payload
        )
        await self._writer.drain()

    async def _reply(self, box: int) -> bytes:
        assert self._reader is not None
        while True:
            if self._pending_frame is None:
                _, _, received, status, _, size = struct.unpack(
                    ">HBHBHH", await self._reader.readexactly(10)
                )
                if size > MAX_PAYLOAD:
                    raise ValueError("Oversized LUCI frame")
                # A command can time out mid-frame without closing the session.
                self._pending_frame = (received, status, size)
            received, status, size = self._pending_frame
            payload = await self._reader.readexactly(size)
            self._pending_frame = None
            if status == 0:
                if received == POSITION:
                    self._pushed_position = payload
                    self._position_push_seen = True
                continue
            if received == TRANSPORT and box != TRANSPORT:
                self._transport_ack_pending = False
            if status == 3 and received in (0, box):
                raise ValueError(f"LUCI session not registered (box {box:#04x})")
            if received == box:
                if status == REPLY:
                    return payload
                if status == 2:
                    raise LuciRefused(f"LUCI request refused for box {box:#04x}")
                raise ValueError(f"Unexpected LUCI status {status} for box {box:#04x}")

    async def _wait_for_reply(self, box: int, timeout: float) -> bytes:
        try:
            async with asyncio.timeout(timeout):
                return await self._reply(box)
        except TimeoutError as err:
            raise TimeoutError(f"LUCI timed out waiting for box {box:#04x}") from err

    async def _connect(self) -> None:
        if self._stopping:
            raise ConnectionError("LUCI client is shutting down")
        if self._writer is not None:
            assert self._reader is not None
            if not self._writer.is_closing() and not self._reader.at_eof():
                return
            self.close()
        try:
            async with asyncio.timeout(3):
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
        except TimeoutError as err:
            raise TimeoutError("LUCI TCP connection timed out") from err
        local_ip = self._writer.get_extra_info("sockname")[0]
        await self._send(2, REGISTER, local_ip.encode("ascii"))
        await self._wait_for_reply(REGISTER, 3)
        _LOGGER.debug("Registered LUCI session")

    async def _query(self, box: int, timeout: float = 3) -> bytes:
        await self._send(1, box)
        return await self._wait_for_reply(box, timeout)

    async def async_read(self) -> Playback:
        async with self._lock:
            self._cancel_idle()
            self._pushed_position = None
            try:
                await self._connect()
                # PlayView can keep reporting "playing" after Spotify pauses.
                raw_state = _ascii(await self._query(PLAY_STATE))
                try:
                    state = int(raw_state)
                except ValueError as err:
                    raise ValueError(
                        "Empty LUCI playback state" if not raw_state
                        else "Non-numeric LUCI playback state"
                    ) from err
                if state not in (0, 2, 5):
                    if state != 1:
                        _LOGGER.debug("Unmapped LUCI playback state: %s", state)
                    return Playback(state)
                playback = _playback(await self._query(PLAY_VIEW), state)
                if state == 5:
                    return playback
                if self._pushed_position is not None:
                    return replace(playback, position=_position(self._pushed_position))
                if not self._position_push_seen and self._position_query_supported:
                    try:
                        raw_position = await self._query(POSITION, timeout=1)
                    except LuciRefused:
                        self._position_query_supported = False
                    except TimeoutError:
                        # A late reply could be confused with a future query.
                        self.close()
                    else:
                        return replace(playback, position=_position(raw_position))
                return playback
            except (OSError, EOFError, ValueError, asyncio.CancelledError):
                self.close()
                raise
            finally:
                self._arm_idle()

    async def async_transport(self, command: str, position: float | None = None) -> None:
        if command == "SEEK":
            if position is None or not 0 <= position <= 2_147_483.647:
                raise ValueError("Invalid playback position")
            payload = f"SEEK:{int(position * 1000)}"
        elif command in ("PLAY", "RESUME", "PAUSE", "STOP", "NEXT", "PREV"):
            payload = command
        else:
            raise ValueError("Unsupported LUCI transport command")

        async with self._lock:
            self._cancel_idle()
            try:
                if self._transport_ack_pending:
                    # Replies do not identify the command, only its mailbox.
                    # Polling can keep this session; another command cannot.
                    self.close()
                await self._connect()
                async with asyncio.timeout(3):
                    await self._send(2, TRANSPORT, payload.encode("ascii"))
                try:
                    await self._wait_for_reply(TRANSPORT, 1)
                except LuciRefused as err:
                    raise ValueError("LUCI transport command refused") from err
                except TimeoutError:
                    # Some NP5 commands send only events. Never resend them.
                    self._transport_ack_pending = True
                    _LOGGER.debug("No LUCI acknowledgement for %s", command)
            except (OSError, EOFError, ValueError, asyncio.CancelledError):
                self.close()
                raise
            finally:
                self._arm_idle()
