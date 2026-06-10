from __future__ import annotations

import ast
import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import discord
import pytest
import voicelink

from cogs.basic import Basic
from cogs.playlist import Playlists
from cogs.settings import Settings
from function import sync_single_guild_app_commands
from voicelink.exceptions import TrackLoadError
from voicelink.views.controller import (
    AutoPlay,
    Forward,
    Loop,
    Lyrics,
    PlayPause,
    Skip,
    Stop,
    Back,
    Rewind,
    Shuffle,
    Tracks,
    VolumeDown,
    VolumeMute,
    VolumeUp,
)
from voicelink.utils import TempCtx, dispatch_message

ROOT = Path(__file__).resolve().parents[1]


class _FakeTree:
    def add_command(self, _command) -> None:
        return None

    def remove_command(self, _name, type=None) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()


class _FakePlayer:
    def __init__(self, *, tracks, is_playing: bool = False) -> None:
        self._tracks = tracks
        self._is_playing = is_playing
        self._is_paused = False
        self.order: list[str] = []
        self.settings = {"lang": "VN", "silent_msg": False, "autoplay": False}
        self.channel = SimpleNamespace(mention="#music", members=[])
        self.context = SimpleNamespace(channel=SimpleNamespace(id=111), guild=SimpleNamespace(id=123))
        self.node = SimpleNamespace(_available=True)
        self.current = SimpleNamespace(requester=SimpleNamespace())
        self.is_ipc_connected = False
        self.position = 60000
        self.volume = 100
        self.queue = SimpleNamespace(
            _repeat=SimpleNamespace(mode=voicelink.LoopType.OFF),
            skipto=lambda index: self.order.append(f"skipto:{index}"),
            backto=lambda index: self.order.append(f"backto:{index}"),
        )

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def is_user_join(self, _author) -> bool:
        return True

    def is_privileged(self, _author) -> bool:
        return True

    async def get_tracks(self, _query=None, requester=None, search_type=None, query=None):
        self.order.append("get_tracks")
        return self._tracks

    async def add_track(self, _tracks, **_kwargs):
        self.order.append("add_track")
        return 1

    async def do_next(self):
        channel_id = getattr(getattr(self.context, "channel", None), "id", "unknown")
        self.order.append(f"do_next:{channel_id}")
        self._is_playing = True

    async def stop(self):
        self.order.append("stop")

    async def set_pause(self, pause, requester=None):
        self._is_paused = pause
        self.order.append(f"pause:{pause}")

    async def set_volume(self, volume, requester=None):
        self.order.append(f"volume:{volume}")

    async def shuffle(self, queue_type, requester=None):
        self.order.append(f"shuffle:{queue_type}")

    async def remove_track(self, index, index2=None, remove_target=None, requester=None):
        self.order.append("remove_track")
        return {1: SimpleNamespace(title="Removed")}

    async def clear_queue(self, queue_type, requester=None):
        self.order.append(f"clear:{queue_type}")

    async def swap_track(self, index1, index2, requester=None):
        self.order.append("swap")
        return SimpleNamespace(title="One"), SimpleNamespace(title="Two")

    async def move_track(self, index, new_index, requester=None):
        self.order.append("move")
        return "Moved"

    async def seek(self, position, requester=None):
        self.position = position
        self.order.append(f"seek:{position}")

    async def set_repeat(self, mode, requester=None):
        self.order.append(f"repeat:{mode.name}")

    def get_msg(self, *_keys):
        if _keys == ("common.status.live", "player.playback.trackLoadPos", "player.playback.trackLoad"):
            return ("LIVE", "TRACK_LOAD_POS", "TRACK_LOAD")
        if _keys == ("player.errors.spotifyPlaylistLookupFailed",):
            return "Spotify playlist lookup failed"
        if _keys == ("player.errors.trackLookupFailed",):
            return "Track lookup failed"
        return "Not found!"

    def bind_controller_context(self, ctx):
        self.context = ctx
        channel_id = getattr(getattr(ctx, "channel", None), "id", "unknown")
        self.order.append(f"context:{channel_id}")

    async def refresh_controller_after_queue_update(self, ctx=None):
        if ctx is not None:
            self.bind_controller_context(ctx)
        self.order.append("refresh_controller")

    async def refresh_controller_for_state_change(self, ctx=None):
        if ctx is not None:
            self.bind_controller_context(ctx)
        self.order.append("refresh_state")


def _make_playlist() -> voicelink.Playlist:
    return voicelink.Playlist(
        playlist_info={"name": "Demo playlist"},
        tracks=[
            {
                "encoded": "abc",
                "info": {
                    "identifier": "id-1",
                    "title": "Song 1",
                    "author": "Artist",
                    "uri": "https://example.com/1",
                    "length": 1000,
                    "sourceName": "spotify",
                },
            }
        ],
        requester=SimpleNamespace(id=1),
    )


def test_play_starts_playlist_playback_before_sending_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="spotify-playlist", start="0", end="0"))

    do_next_index = next(index for index, entry in enumerate(player.order) if entry.startswith("do_next:"))
    assert do_next_index < player.order.index("message")


def test_play_binds_latest_controller_context_before_initial_playback(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="spotify-playlist", start="0", end="0"))

    assert player.order.index("context:456") < player.order.index("do_next:456")


def test_play_refreshes_controller_after_track_confirmation(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Song",
        uri="https://example.com/song",
        author="Artist",
        formatted_length="03:00",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_dispatch_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="https://example.com/song", start="0", end="0"))

    assert player.order.index("message") < player.order.index("refresh_controller")


def test_play_refreshes_controller_after_playlist_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        if _args[1] == "player.playback.playlistLoad":
            player.order.append("message")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
            start="0",
            end="0",
        )
    )

    assert player.order.index("message") < player.order.index("refresh_controller")


@pytest.mark.parametrize(
    ("callback", "kwargs"),
    [
        (Basic.playtop.callback, {"query": "https://example.com/song", "start": "0", "end": "0"}),
        (Basic.forceplay.callback, {"query": "https://example.com/song", "start": "0", "end": "0"}),
    ],
)
def test_queue_add_commands_refresh_controller_after_confirmation(monkeypatch, callback, kwargs) -> None:
    track = SimpleNamespace(
        title="Song",
        uri="https://example.com/song",
        author="Artist",
        formatted_length="03:00",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=600),
        author=SimpleNamespace(mention="@user"),
        interaction=SimpleNamespace(response=SimpleNamespace(defer=lambda: None)) if callback is Basic.forceplay.callback else None,
    )
    cog = Basic(_FakeBot())

    async def fake_dispatch_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    async def fake_defer():
        player.order.append("defer")

    if ctx.interaction:
        ctx.interaction.response.defer = fake_defer

    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(callback(cog, ctx, **kwargs))

    assert player.order.index("message") < player.order.index("refresh_controller")
    assert "context:600" in player.order


