from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isclose
from types import SimpleNamespace

import pytest
import voicelink

from cogs.basic import Basic


class _FakeTree:
    def add_command(self, _command) -> None:
        return None

    def remove_command(self, _name, type=None) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()


class _LogicalClock:
    def __init__(self) -> None:
        self.now_ms = 0

    async def advance(self, delta_ms: int) -> None:
        self.now_ms += delta_ms
        await asyncio.sleep(0)


@dataclass
class _BenchmarkResult:
    first_audio_ms: int
    command_complete_ms: int
    playlist_ready_ms: int


def _make_playlist(track_count: int = 25) -> voicelink.Playlist:
    tracks = []
    for index in range(track_count):
        tracks.append(
            {
                "encoded": f"track-{index}",
                "info": {
                    "identifier": f"id-{index}",
                    "title": f"Song {index}",
                    "author": "Artist",
                    "uri": f"https://example.com/{index}",
                    "length": 1000,
                    "sourceName": "spotify",
                },
            }
        )
    return voicelink.Playlist(
        playlist_info={"name": "Benchmark playlist"},
        tracks=tracks,
        requester=SimpleNamespace(id=1),
    )


class _BenchmarkPlayer:
    def __init__(
        self,
        *,
        clock: _LogicalClock,
        tracks,
        lookup_ms: int = 0,
        add_ms: int = 12,
        play_ms: int = 35,
    ) -> None:
        self.clock = clock
        self._tracks = tracks
        self.lookup_ms = lookup_ms
        self.add_ms = add_ms
        self.play_ms = play_ms
        self._is_playing = False
        self.settings = {"lang": "VN", "silent_msg": False}
        self.channel = SimpleNamespace(mention="#music", members=[])
        self.node = SimpleNamespace(_available=True)
        self.current = SimpleNamespace(requester=SimpleNamespace(bot=False))
        self.queue = SimpleNamespace(_repeat=SimpleNamespace(mode=voicelink.LoopType.OFF))
        self.first_audio_ms: int | None = None
        self.message_sent_ms: int | None = None
        self.playlist_ready_ms: int | None = None

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def is_user_join(self, _author) -> bool:
        return True

    def is_privileged(self, _author) -> bool:
        return True

    async def get_tracks(self, _query, requester=None):
        await self.clock.advance(self.lookup_ms)
        self.playlist_ready_ms = self.clock.now_ms
        return self._tracks

    async def add_track(self, _tracks, **_kwargs):
        await self.clock.advance(self.add_ms)
        return 1

    async def do_next(self):
        await self.clock.advance(self.play_ms)
        self._is_playing = True
        if self.first_audio_ms is None:
            self.first_audio_ms = self.clock.now_ms

    def get_msg(self, *_keys):
        return ["LIVE", "queued", "loaded"]


class _FirstTrackResolver:
    def __init__(
        self,
        *,
        clock: _LogicalClock,
        playlist: voicelink.Playlist,
        first_track_lookup_ms: int,
        remaining_lookup_ms: int,
    ) -> None:
        self.clock = clock
        self.playlist = playlist
        self.first_track_lookup_ms = first_track_lookup_ms
        self.remaining_lookup_ms = remaining_lookup_ms

    async def resolve_first_track(self):
        await self.clock.advance(self.first_track_lookup_ms)
        return self.playlist.tracks[0]

    async def resolve_remaining_tracks(self):
        await self.clock.advance(self.remaining_lookup_ms)
        return self.playlist.tracks[1:]


async def _run_current_playlist_flow(
    *,
    full_lookup_ms: int,
    message_ms: int,
) -> _BenchmarkResult:
    clock = _LogicalClock()
    player = _BenchmarkPlayer(clock=clock, tracks=_make_playlist(), lookup_ms=full_lookup_ms)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        await clock.advance(message_ms)
        player.message_sent_ms = clock.now_ms

    import cogs.basic as basic_module

    original_send = basic_module.send_localized_message
    basic_module.send_localized_message = fake_send_localized_message
    try:
        await Basic.play.callback(cog, ctx, query="spotify-playlist", start="0", end="0")
    finally:
        basic_module.send_localized_message = original_send

    return _BenchmarkResult(
        first_audio_ms=player.first_audio_ms or 0,
        command_complete_ms=player.message_sent_ms or 0,
        playlist_ready_ms=player.playlist_ready_ms or 0,
    )


