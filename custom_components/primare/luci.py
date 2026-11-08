"""Read and control playback on the Primare streaming module (LUCI)."""

import asyncio
from dataclasses import dataclass, replace
import json
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


class LuciPlaybackClient:
    """Serialize queries and transport commands on one LUCI session."""

    def __init__(self, host: str, port: int = PORT) -> None:
        self._host = host
        self._port = port
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = self._writer = None

    async def _send(self, kind: int, box: int, payload: bytes = b"") -> None:
        assert self._writer is not None
        self._writer.write(
            struct.pack("<HBHBHH", 0, kind, box, 0, 0, len(payload)) + payload
        )
        await self._writer.drain()

    async def _reply(self, box: int) -> bytes:
        assert self._reader is not None
        while True:
            _, _, received, status, _, size = struct.unpack(
                ">HBHBHH", await self._reader.readexactly(10)
            )
            if size > MAX_PAYLOAD:
                raise ValueError("Oversized LUCI frame")
            payload = await self._reader.readexactly(size)
            if status == 3 or (received == box and status == 2):
                raise ValueError("LUCI request refused")
            if received == box and status == REPLY:
                return payload

    async def _connect(self) -> None:
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port
        )
        local_ip = self._writer.get_extra_info("sockname")[0]
        await self._send(2, REGISTER, local_ip.encode("ascii"))
        await self._reply(REGISTER)

    async def _query(self, box: int) -> bytes:
        await self._send(1, box)
        return await self._reply(box)

    async def async_read(self) -> Playback:
        async with self._lock:
            try:
                async with asyncio.timeout(3):
                    await self._connect()
                    # PlayView can keep reporting "playing" after Spotify pauses.
                    state = _number((await self._query(PLAY_STATE)).decode("ascii"))
                    if state == 1:
                        return Playback(state)
                    if state not in (0, 2, 5):
                        raise ValueError("Unknown LUCI playback state")
                    playback = _playback(await self._query(PLAY_VIEW), state)
                if state == 5:
                    return playback
                try:
                    async with asyncio.timeout(1):
                        raw_position = await self._query(POSITION)
                except (TimeoutError, ValueError):
                    # The source may omit the position. A late response must
                    # not be confused with a reply to the next poll.
                    self.close()
                    return playback
                position = _number(raw_position.decode("ascii", errors="replace"))
                if position is not None and position >= 0:
                    return replace(playback, position=position / 1000)
                return playback
            except (OSError, asyncio.IncompleteReadError, ValueError, asyncio.CancelledError):
                self.close()
                raise

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
            try:
                async with asyncio.timeout(3):
                    await self._connect()
                    await self._send(2, TRANSPORT, payload.encode("ascii"))
                    # NEXT/PREV and RESUME may send only a state/metadata event.
                    # Never retry a transport command automatically.
            except (OSError, asyncio.IncompleteReadError, ValueError, asyncio.CancelledError):
                self.close()
                raise