def test_context_menu_play_refreshes_controller_after_confirmation(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Clip Song",
        uri="https://example.com/clip",
        author="Artist",
        formatted_length="03:10",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=True)
    interaction = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=604),
        user=SimpleNamespace(mention="@user"),
        response=SimpleNamespace(),
    )
    message = SimpleNamespace(content="https://example.com/clip", attachments=[])
    cog = Basic(_FakeBot())

    async def fake_defer():
        player.order.append("defer")

    async def fake_dispatch_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    interaction.response.defer = fake_defer
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(Basic._play(cog, interaction, message))

    assert player.order.index("message") < player.order.index("refresh_controller")
    assert "context:604" in player.order


def test_search_selection_refreshes_controller_after_confirmation(monkeypatch) -> None:
    tracks = [
        SimpleNamespace(
            title="Result 1",
            uri="https://example.com/result-1",
            author="Artist",
            formatted_length="03:11",
            is_stream=False,
        ),
        SimpleNamespace(
            title="Result 2",
            uri="https://example.com/result-2",
            author="Artist",
            formatted_length="03:12",
            is_stream=False,
        ),
    ]
    player = _FakePlayer(tracks=tracks, is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=605),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    class _FakeSearchView:
        def __init__(self, *, tracks, texts):
            self.tracks = tracks
            self.texts = texts
            self.values = ["1. Result 1"]
            self.response = None

        async def wait(self):
            return None

    async def fake_dispatch_message(*_args, **kwargs):
        if kwargs.get("view") is not None:
            player.order.append("search_results")
            return SimpleNamespace()
        player.order.append("message")
        return None

    async def fake_get_lang(*_args, **_kwargs):
        return (
            "Search: {}",
            "{} {} {} {}",
            "LIVE",
            "TRACK_LOAD_POS",
            "TRACK_LOAD",
            "wait",
            "success",
        )

    monkeypatch.setattr("cogs.basic.SearchView", _FakeSearchView)
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("cogs.basic.LangHandler.get_lang", fake_get_lang)

    asyncio.run(Basic.search.callback(cog, ctx, query="song name", platform=voicelink.SearchType.YOUTUBE.name))

    assert player.order.index("search_results") < player.order.index("add_track")
    assert player.order.index("message") < player.order.index("refresh_controller")
    assert "context:605" in player.order


def test_playlist_play_refreshes_controller_after_confirmation(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Saved Song",
        uri="https://example.com/saved",
        author="Artist",
        formatted_length="03:00",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=601),
        author=SimpleNamespace(id=999),
    )
    cog = Playlists(_FakeBot())

    async def fake_check_playlist(_ctx, _name=None, full=False):
        return {
            "playlist": {
                "type": "link",
                "uri": "https://example.com/playlist",
                "name": "Favs",
            },
            "position": 1,
        }

    async def fake_search_playlist(_uri, _requester, time_needed=False):
        return {"name": "Favs", "tracks": [track]}

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.playlist.check_playlist", fake_check_playlist)
    monkeypatch.setattr("cogs.playlist.search_playlist", fake_search_playlist)
    monkeypatch.setattr("cogs.playlist.send_localized_message", fake_send_localized_message)

    asyncio.run(Playlists.play.callback(cog, ctx, name="favs", value=None))

    assert player.order.index("add_track") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_controller")
    assert "context:601" in player.order


def test_queue_import_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=606),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    class _FakeTrack(SimpleNamespace):
        @staticmethod
        def decode(track_id):
            return {
                "identifier": track_id,
                "title": f"Track {track_id}",
                "author": "Artist",
                "uri": f"https://example.com/{track_id}",
                "length": 1000,
                "sourceName": "youtube",
            }

        def __init__(self, track_id, info, requester):
            super().__init__(
                track_id=track_id,
                title=info["title"],
                author=info["author"],
                uri=info["uri"],
                length=info["length"],
                formatted_length="00:01",
                is_stream=False,
                requester=requester,
            )

    attachment = SimpleNamespace(
        filename="saved.txt",
        read=lambda: None,
    )

    async def fake_read():
        return b"header\ntrack-a,track-b"

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    attachment.read = fake_read
    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.voicelink.Track", _FakeTrack)

    asyncio.run(Basic._import.callback(cog, ctx, attachment=attachment))

    assert player.order.index("add_track") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_controller")
    assert "context:606" in player.order


def test_play_sends_spotify_playlist_loading_notice_before_lookup_and_cleans_it_up(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    class _LoadingMessage:
        async def delete(self):
            player.order.append("delete_loading")

    async def fake_send_localized_message(*_args, **_kwargs):
        key = _args[1]
        if key == "player.playback.spotifyPlaylistLoading":
            player.order.append("loading")
            return _LoadingMessage()
        if key == "player.playback.playlistLoad":
            player.order.append("playlistLoad")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
            start="0",
            end="0",
        )
    )

    assert player.order.index("loading") < player.order.index("get_tracks")
    assert player.order.index("get_tracks") < player.order.index("delete_loading")
    assert player.order.index("delete_loading") < player.order.index("playlistLoad")


def test_play_does_not_send_spotify_playlist_loading_notice_for_spotify_track(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Beauty And A Beat",
        uri="https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk",
        author="Justin Bieber",
        formatted_length="03:47",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    sent_keys: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        sent_keys.append(_args[1])
        return None

    async def fake_dispatch_message(*_args, **_kwargs):
        sent_keys.append("dispatch")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=test",
            start="0",
            end="0",
        )
    )

    assert "player.playback.spotifyPlaylistLoading" not in sent_keys
    assert "dispatch" in sent_keys