async def _run_first_track_first_prototype(
    *,
    first_track_lookup_ms: int,
    remaining_lookup_ms: int,
    message_ms: int,
) -> _BenchmarkResult:
    clock = _LogicalClock()
    playlist = _make_playlist()
    player = _BenchmarkPlayer(clock=clock, tracks=playlist)
    resolver = _FirstTrackResolver(
        clock=clock,
        playlist=playlist,
        first_track_lookup_ms=first_track_lookup_ms,
        remaining_lookup_ms=remaining_lookup_ms,
    )

    first_track = await resolver.resolve_first_track()
    await player.add_track(first_track)
    await player.do_next()
    await clock.advance(message_ms)
    player.message_sent_ms = clock.now_ms

    remaining_tracks = await resolver.resolve_remaining_tracks()
    if remaining_tracks:
        await player.add_track(remaining_tracks)
    player.playlist_ready_ms = clock.now_ms

    return _BenchmarkResult(
        first_audio_ms=player.first_audio_ms or 0,
        command_complete_ms=player.message_sent_ms or 0,
        playlist_ready_ms=player.playlist_ready_ms or 0,
    )


def test_current_spotify_playlist_flow_waits_for_full_lookup_before_first_audio() -> None:
    result = asyncio.run(_run_current_playlist_flow(full_lookup_ms=23_067, message_ms=520))

    assert result.playlist_ready_ms == 23_067
    assert result.first_audio_ms == 23_114
    assert result.command_complete_ms == 23_634


def test_first_track_first_prototype_can_cut_ttfa_by_resolving_the_first_song_early() -> None:
    baseline = asyncio.run(_run_current_playlist_flow(full_lookup_ms=23_067, message_ms=520))
    staged = asyncio.run(
        _run_first_track_first_prototype(
            first_track_lookup_ms=1_800,
            remaining_lookup_ms=21_267,
            message_ms=520,
        )
    )

    assert staged.first_audio_ms == 1_847
    assert staged.command_complete_ms == 2_367
    assert staged.playlist_ready_ms == 23_646
    assert baseline.first_audio_ms / staged.first_audio_ms > 12


@pytest.mark.parametrize(
    ("first_track_ratio", "expected_speedup"),
    [
        (0.10, 9.6),
        (0.25, 3.9),
        (0.50, 1.95),
    ],
)
def test_first_track_first_speedup_tracks_how_early_the_first_song_is_available(
    first_track_ratio: float,
    expected_speedup: float,
) -> None:
    full_lookup_ms = 23_067
    first_track_lookup_ms = int(full_lookup_ms * first_track_ratio)
    remaining_lookup_ms = full_lookup_ms - first_track_lookup_ms

    baseline = asyncio.run(_run_current_playlist_flow(full_lookup_ms=full_lookup_ms, message_ms=520))
    staged = asyncio.run(
        _run_first_track_first_prototype(
            first_track_lookup_ms=first_track_lookup_ms,
            remaining_lookup_ms=remaining_lookup_ms,
            message_ms=520,
        )
    )

    speedup = baseline.first_audio_ms / staged.first_audio_ms
    print(
        "scenario=spotify-playlist "
        f"ratio={first_track_ratio:.0%} "
        f"current_ttfa_ms={baseline.first_audio_ms} "
        f"staged_ttfa_ms={staged.first_audio_ms} "
        f"speedup={speedup:.2f}x"
    )

    assert isclose(speedup, expected_speedup, rel_tol=0.05)


def test_first_track_first_is_not_worth_it_if_the_first_song_arrives_only_at_the_end() -> None:
    baseline = asyncio.run(_run_current_playlist_flow(full_lookup_ms=23_067, message_ms=520))
    staged = asyncio.run(
        _run_first_track_first_prototype(
            first_track_lookup_ms=21_500,
            remaining_lookup_ms=1_567,
            message_ms=520,
        )
    )

    assert staged.first_audio_ms >= baseline.first_audio_ms * 0.92
