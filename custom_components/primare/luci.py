"""Read and control playback on the Primare streaming module (LUCI)."""

import asyncio
from collections.abc import Callable
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
PLAY_VIEW_PUSH = 0x2D
POSITION = 0x31
PLAY_STATE = 0x33
SPEAKER = 0x46
REPLY = 1
MAX_PAYLOAD = 5120
REGISTER_SETTLE = 0.1
ACK_TIMEOUT = 0.5
PUSH_SETTLE = 0.15
POSITION_TOLERANCE = 1.5
TRACK_GAP = 2.0
STATE_KEEP_SECONDS = 10
_BUFFERING_STATES = (3, 4, 5)
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

    @property
    def track(self) -> tuple:
        return self.title, self.artist, self.album, self.duration


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
    return position / 1000 if 0 <= position <= 2_147_483_647 else None


class LuciPlaybackClient:
    """Read all frames on one task and serialize commands on one LUCI session."""

    def __init__(self, host: str, port: int = PORT) -> None:
        self._host = host
        self._port = port
        self._lock = asyncio.Lock()
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._replies: dict[int, asyncio.Future[bytes]] = {}
        self._listener: Callable[[Playback | Exception], None] | None = None
        self._state: int | None = None
        self._metadata: Playback | None = None
        self._position: float | None = None
        self._pushed_position: float | None = None
        self._pushed_position_at: float | None = None
        self._last_view_push: tuple[int, bytes, float] | None = None
        self._position_query_supported = True
        self._last_snapshot: Playback | None = None
        self._last_snapshot_at: float | None = None
        self._disconnected_at: float | None = None
        self._publish_handle: asyncio.TimerHandle | None = None
        self._transition_handle: asyncio.TimerHandle | None = None
        self._pending_state: int | None = None
        self._syncing = False
        self._stopping = False

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    def subscribe(self, listener: Callable[[Playback | Exception], None]) -> Callable[[], None]:
        self._listener = listener

        def unsubscribe() -> None:
            self._listener = None

        return unsubscribe

    async def async_shutdown(self) -> None:
        self._stopping = True
        await self.async_disconnect()
        self._clear_playback()
        self._disconnected_at = None

    def _clear_playback(self) -> None:
        self._state = self._metadata = self._position = self._last_snapshot = None
        self._last_snapshot_at = None

    async def async_disconnect(self) -> None:
        async with self._lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        self._cancel_transition()
        self._cancel_publish()
        task, self._reader_task = self._reader_task, None
        writer, self._writer = self._writer, None
        self._clear_position_push()
        self._last_view_push = None
        self._position_query_supported = True
        if writer is not None:
            if self._disconnected_at is None:
                self._disconnected_at = asyncio.get_running_loop().time()
            writer.close()
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if writer is not None:
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()

    async def _request(self, kind: int, box: int, payload: bytes = b"", *, timeout=3) -> bytes:
        if self._writer is None:
            raise ConnectionError("LUCI connection closed")
        assert box not in self._replies
        reply = self._replies[box] = asyncio.get_running_loop().create_future()
        try:
            async with asyncio.timeout(timeout):
                self._writer.write(
                    struct.pack("<HBHBHH", 0, kind, box, 0, 0, len(payload)) + payload
                )
                await self._writer.drain()
                return await reply
        except TimeoutError as err:
            raise TimeoutError(f"LUCI timed out waiting for box {box:#04x}") from err
        finally:
            self._replies.pop(box, None)
            if reply.done() and not reply.cancelled():
                reply.exception()  # Drain an error if the write failed before the await.
            else:
                reply.cancel()

    async def _connect(self) -> None:
        if self._stopping:
            raise ConnectionError("LUCI client is shutting down")
        if self._writer is not None:
            if not self._writer.is_closing() and not self._reader_task.done():
                return
            await self._disconnect()
        try:
            async with asyncio.timeout(3):
                reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
        except TimeoutError as err:
            raise TimeoutError("LUCI TCP connection timed out") from err
        if (
            self._disconnected_at is not None
            and asyncio.get_running_loop().time() - self._disconnected_at > STATE_KEEP_SECONDS
        ):
            self._clear_playback()
        self._reader_task = asyncio.create_task(self._read_loop(reader))
        local_ip = self._writer.get_extra_info("sockname")[0]
        try:
            await self._request(2, REGISTER, local_ip.encode("ascii"))
            await asyncio.sleep(REGISTER_SETTLE)
        except (OSError, EOFError, ValueError, asyncio.CancelledError):
            await self._disconnect()
            raise
        self._disconnected_at = None
        _LOGGER.debug("Registered LUCI session")

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                _, _, box, status, _, size = struct.unpack(
                    ">HBHBHH", await reader.readexactly(10)
                )
                if size > MAX_PAYLOAD:
                    raise ValueError("Oversized LUCI frame")
                self._dispatch(box, status, await reader.readexactly(size))
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if isinstance(err, (OSError, EOFError, ValueError)):
                _LOGGER.debug("LUCI reader disconnected: %s", err)
            else:
                _LOGGER.warning("Unexpected LUCI reader failure", exc_info=True)
            for reply in self._replies.values():
                if not reply.done():
                    reply.set_exception(err)
            await self._disconnect()
            if (
                self._writer is None
                and self._listener is not None
                and not self._syncing
                and not self._stopping
            ):
                self._listener(err)

    def _dispatch(self, box: int, status: int, payload: bytes) -> None:
        if status == 3 and box == 0:
            # The NP5 uses box zero when a request arrives before registration.
            reply = next(iter(self._replies.values()), None)
        else:
            reply = self._replies.get(box)
        if status == 0 or (
            status == REPLY
            and (reply is None or reply.done())
            and box in (PLAY_STATE, PLAY_VIEW, PLAY_VIEW_PUSH, POSITION, SPEAKER)
        ):
            try:
                self._apply_frame(box, payload, pushed=True)
            except ValueError as err:
                _LOGGER.debug("Ignoring malformed LUCI push for box %#04x: %s", box, err)
            return

        if reply is None or reply.done():
            return
        try:
            if status == 3:
                raise ValueError(f"LUCI session not registered (box {box:#04x})")
            if status == 2:
                raise LuciRefused(f"LUCI request refused for box {box:#04x}")
            if status != REPLY:
                raise ValueError(f"Unexpected LUCI status {status} for box {box:#04x}")
            self._apply_frame(box, payload)
        except ValueError as err:
            reply.set_exception(err)
        else:
            reply.set_result(payload)

    def _apply_frame(self, box: int, payload: bytes, *, pushed=False) -> None:
        if box == PLAY_STATE:
            raw_state = _ascii(payload)
            try:
                state = int(raw_state)
            except ValueError as err:
                raise ValueError(
                    "Empty LUCI playback state" if not raw_state
                    else "Non-numeric LUCI playback state"
                ) from err
            self._apply_state(state)
        elif box in (PLAY_VIEW, PLAY_VIEW_PUSH):
            # PlayView's state can be stale after a Spotify pause. Use 0x33.
            metadata = _playback(payload, 0)
            track_changed = self._metadata is not None and metadata.track != self._metadata.track
            if pushed:
                now = asyncio.get_running_loop().time()
                last = self._last_view_push
                if last is not None and box != last[0] and payload == last[1] and now - last[2] <= PUSH_SETTLE:
                    # The NP5 can mirror the same PlayView on both boxes.
                    return
                self._last_view_push = box, payload, now
            if pushed or track_changed:
                self._clear_position_push()
                self._position = metadata.position
            self._metadata = metadata
        elif box == POSITION:
            self._position = _position(payload)
            if pushed:
                self._pushed_position = self._position
                self._pushed_position_at = asyncio.get_running_loop().time()
        elif box == SPEAKER:
            # Do not let an inactive event override a confirmed pause or play.
            if self._pending_state == 1 and _ascii(payload).startswith("SPEAKER_INACTIVE,"):
                self._schedule_transition(1, PUSH_SETTLE)
            return
        else:
            return
        self._schedule_publish()

    def _clear_position_push(self) -> None:
        self._pushed_position = self._pushed_position_at = None

    def _has_usable_position_push(self, read_started: float) -> bool:
        return self._pushed_position_at is not None and (
            self._state == 2
            or (self._state == 0 and self._pushed_position_at >= read_started)
        )

    async def _refresh_position(self, read_started: float) -> None:
        if not self._has_usable_position_push(read_started):
            self._position = self._metadata.position if self._metadata else None
            if self._position_query_supported and (
                self._pushed_position_at is None or self._position is None
            ):
                try:
                    await self._request(1, POSITION, timeout=1)
                except (LuciRefused, TimeoutError):
                    # A late reply could be mistaken for another position query.
                    self._position_query_supported = False
        if self._has_usable_position_push(read_started):
            self._position = self._pushed_position

    def _cancel_transition(self) -> None:
        if self._transition_handle is not None:
            self._transition_handle.cancel()
            self._transition_handle = None
        self._pending_state = None

    def _schedule_transition(self, state: int, delay: float) -> None:
        self._cancel_transition()
        self._pending_state = state
        self._transition_handle = asyncio.get_running_loop().call_later(
            delay, self._finish_transition
        )

    def _finish_transition(self) -> None:
        state = self._pending_state
        self._cancel_transition()
        assert state is not None
        self._set_state(state)
        self._schedule_publish()

    def _apply_state(self, state: int) -> None:
        if (
            state == 1 and self._state in (0, 2, *_BUFFERING_STATES)
        ) or (state in _BUFFERING_STATES and self._state == 0):
            # An idle or buffering blip can also be a track change. Don't publish it as a new
            # session, or an amplifier following the entity will switch again.
            if self._pending_state is None:
                self._schedule_transition(state, TRACK_GAP)
            else:
                self._pending_state = state
            return
        self._cancel_transition()
        self._set_state(state)

    def _set_state(self, state: int) -> None:
        if state == 1 and self._state != 1:
            self._metadata = self._position = None
            self._clear_position_push()
            self._last_view_push = None
        if state not in (0, 1, 2, *_BUFFERING_STATES) and self._state != state:
            _LOGGER.debug("Unmapped LUCI playback state: %s", state)
        self._state = state

    def _snapshot(self) -> Playback | None:
        if self._state is None:
            return None
        if self._metadata is None or self._state not in (0, 2, *_BUFFERING_STATES):
            return Playback(self._state)
        return replace(self._metadata, state=self._state, position=self._position)

    def _cancel_publish(self) -> None:
        if self._publish_handle is not None:
            self._publish_handle.cancel()
            self._publish_handle = None

    def _schedule_publish(self) -> None:
        if self._publish_handle is None and not self._syncing and self._listener is not None:
            self._publish_handle = asyncio.get_running_loop().call_later(
                PUSH_SETTLE, self._publish
            )

    def _publish(self) -> None:
        self._publish_handle = None
        if self._syncing or self._listener is None or self._stopping:
            return
        snapshot = self._snapshot()
        last = self._last_snapshot
        if snapshot is None:
            return
        now = asyncio.get_running_loop().time()
        if last is not None and replace(snapshot, position=None) == replace(last, position=None):
            if snapshot.position is not None and last.position is not None:
                expected = last.position
                if last.state == 0:
                    assert self._last_snapshot_at is not None
                    expected += now - self._last_snapshot_at
                if abs(snapshot.position - expected) <= POSITION_TOLERANCE:
                    return
            elif snapshot.position == last.position:
                return
        self._last_snapshot = snapshot
        self._last_snapshot_at = now
        self._listener(snapshot)

    async def async_read(self) -> Playback:
        """Seed the initial state and periodically check a quiet session."""
        async with self._lock:
            read_started = asyncio.get_running_loop().time()
            self._syncing = True
            self._cancel_publish()
            try:
                await self._connect()
                await self._request(1, PLAY_STATE)
                if self._pending_state is None and self._state in (0, 2, 5):
                    await self._request(1, PLAY_VIEW)
                    await self._refresh_position(read_started)
                snapshot = self._snapshot()
                if snapshot is None:
                    raise ConnectionError("LUCI connection closed while reading playback")
                self._last_snapshot = snapshot
                self._last_snapshot_at = asyncio.get_running_loop().time()
                return snapshot
            except (OSError, EOFError, ValueError, asyncio.CancelledError):
                await self._disconnect()
                raise
            finally:
                self._syncing = False

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
            await self._connect()
            if command == "SEEK":
                self._clear_position_push()
            try:
                await self._request(
                    2, TRANSPORT, payload.encode("ascii"), timeout=ACK_TIMEOUT
                )
            except LuciRefused as err:
                raise LuciRefused("LUCI transport command refused") from err
            except TimeoutError:
                # Acks normally arrive within milliseconds, and the NP5 can omit them.
                # Keep the push session rather than reconnect to rule out a late ack.
                _LOGGER.debug("No LUCI acknowledgement for %s", command)
            except (OSError, EOFError, ValueError, asyncio.CancelledError):
                await self._disconnect()
                raise