def test_spotify_playlist_loading_notice_wraps_track_load_error_in_user_friendly_error(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    class _LoadingMessage:
        async def delete(self):
            player.order.append("delete_loading")

    async def fake_send_localized_message(*_args, **_kwargs):
        key = _args[1]
        if key == "player.playback.spotifyPlaylistLoading":
            player.order.append("loading")
            return _LoadingMessage()
        if key == "player.playback.playlistLoad":
            player.order.append("playlistLoad")
        return None

    async def fake_get_tracks(*_args, **_kwargs):
        player.order.append("get_tracks")
        raise TrackLoadError("Something went wrong while looking up the track. [fault]")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr(player, "get_tracks", fake_get_tracks)

    with pytest.raises(TrackLoadError, match="Spotify"):
        asyncio.run(
            Basic.play.callback(
                cog,
                ctx,
                query="https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
                start="0",
                end="0",
            )
        )

    assert player.order.index("loading") < player.order.index("get_tracks")
    assert player.order[-1] == "delete_loading"


def test_spotify_playlist_loading_notice_wraps_timeout_in_track_load_error(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    class _LoadingMessage:
        async def delete(self):
            player.order.append("delete_loading")

    async def fake_send_localized_message(*_args, **_kwargs):
        key = _args[1]
        if key == "player.playback.spotifyPlaylistLoading":
            player.order.append("loading")
            return _LoadingMessage()
        return None

    async def fake_get_tracks(*_args, **_kwargs):
        player.order.append("get_tracks")
        raise aiohttp.client_exceptions.SocketTimeoutError("Timeout on reading data from socket")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr(player, "get_tracks", fake_get_tracks)

    with pytest.raises(TrackLoadError, match="Spotify"):
        asyncio.run(
            Basic.play.callback(
                cog,
                ctx,
                query="https://open.spotify.com/playlist/6XFOsAdp88ptBCdqUMAfmP?si=test",
                start="0",
                end="0",
            )
        )

    assert player.order.index("loading") < player.order.index("get_tracks")
    assert player.order[-1] == "delete_loading"


def test_play_autocomplete_returns_empty_when_lookup_fails(monkeypatch) -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(id=1))
    cog = Basic(_FakeBot())
    node = SimpleNamespace()

    async def fake_get_tracks(*_args, **_kwargs):
        raise aiohttp.client_exceptions.SocketTimeoutError("Timeout on reading data from socket")

    class FakeYoutubeDL:
        def __init__(self, _options: dict[str, object]) -> None:
            return None

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def extract_info(self, query: str, download: bool = False) -> dict[str, object]:
            assert query == "ytsearch5:vi sao"
            assert download is False
            return {
                "entries": [
                    {
                        "title": "Vì Sao Tôi Là Gay",
                        "uploader": "MiiNa",
                        "webpage_url": "https://www.youtube.com/watch?v=exact-1",
                        "duration": 180,
                    },
                    {
                        "title": "Vì Sao",
                        "uploader": "Artist 2",
                        "webpage_url": "https://www.youtube.com/watch?v=exact-2",
                        "duration": 200,
                    },
                ]
            }

    node.get_tracks = fake_get_tracks
    monkeypatch.setattr("cogs.basic.voicelink.NodePool.get_node", lambda: node)
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    choices = asyncio.run(cog.play_autocomplete(interaction, "vi sao"))

    assert len(choices) == 2
    assert choices[0].name.startswith("🎵 [03:00] MiiNa - Vì Sao Tôi Là Gay")
    assert choices[0].value == "https://www.youtube.com/watch?v=exact-1"
    assert choices[1].name.startswith("🎵 [03:20] Artist 2 - Vì Sao")
    assert choices[1].value == "https://www.youtube.com/watch?v=exact-2"


def test_play_autocomplete_returns_multiple_tracks_from_lavalink_lookup(monkeypatch) -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(id=1))
    cog = Basic(_FakeBot())

    async def fake_search_songs(query: str, *, limit: int = 10, search_type: str | None = None):
        assert query == "song"
        assert limit == 5
        assert search_type is None
        return [
            SimpleNamespace(
                duration_ms=180000,
                author="Artist 1",
                title="Song 1",
                canonical_url="https://www.youtube.com/watch?v=1",
            ),
            SimpleNamespace(
                duration_ms=210000,
                author="Artist 2",
                title="Song 2",
                canonical_url="https://www.youtube.com/watch?v=2",
            ),
        ]

    monkeypatch.setattr("cogs.basic.search_songs", fake_search_songs)

    choices = asyncio.run(cog.play_autocomplete(interaction, "song"))

    assert [choice.name for choice in choices] == [
        "🎵 [03:00] Artist 1 - Song 1",
        "🎵 [03:30] Artist 2 - Song 2",
    ]
    assert [choice.value for choice in choices] == [
        "https://www.youtube.com/watch?v=1",
        "https://www.youtube.com/watch?v=2",
    ]


def test_play_autocomplete_caps_keyword_results_at_five_choices(monkeypatch) -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(id=1))
    cog = Basic(_FakeBot())

    async def fake_search_songs(query: str, *, limit: int = 10, search_type: str | None = None):
        assert query == "song"
        assert limit == 5
        assert search_type is None
        return [
            SimpleNamespace(
                duration_ms=(180 + index) * 1000,
                author=f"Artist {index}",
                title=f"Song {index}",
                canonical_url=f"https://www.youtube.com/watch?v={index}",
            )
            for index in range(1, 8)
        ]

    monkeypatch.setattr("cogs.basic.search_songs", fake_search_songs)

    choices = asyncio.run(cog.play_autocomplete(interaction, "song"))

    assert len(choices) == 5
    assert [choice.value for choice in choices] == [
        "https://www.youtube.com/watch?v=1",
        "https://www.youtube.com/watch?v=2",
        "https://www.youtube.com/watch?v=3",
        "https://www.youtube.com/watch?v=4",
        "https://www.youtube.com/watch?v=5",
    ]


def test_play_autocomplete_skips_remote_lookup_for_single_character_queries(monkeypatch) -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(id=1))
    cog = Basic(_FakeBot())
    node = SimpleNamespace()
    called = False

    async def fake_get_tracks(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    node.get_tracks = fake_get_tracks
    monkeypatch.setattr("cogs.basic.voicelink.NodePool.get_node", lambda: node)

    assert asyncio.run(cog.play_autocomplete(interaction, "A")) == []
    assert called is False


def test_play_autocomplete_limits_remote_lookup_time(monkeypatch) -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(id=1))
    cog = Basic(_FakeBot())
    captured: dict[str, object] = {}

    async def fake_search_songs(query: str, *, limit: int = 10, search_type: str | None = None):
        captured["query"] = query
        captured["limit"] = limit
        captured["search_type"] = search_type
        return []

    monkeypatch.setattr("cogs.basic.search_songs", fake_search_songs, raising=False)

    assert asyncio.run(cog.play_autocomplete(interaction, "vi sao")) == []
    assert captured == {"query": "vi sao", "limit": 5, "search_type": None}


