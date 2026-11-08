"""Read playback snapshots from the Primare streaming module (LUCI)."""

import asyncio
from dataclasses import dataclass, replace
import json
import struct
from urllib.parse import urlsplit

PORT = 7777
REGISTER = 0x03
PLAY_VIEW = 0x2A
POSITION = 0x31
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


def _playback(payload: bytes) -> Playback:
    try:
        message = json.loads(payload.rstrip(b"\0"))
        view = message["Window CONTENTS"]
        state = _number(view["PlayState"])
    except (ValueError, TypeError, KeyError) as err:
        raise ValueError("Invalid LUCI PlayView response") from err

    if state == 1:
        # The module can retain the previous track in an idle snapshot.
        return Playback(state)
    if state not in (0, 2, 5):
        raise ValueError("Unknown LUCI playback state")

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
    )


class LuciPlaybackClient:
    """One session per device; only registration and playback queries are sent."""

    def __init__(self, host: str, port: int = PORT) -> None:
        self._host = host
        self._port = port
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

    async def async_read(self) -> Playback:
        try:
            async with asyncio.timeout(3):
                if self._writer is None:
                    self._reader, self._writer = await asyncio.open_connection(
                        self._host, self._port
                    )
                    local_ip = self._writer.get_extra_info("sockname")[0]
                    await self._send(2, REGISTER, local_ip.encode("ascii"))
                    await self._reply(REGISTER)

                await self._send(1, PLAY_VIEW)
                playback = _playback(await self._reply(PLAY_VIEW))
            if playback.state not in (0, 2):
                return playback
            try:
                async with asyncio.timeout(1):
                    await self._send(1, POSITION)
                    raw_position = await self._reply(POSITION)
            except (TimeoutError, ValueError):
                # Position support varies by source. Keep the verified snapshot;
                # close so a partial or late reply cannot affect the next poll.
                self.close()
                return playback
            position = _number(raw_position.decode("ascii", errors="replace"))
            if position is not None and position >= 0:
                return replace(playback, position=position / 1000)
            return playback
        except (OSError, asyncio.IncompleteReadError, ValueError, asyncio.CancelledError):
            self.close()
            raise