def test_play_falls_back_to_resolved_track_url_when_keyword_lookup_returns_empty(monkeypatch) -> None:
    resolved_url = "https://www.youtube.com/watch?v=exact"
    track = SimpleNamespace(
        title="Vì Sao Tôi Là Gay",
        uri=resolved_url,
        author="MiiNa",
        formatted_length="03:00",
        is_stream=False,
    )
    requested_queries: list[str] = []
    player = _FakePlayer(tracks=None, is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=606),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_get_tracks(query=None, requester=None, search_type=None, **_kwargs):
        requested_queries.append(query)
        player.order.append(f"get_tracks:{query}")
        if query == "vì sao tôi là gay":
            return None
        if query == resolved_url:
            return [track]
        raise AssertionError(f"Unexpected query: {query!r}")

    async def fake_resolve_song(query: str, *, search_type: str | None = None):
        assert query == "vì sao tôi là gay"
        assert search_type is None
        return SimpleNamespace(canonical_url=resolved_url)

    async def fake_dispatch_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("localized_message")
        return None

    player.get_tracks = fake_get_tracks
    monkeypatch.setattr("cogs.basic.resolve_song", fake_resolve_song, raising=False)
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="vì sao tôi là gay", start="0", end="0"))

    assert requested_queries == ["vì sao tôi là gay", resolved_url]
    assert "add_track" in player.order
    assert "message" in player.order


def test_search_falls_back_to_resolver_results_when_keyword_lookup_returns_empty(monkeypatch) -> None:
    resolved_urls = [
        "https://www.youtube.com/watch?v=1",
        "https://www.youtube.com/watch?v=2",
    ]
    requested_queries: list[str] = []
    tracks_by_url = {
        resolved_urls[0]: [
            SimpleNamespace(
                title="Vì Sao Tôi Là Gay",
                uri=resolved_urls[0],
                author="MiiNa",
                formatted_length="03:00",
                is_stream=False,
            )
        ],
        resolved_urls[1]: [
            SimpleNamespace(
                title="Vì Sao",
                uri=resolved_urls[1],
                author="Artist 2",
                formatted_length="03:20",
                is_stream=False,
            )
        ],
    }
    player = _FakePlayer(tracks=None, is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=607),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_get_tracks(query=None, requester=None, search_type=None, **_kwargs):
        requested_queries.append(query)
        player.order.append(f"get_tracks:{query}")
        if query == "vì sao":
            return None
        if query in tracks_by_url:
            return tracks_by_url[query]
        raise AssertionError(f"Unexpected query: {query!r}")

    async def fake_search_songs(query: str, *, limit: int = 10, search_type: str | None = None):
        assert query == "vì sao"
        assert limit == 10
        assert search_type == voicelink.SearchType.YOUTUBE.name
        return [
            SimpleNamespace(canonical_url=resolved_urls[0]),
            SimpleNamespace(canonical_url=resolved_urls[1]),
        ]

    class _FakeSearchView:
        def __init__(self, *, tracks, texts):
            self.tracks = tracks
            self.texts = texts
            self.values = ["1. Vì Sao Tôi Là Gay"]
            self.response = None

        async def wait(self):
            return None

    async def fake_dispatch_message(*_args, **kwargs):
        if kwargs.get("view") is not None:
            player.order.append("search_results")
            return SimpleNamespace()
        player.order.append("message")
        return None

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("localized_message")
        return None

    async def fake_get_lang(*_args, **_kwargs):
        return (
            "Search: {}",
            "{} {} {} {}",
            "LIVE",
            "TRACK_LOAD_POS",
            "TRACK_LOAD",
            "wait",
            "success",
        )

    player.get_tracks = fake_get_tracks
    monkeypatch.setattr("cogs.basic.search_songs", fake_search_songs)
    monkeypatch.setattr("cogs.basic.SearchView", _FakeSearchView)
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.LangHandler.get_lang", fake_get_lang)

    asyncio.run(Basic.search.callback(cog, ctx, query="vì sao", platform=voicelink.SearchType.YOUTUBE.name))

    assert requested_queries == ["vì sao", resolved_urls[0], resolved_urls[1]]
    assert player.order.index("search_results") < player.order.index("add_track")
    assert player.order.index("message") < player.order.index("refresh_controller")


def test_skip_stops_audio_before_sending_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.skip.callback(cog, ctx, index=0))

    assert player.order.index("stop") < player.order.index("message")


def test_skip_binds_latest_controller_context_before_stopping(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=602),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.skip.callback(cog, ctx, index=0))

    assert player.order.index("context:602") < player.order.index("stop")


def test_back_binds_latest_controller_context_before_stopping(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=603),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.back.callback(cog, ctx, index=1))

    assert player.order.index("context:603") < player.order.index("stop")


def test_pause_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=789),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.pause.callback(cog, ctx))

    assert player.order.index("pause:True") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_state")
    assert "context:789" in player.order


def test_resume_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    player._is_paused = True
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=790),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.resume.callback(cog, ctx))

    assert player.order.index("pause:False") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_state")
    assert "context:790" in player.order


def test_remove_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=654),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.remove.callback(cog, ctx, position1=1, position2=None, member=None))

    assert player.order.index("remove_track") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_state")


@pytest.mark.parametrize(
    ("callback", "kwargs", "expected_before_message"),
    [
        (Basic.clear.callback, {"queue": "queue"}, "clear:queue"),
        (Basic.forward.callback, {"position": "10"}, "seek:70000"),
        (Basic.rewind.callback, {"position": "30"}, "seek:30000"),
        (Basic.replay.callback, {}, "seek:0"),
        (Basic.shuffle.callback, {}, "shuffle:queue"),
        (Basic.swap.callback, {"position1": 1, "position2": 2}, "swap"),
        (Basic.move.callback, {"target": 3, "to": 1}, "move"),
    ],
)
def test_state_mutation_commands_refresh_controller_after_confirmation(
    monkeypatch,
    callback,
    kwargs,
    expected_before_message,
) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=791),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(callback(cog, ctx, **kwargs))

    assert player.order.index(expected_before_message) < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_state")
    assert "context:791" in player.order


def test_loop_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=792),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.loop.callback(cog, ctx, mode="QUEUE"))

    assert player.order.index("repeat:QUEUE") < player.order.index("message")
    assert player.order.index("message") < player.order.index("refresh_state")
    assert "context:792" in player.order


def test_autoplay_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=793),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    async def fake_get_lang(*_args, **_kwargs):
        return "Enabled"

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.LangHandler.get_lang", fake_get_lang)

    asyncio.run(Basic.autoplay.callback(cog, ctx))

    assert player.order.index("message") < player.order.index("refresh_state")
    assert "context:793" in player.order


def test_settings_volume_command_refreshes_controller_after_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        channel=SimpleNamespace(id=794),
        author=SimpleNamespace(),
    )
    cog = Settings(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    async def fake_update_settings(_guild_id, _payload):
        player.order.append("db")

    monkeypatch.setattr("cogs.settings.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.settings.MongoDBHandler.update_settings", fake_update_settings)

    asyncio.run(Settings.volume.callback(cog, ctx, value=42))

    assert player.order.index("context:794") < player.order.index("volume:42")
    assert player.order.index("volume:42") < player.order.index("db")
    assert player.order.index("message") < player.order.index("refresh_state")


def test_player_do_next_does_not_inline_await_controller_or_voice_status() -> None:
    player_source = (ROOT / "voicelink" / "player.py").read_text(encoding="utf8")
    module = ast.parse(player_source)
    do_next = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_next"
    )
    awaited_attrs = {
        node.value.func.attr
        for node in ast.walk(do_next)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
    }

    assert "invoke_controller" not in awaited_attrs
    assert "update_voice_status" not in awaited_attrs


def test_dispatch_message_uses_provided_settings_without_fetch(monkeypatch) -> None:
    sent_payload: dict = {}

    async def fail_get_settings(_guild_id: int):
        raise AssertionError("dispatch_message should reuse the provided settings snapshot")

    async def fake_send(*, content=None, embed=None, allowed_mentions=None, silent=False, delete_after=None, ephemeral=False, view=None, file=None):
        kwargs = {
            "content": content,
            "embed": embed,
            "allowed_mentions": allowed_mentions,
            "silent": silent,
            "delete_after": delete_after,
            "ephemeral": ephemeral,
            "view": view,
            "file": file,
        }
        sent_payload.update(kwargs)
        return SimpleNamespace()

    channel = SimpleNamespace(
        id=456,
        guild=SimpleNamespace(id=123),
        send=fake_send,
    )
    ctx = TempCtx(author=SimpleNamespace(), channel=channel)
    settings = {"silent_msg": True, "music_request_channel": {"text_channel_id": 456}}

    monkeypatch.setattr("voicelink.utils.MongoDBHandler.get_settings", fail_get_settings)

    asyncio.run(dispatch_message(ctx, "hello", settings=settings))

    assert sent_payload["silent"] is True
    assert sent_payload["delete_after"] == 10


def test_controller_tracks_dropdown_is_hard_capped_to_25_options() -> None:
    queue_tracks = [
        SimpleNamespace(
            title=f"Song {index}",
            author="Artist",
            formatted_length="03:00",
            is_stream=False,
            emoji="🎵",
        )
        for index in range(1, 31)
    ]
    player = SimpleNamespace(
        queue=SimpleNamespace(is_empty=False, tracks=lambda: queue_tracks),
        _ph=SimpleNamespace(replace=lambda value, _data: value),
        get_msg=lambda key: "TRUC TIEP" if key == "common.status.live" else key,
    )

    select = Tracks(player=player, btn_data={"label": "chon bai", "max_options": 10})

    assert len(select.options) == 25
    assert select.options[-1].label.startswith("25.")


def test_invoke_controller_uses_channel_context_instead_of_interaction_response(monkeypatch) -> None:
    captured = {}

    async def fake_dispatch_message(ctx, content=None, **kwargs):
        captured["ctx"] = ctx
        captured["content"] = content
        captured["kwargs"] = kwargs
        return SimpleNamespace(id=42)

    monkeypatch.setattr("voicelink.player.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    fake_channel = SimpleNamespace(send=None, guild=SimpleNamespace(id=123))
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=None,
        bot=SimpleNamespace(get_channel=lambda _id: None),
        context=SimpleNamespace(channel=fake_channel),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
    )

    asyncio.run(voicelink.Player.invoke_controller(fake_player))

    assert isinstance(captured["ctx"], TempCtx)
    assert captured["ctx"].channel is fake_channel


def test_invoke_controller_reposts_new_message_for_forced_queue_update(monkeypatch) -> None:
    deleted: list[str] = []
    dispatched: list[int] = []

    async def fake_dispatch_message(ctx, content=None, **kwargs):
        dispatched.append(ctx.channel.id)
        return SimpleNamespace(id=99)

    async def fail_is_position_fresh():
        raise AssertionError("Forced controller refresh should not depend on position freshness")

    old_controller = SimpleNamespace(id=42, delete=lambda: deleted.append("old"))

    monkeypatch.setattr("voicelink.player.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    async def delete_old():
        deleted.append("old")

    old_controller.delete = delete_old

    fake_channel = SimpleNamespace(id=456, send=None, guild=SimpleNamespace(id=123))
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=old_controller,
        bot=SimpleNamespace(get_channel=lambda _id: None),
        context=SimpleNamespace(channel=fake_channel),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
        is_position_fresh=fail_is_position_fresh,
    )
    fake_player._replace_controller_message = voicelink.Player._replace_controller_message.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=True))

    assert deleted == ["old"]
    assert dispatched == [456]
    assert fake_player.controller.id == 99


def test_invoke_controller_keeps_sticky_request_channel_message_when_forced(monkeypatch) -> None:
    edited: list[str] = []

    async def fake_edit(*, embed=None, view=None):
        edited.append("edited")

    fetched_message = SimpleNamespace(id=55, edit=fake_edit)

    async def fake_fetch_message(message_id):
        assert message_id == 55
        return fetched_message

    def get_channel(channel_id):
        assert channel_id == 777
        return SimpleNamespace(fetch_message=fake_fetch_message, guild=SimpleNamespace(id=123))

    async def fail_dispatch_message(*_args, **_kwargs):
        raise AssertionError("Sticky request-channel controller should be edited instead of re-posted")

    monkeypatch.setattr("voicelink.player.dispatch_message", fail_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    fake_player = SimpleNamespace(
        settings={"controller": True, "music_request_channel": {"text_channel_id": 777, "controller_msg_id": 55}},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=None,
        bot=SimpleNamespace(get_channel=get_channel),
        context=SimpleNamespace(channel=SimpleNamespace(id=456)),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
    )
    fake_player._replace_controller_message = voicelink.Player._replace_controller_message.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=True))

    assert edited == ["edited"]
    assert fake_player.controller is fetched_message


def test_refresh_controller_after_queue_update_rebinds_latest_context(monkeypatch) -> None:
    recorded = {}
    old_ctx = SimpleNamespace(channel=SimpleNamespace(id=111), guild=SimpleNamespace(id=123))
    new_ctx = SimpleNamespace(channel=SimpleNamespace(id=456), guild=SimpleNamespace(id=123))

    async def fake_invoke_controller(*, prefer_new_message=False):
        recorded["prefer_new_message"] = prefer_new_message
        recorded["context"] = fake_player.context

    fake_player = SimpleNamespace(
        context=old_ctx,
        guild=SimpleNamespace(id=123),
        invoke_controller=fake_invoke_controller,
    )
    fake_player.bind_controller_context = voicelink.Player.bind_controller_context.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.refresh_controller_after_queue_update(fake_player, new_ctx))

    assert recorded["prefer_new_message"] is True
    assert recorded["context"] is new_ctx


def test_refresh_controller_for_state_change_rebinds_latest_context() -> None:
    recorded = {}
    old_ctx = SimpleNamespace(channel=SimpleNamespace(id=111), guild=SimpleNamespace(id=123))
    new_ctx = SimpleNamespace(channel=SimpleNamespace(id=457), guild=SimpleNamespace(id=123))

    async def fake_invoke_controller(*, prefer_new_message=False):
        recorded["prefer_new_message"] = prefer_new_message
        recorded["context"] = fake_player.context

    fake_player = SimpleNamespace(
        context=old_ctx,
        guild=SimpleNamespace(id=123),
        invoke_controller=fake_invoke_controller,
    )
    fake_player.bind_controller_context = voicelink.Player.bind_controller_context.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.refresh_controller_for_state_change(fake_player, new_ctx))

    assert recorded["prefer_new_message"] is False
    assert recorded["context"] is new_ctx


def test_bind_controller_context_ignores_foreign_guild() -> None:
    original_ctx = SimpleNamespace(channel=SimpleNamespace(id=111), guild=SimpleNamespace(id=123))
    foreign_ctx = SimpleNamespace(channel=SimpleNamespace(id=222), guild=SimpleNamespace(id=999))
    fake_player = SimpleNamespace(context=original_ctx, guild=SimpleNamespace(id=123))

    voicelink.Player.bind_controller_context(fake_player, foreign_ctx)

    assert fake_player.context is original_ctx


def test_invoke_controller_queues_pending_refresh_when_busy() -> None:
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=True,
        channel=SimpleNamespace(),
        _tearing_down=False,
        _controller_refresh_pending=False,
        _controller_refresh_prefer_new_message=False,
    )

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=True))

    assert fake_player._controller_refresh_pending is True
    assert fake_player._controller_refresh_prefer_new_message is True


def test_invoke_controller_preserves_forced_refresh_preference_when_busy() -> None:
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=True,
        channel=SimpleNamespace(),
        _tearing_down=False,
        _controller_refresh_pending=True,
        _controller_refresh_prefer_new_message=True,
    )

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=False))

    assert fake_player._controller_refresh_pending is True
    assert fake_player._controller_refresh_prefer_new_message is True


def test_playpause_button_refreshes_controller_after_state_change() -> None:
    order: list[str] = []

    async def fake_set_pause(pause, requester=None):
        order.append(f"pause:{pause}")

    async def fake_refresh(interaction=None):
        order.append("refresh_state")

    class _FakeResponse:
        def __init__(self):
            self.deferred = False

        async def defer(self):
            self.deferred = True

    response = _FakeResponse()
    interaction = SimpleNamespace(user=SimpleNamespace(), response=response)
    player = SimpleNamespace(
        is_paused=False,
        current=SimpleNamespace(),
        is_privileged=lambda _user: True,
        set_pause=fake_set_pause,
        refresh_controller_for_state_change=fake_refresh,
        pause_votes=set(),
        resume_votes=set(),
        required=lambda: 1,
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    button = PlayPause(
        player=player,
        btn_data={
            "states": {
                "pause": {"label": "Tam dung"},
                "resume": {"label": "Phat tiep"},
            }
        },
    )

    asyncio.run(button.callback(interaction))

    assert response.deferred is True
    assert order == ["pause:True", "refresh_state"]


@pytest.mark.parametrize(
    ("button_cls", "expected_prefix"),
    [
        (Loop, "repeat:TRACK"),
        (VolumeUp, "volume:120"),
        (VolumeDown, "volume:80"),
        (Shuffle, "shuffle:queue"),
        (Forward, "seek:70000"),
        (Rewind, "seek:30000"),
        (AutoPlay, "message"),
    ],
)
def test_controller_buttons_refresh_controller_after_action(monkeypatch, button_cls, expected_prefix) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_refresh(interaction=None):
        order.append("refresh_state")

    async def fake_set_repeat(mode=None, requester=None):
        if mode is None:
            order.append("repeat:TRACK")
        else:
            order.append(f"repeat:{mode.name}")

    async def fake_set_volume(value, requester=None):
        order.append(f"volume:{value}")

    async def fake_shuffle(queue_type, requester=None):
        order.append(f"shuffle:{queue_type}")

    async def fake_seek(position):
        order.append(f"seek:{position}")

    async def fake_do_next():
        order.append("do_next")

    async def fake_get_lang(*_args, **_kwargs):
        return "Enabled"

    player = SimpleNamespace(
        is_paused=False,
        is_playing=True,
        queue=SimpleNamespace(
            _repeat=SimpleNamespace(mode=voicelink.LoopType.OFF, peek_next=lambda: voicelink.LoopType.TRACK)
        ),
        is_privileged=lambda _user: True,
        required=lambda *args, **kwargs: 1,
        set_repeat=fake_set_repeat,
        set_volume=fake_set_volume,
        shuffle=fake_shuffle,
        seek=fake_seek,
        refresh_controller_for_state_change=fake_refresh,
        _ph=SimpleNamespace(replace=lambda value, _data: value),
        settings={"volume": 100, "autoplay": False, "controller_msg": True},
        volume=100,
        position=60000,
        do_next=fake_do_next,
        channel=SimpleNamespace(mention="#music", members=[]),
        node=SimpleNamespace(_available=True),
        is_user_join=lambda _user: True,
        current=SimpleNamespace(title="Song", author="Artist", requester=SimpleNamespace()),
        shuffle_votes=set(),
        resume_votes=set(),
        pause_votes=set(),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(),
        guild_id=123,
        response=SimpleNamespace(defer=lambda: None),
    )

    async def fake_defer():
        order.append("defer")

    interaction.response.defer = fake_defer
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("voicelink.views.controller.LangHandler.get_lang", fake_get_lang)

    button = button_cls(player=player, btn_data={"label": "x", "states": {"track": {"label": "track"}}})

    asyncio.run(button.callback(interaction))

    assert expected_prefix in order
    assert order[-1] == "refresh_state"


def test_volume_mute_button_refreshes_controller_after_state_change() -> None:
    order: list[str] = []

    async def fake_set_volume(value, requester=None):
        order.append(f"volume:{value}")

    async def fake_refresh(interaction=None):
        order.append("refresh_state")

    async def fake_defer():
        order.append("defer")

    player = SimpleNamespace(
        current=SimpleNamespace(),
        volume=100,
        settings={"volume": 100},
        is_privileged=lambda _user: True,
        set_volume=fake_set_volume,
        refresh_controller_for_state_change=fake_refresh,
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(user=SimpleNamespace(), response=SimpleNamespace(defer=fake_defer))
    button = VolumeMute(
        player=player,
        btn_data={"label": "x", "states": {"mute": {"label": "Mute"}, "muted": {"label": "Unmute"}}},
    )

    asyncio.run(button.callback(interaction))

    assert order == ["volume:0", "defer", "refresh_state"]


def test_skip_button_sends_success_then_stops_playback(monkeypatch) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_stop():
        order.append("stop")

    player = SimpleNamespace(
        is_playing=True,
        current=SimpleNamespace(requester=SimpleNamespace()),
        is_privileged=lambda _user: True,
        queue=SimpleNamespace(_repeat=SimpleNamespace(mode=voicelink.LoopType.OFF)),
        stop=fake_stop,
        skip_votes=set(),
        required=lambda: 1,
        settings={"controller_msg": True},
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(user=SimpleNamespace())
    button = Skip(player=player, btn_data={"label": "skip"})
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)

    asyncio.run(button.callback(interaction))

    assert order == ["message", "stop"]


def test_back_button_while_playing_sends_success_then_stops_playback(monkeypatch) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_stop():
        order.append("stop")

    player = SimpleNamespace(
        is_playing=True,
        current=SimpleNamespace(),
        is_privileged=lambda _user: True,
        queue=SimpleNamespace(
            history=lambda: ["old"],
            backto=lambda index: order.append(f"backto:{index}"),
            _repeat=SimpleNamespace(mode=voicelink.LoopType.OFF),
        ),
        stop=fake_stop,
        previous_votes=set(),
        required=lambda: 1,
        settings={"controller_msg": True},
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(user=SimpleNamespace())
    button = Back(player=player, btn_data={"label": "back"})
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)

    asyncio.run(button.callback(interaction))

    assert order == ["backto:2", "stop", "message"]


def test_stop_button_sends_success_then_tears_down(monkeypatch) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_teardown():
        order.append("teardown")

    player = SimpleNamespace(
        is_privileged=lambda _user: True,
        stop_votes=set(),
        required=lambda leave=False: 1,
        teardown=fake_teardown,
        settings={"controller_msg": True},
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(user=SimpleNamespace())
    button = Stop(player=player, btn_data={"label": "stop"})
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)

    asyncio.run(button.callback(interaction))

    assert order == ["message", "teardown"]


def test_lyrics_button_returns_not_found_when_provider_times_out(monkeypatch) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_fetch_lyrics(_title, _artist):
        raise AssertionError("controller should use voicelink.fetch_lyrics instead of raw provider access")

    async def fake_safe_fetch(_title, _artist):
        order.append("lookup")
        return None

    async def fake_defer():
        order.append("defer")

    player = SimpleNamespace(
        is_playing=True,
        current=SimpleNamespace(title="Song", author="Artist"),
        is_privileged=lambda _user: True,
        settings={"controller_msg": True},
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(),
        response=SimpleNamespace(defer=fake_defer),
    )
    button = Lyrics(player=player, btn_data={"label": "lyrics"})
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("voicelink.views.controller.voicelink.fetch_lyrics", fake_safe_fetch)
    monkeypatch.setattr(
        "voicelink.views.controller.voicelink.LYRICS_PLATFORMS",
        {"genius": fake_fetch_lyrics},
    )

    asyncio.run(button.callback(interaction))

    assert order == ["defer", "lookup", "message"]


def test_tracks_select_skips_to_selected_track_and_stops_playback(monkeypatch) -> None:
    order: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        order.append("message")
        return None

    async def fake_defer():
        order.append("defer")

    async def fake_stop():
        order.append("stop")

    queue_tracks = [
        SimpleNamespace(title="Song 1", author="Artist", formatted_length="03:00", is_stream=False, emoji="🎵"),
        SimpleNamespace(title="Song 2", author="Artist", formatted_length="03:00", is_stream=False, emoji="🎵"),
    ]
    player = SimpleNamespace(
        queue=SimpleNamespace(
            is_empty=False,
            tracks=lambda: queue_tracks,
            skipto=lambda index: order.append(f"skipto:{index}"),
        ),
        get_msg=lambda key: "LIVE" if key == "common.status.live" else key,
        is_privileged=lambda _user: True,
        stop=fake_stop,
        settings={"controller_msg": True},
        _ph=SimpleNamespace(replace=lambda value, _data: value),
    )
    interaction = SimpleNamespace(user=SimpleNamespace(), response=SimpleNamespace(defer=fake_defer))
    select = Tracks(player=player, btn_data={"label": "chon bai"})
    select._values = ["2. Song 2"]
    monkeypatch.setattr("voicelink.views.controller.send_localized_message", fake_send_localized_message)

    asyncio.run(select.callback(interaction))

    assert order == ["defer", "skipto:2", "stop", "message"]


def test_voice_status_cleanup_clears_status_even_when_cached_channel_status_is_missing() -> None:
    recorded = {}

    async def fake_edit(*, status=None):
        recorded["status"] = status

    channel = SimpleNamespace(
        type=discord.ChannelType.voice,
        status=None,
        edit=fake_edit,
    )

    asyncio.run(voicelink.Player._clear_voice_status_for_channel(SimpleNamespace(), channel))

    assert recorded["status"] is None


def test_teardown_clears_voice_status_before_destroy() -> None:
    order: list[str] = []

    async def fake_clear_voice_status(channel):
        order.append(f"clear:{channel.id}")

    async def fake_destroy():
        order.append("destroy")

    fake_player = SimpleNamespace(
        _cancel_inactive_cleanup_timer=lambda: None,
        _cancel_background_tasks=lambda: order.append("cancel_background"),
        controller=None,
        settings={"played_time": 0, "music_request_channel": {}},
        build_embed=lambda current=None: None,
        joinTime=0,
        _start_background_task=lambda coro, label: order.append(f"bg:{label}"),
        _persist_teardown_state=lambda played_time: None,
        _clear_voice_status_for_channel=fake_clear_voice_status,
        _cleanup_controller_message=lambda controller, **kwargs: None,
        is_ipc_connected=False,
        destroy=fake_destroy,
        channel=SimpleNamespace(id=321),
        _tearing_down=False,
        guild=SimpleNamespace(id=123),
        _logger=logging.getLogger("test"),
    )

    asyncio.run(voicelink.Player.teardown(fake_player))

    assert order[:3] == ["cancel_background", "bg:teardown_persist", "clear:321"]
    assert order[-1] == "destroy"


def test_teardown_suppresses_forbidden_voice_status_warning_noise(monkeypatch) -> None:
    debug_messages: list[str] = []
    warning_messages: list[str] = []
    order: list[str] = []

    class _FakeForbidden(Exception):
        pass

    monkeypatch.setattr("voicelink.player.errors.Forbidden", _FakeForbidden)

    async def fake_clear_voice_status(_channel):
        raise _FakeForbidden()

    async def fake_destroy():
        order.append("destroy")

    logger = SimpleNamespace(
        debug=lambda message, *args, **kwargs: debug_messages.append(message % args if args else message),
        warning=lambda message, *args, **kwargs: warning_messages.append(message % args if args else message),
    )

    fake_player = SimpleNamespace(
        _cancel_inactive_cleanup_timer=lambda: None,
        _cancel_background_tasks=lambda: None,
        controller=None,
        settings={"played_time": 0, "music_request_channel": {}},
        build_embed=lambda current=None: None,
        joinTime=0,
        _start_background_task=lambda coro, label: order.append(f"bg:{label}"),
        _persist_teardown_state=lambda played_time: None,
        _clear_voice_status_for_channel=fake_clear_voice_status,
        _cleanup_controller_message=lambda controller, **kwargs: None,
        is_ipc_connected=False,
        destroy=fake_destroy,
        channel=SimpleNamespace(id=321),
        _tearing_down=False,
        guild=SimpleNamespace(id=123),
        _logger=logger,
    )

    asyncio.run(voicelink.Player.teardown(fake_player))

    assert order == ["bg:teardown_persist", "destroy"]
    assert warning_messages == []
    assert debug_messages == [
        "Skipped clearing voice status during teardown for guild 123 due to missing permissions or disconnect timing."
    ]


def test_update_voice_status_is_skipped_while_tearing_down() -> None:
    recorded = {"called": False}

    async def fake_edit(*, status=None):
        recorded["called"] = True

    fake_player = SimpleNamespace(
        _tearing_down=True,
        settings={},
        channel=SimpleNamespace(type=discord.ChannelType.voice, edit=fake_edit),
        _ph=SimpleNamespace(variables={}),
    )

    asyncio.run(voicelink.Player.update_voice_status(fake_player))

    assert recorded["called"] is False


def test_schedule_post_playback_updates_cancels_pending_voice_status_task() -> None:
    cancelled = {"called": False}
    scheduled = []

    class _PendingTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            cancelled["called"] = True

    fake_player = SimpleNamespace(
        _voice_status_task=_PendingTask(),
        _start_background_task=lambda coro, label: scheduled.append(label) or SimpleNamespace(add_done_callback=lambda _cb: None),
        is_ipc_connected=False,
        update_voice_status=lambda **kwargs: None,
        invoke_controller=lambda: None,
        send_ws=lambda payload: None,
    )

    voicelink.Player._schedule_post_playback_updates(fake_player, SimpleNamespace(track_id="track-1"))

    assert cancelled["called"] is True
    assert scheduled == ["controller_side_effect", "voice_status_side_effect"]


def test_update_voice_status_uses_track_snapshot_when_current_is_already_cleared() -> None:
    recorded = {"status": "unset"}

    async def fake_edit(*, status=None):
        recorded["status"] = status

    class _FakePlaceholder:
        def __init__(self) -> None:
            self.variables = {"track_name": lambda: "None"}

        def replace(self, text: str, variables: dict[str, str]) -> str:
            return variables.get("track_name", "")

    fake_player = SimpleNamespace(
        _tearing_down=False,
        settings={"stage_announce_template": "{{@@track_name@@ != 'None' ?? @@track_name@@}}"},
        channel=SimpleNamespace(type=discord.ChannelType.voice, edit=fake_edit, status=None),
        current=None,
        _ph=_FakePlaceholder(),
        bot=SimpleNamespace(
            user=SimpleNamespace(
                id=1,
                display_name="Vocard",
                display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
            )
        ),
        get_msg=lambda key: "LIVE" if key == "common.status.live" else key,
    )

    snapshot = SimpleNamespace(
        title="Track Snapshot",
        uri="https://example.com/track",
        author="Artist",
        is_stream=False,
        length=1234,
        requester=None,
        source="youtube",
        emoji="🎵",
        thumbnail="https://example.com/thumb.png",
    )

    asyncio.run(voicelink.Player.update_voice_status(fake_player, track_snapshot=snapshot))

    assert recorded["status"] == "Track Snapshot"


def test_single_guild_sync_purges_legacy_global_commands() -> None:
    class _FakeCommandTree:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def copy_global_to(self, guild=None) -> None:
            self.calls.append(("copy_global_to", getattr(guild, "id", None)))

        async def sync(self, guild=None):
            self.calls.append(("sync", getattr(guild, "id", None)))
            return []

        async def fetch_commands(self):
            self.calls.append(("fetch_commands", None))
            return [SimpleNamespace(name="play")]

        def clear_commands(self, guild=None) -> None:
            self.calls.append(("clear_commands", getattr(guild, "id", None)))

    tree = _FakeCommandTree()

    asyncio.run(sync_single_guild_app_commands(tree, 1231657902280937694, logging.getLogger("test")))

    assert tree.calls == [
        ("copy_global_to", 1231657902280937694),
        ("sync", 1231657902280937694),
        ("fetch_commands", None),
        ("clear_commands", None),
        ("sync", None),
    ]


def test_single_guild_sync_skips_global_purge_when_no_legacy_commands_exist() -> None:
    class _FakeCommandTree:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def copy_global_to(self, guild=None) -> None:
            self.calls.append(("copy_global_to", getattr(guild, "id", None)))

        async def sync(self, guild=None):
            self.calls.append(("sync", getattr(guild, "id", None)))
            return []

        async def fetch_commands(self):
            self.calls.append(("fetch_commands", None))
            return []

        def clear_commands(self, guild=None) -> None:
            self.calls.append(("clear_commands", getattr(guild, "id", None)))

    tree = _FakeCommandTree()

    asyncio.run(sync_single_guild_app_commands(tree, 1231657902280937694, logging.getLogger("test")))

    assert tree.calls == [
        ("copy_global_to", 1231657902280937694),
        ("sync", 1231657902280937694),
        ("fetch_commands", None),
    ]
