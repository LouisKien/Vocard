from __future__ import annotations

import asyncio
from types import SimpleNamespace

import voicelink

from cogs.basic import Basic
from voicelink.spotify_fastpath import (
    SpotifyPlaylistSeed,
    SpotifyFastPathClient,
    extract_first_spotify_track_url,
    trim_seeded_track_from_playlist,
)


class _FakeTree:
    def add_command(self, _command) -> None:
        return None

    def remove_command(self, _name, type=None) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()


class _FakeFastPathPlayer:
    def __init__(self) -> None:
        self.settings = {"lang": "VN", "silent_msg": False}
        self.channel = SimpleNamespace(mention="#music", members=[])
        self.calls: list[str] = []
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def is_user_join(self, _author) -> bool:
        return True

    async def try_start_spotify_playlist_fast(self, _ctx, query, requester, **_kwargs):
        self.calls.append(f"fast:{query}")
        self._is_playing = True
        return SimpleNamespace(
            first_track=SimpleNamespace(
                title="Song 1",
                uri="https://open.spotify.com/track/track-1",
                author="Artist",
                formatted_length="00:42",
                is_stream=False,
            ),
            queue_position=0,
            playlist_name="Spotify Mix",
            track_count=25,
        )

    async def get_tracks(self, _query, requester=None):
        raise AssertionError("full playlist lookup should not run when fast-path succeeds")

    def get_msg(self, *_keys):
        return ["LIVE", "queued", "loaded"]


class _FakeFallbackPlayer(_FakeFastPathPlayer):
    def __init__(self) -> None:
        super().__init__()
        self._tracks = voicelink.Playlist(
            playlist_info={"name": "Fallback playlist"},
            tracks=[
                {
                    "encoded": "track-1",
                    "info": {
                        "identifier": "track-1",
                        "title": "Song 1",
                        "author": "Artist",
                        "uri": "https://open.spotify.com/track/track-1",
                        "length": 1000,
                        "sourceName": "spotify",
                    },
                }
            ],
            requester=SimpleNamespace(id=1),
        )

    async def try_start_spotify_playlist_fast(self, _ctx, query, requester, **_kwargs):
        self.calls.append(f"fast:{query}")
        return None

    async def get_tracks(self, query, requester=None):
        self.calls.append(f"lookup:{query}")
        return self._tracks

    async def add_track(self, _tracks, **_kwargs):
        self.calls.append("add_track")
        return 1

    async def do_next(self):
        self.calls.append("do_next")
        self._is_playing = True


class _FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return str(self._payload)


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, *, method, url, headers=None, params=None, data=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "params": params or {},
                "data": data,
            }
        )
        return self._responses.pop(0)


def test_extract_first_spotify_track_url_skips_local_and_missing_items() -> None:
    payload = {
        "name": "Spotify Mix",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-id"},
        "images": [{"url": "https://cdn.example/playlist.jpg"}],
        "owner": {"display_name": "Curator"},
        "tracks": {
            "total": 3,
            "items": [
                {"track": {"is_local": True, "external_urls": {"spotify": "https://open.spotify.com/track/local"}}},
                {"track": None},
                {"track": {"id": "track-1", "external_urls": {"spotify": "https://open.spotify.com/track/track-1"}}},
            ],
        },
    }

    assert extract_first_spotify_track_url(payload) == "https://open.spotify.com/track/track-1"


def test_trim_seeded_track_from_playlist_drops_the_first_duplicate() -> None:
    seeded = voicelink.Track(
        info={
            "identifier": "track-1",
            "title": "Song 1",
            "author": "Artist",
            "uri": "https://open.spotify.com/track/track-1",
            "length": 1000,
            "sourceName": "spotify",
        },
        requester=SimpleNamespace(id=1),
    )
    playlist = voicelink.Playlist(
        playlist_info={"name": "Spotify Mix"},
        tracks=[
            {
                "encoded": "track-1",
                "info": {
                    "identifier": "track-1",
                    "title": "Song 1",
                    "author": "Artist",
                    "uri": "https://open.spotify.com/track/track-1",
                    "length": 1000,
                    "sourceName": "spotify",
                },
            },
            {
                "encoded": "track-2",
                "info": {
                    "identifier": "track-2",
                    "title": "Song 2",
                    "author": "Artist",
                    "uri": "https://open.spotify.com/track/track-2",
                    "length": 1000,
                    "sourceName": "spotify",
                },
            },
        ],
        requester=SimpleNamespace(id=1),
    )

    remaining = trim_seeded_track_from_playlist(playlist, seeded)

    assert [track.identifier for track in remaining] == ["track-2"]


def test_play_uses_spotify_fast_path_for_playlist_urls(monkeypatch) -> None:
    player = _FakeFastPathPlayer()
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    messages: list[str] = []

    async def fake_dispatch_message(*_args, **_kwargs):
        messages.append("dispatched")

    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc",
            start="0",
            end="0",
        )
    )

    assert player.calls == ["fast:https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc"]
    assert messages == ["dispatched"]


def test_play_falls_back_to_existing_lookup_when_fast_path_returns_none(monkeypatch) -> None:
    player = _FakeFallbackPlayer()
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    messages: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        messages.append("playlist")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc",
            start="0",
            end="0",
        )
    )

    assert player.calls == [
        "fast:https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc",
        "lookup:https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=abc",
        "add_track",
        "do_next",
    ]
    assert messages == ["playlist"]


def test_spotify_playlist_seed_keeps_playlist_metadata() -> None:
    payload = {
        "name": "Spotify Mix",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-id"},
        "images": [{"url": "https://cdn.example/playlist.jpg"}],
        "owner": {"display_name": "Curator"},
        "tracks": {"total": 25, "items": [{"track": {"id": "track-1", "external_urls": {"spotify": "https://open.spotify.com/track/track-1"}}}]},
    }

    seed = SpotifyPlaylistSeed.from_playlist_payload(payload)

    assert seed.name == "Spotify Mix"
    assert seed.uri == "https://open.spotify.com/playlist/playlist-id"
    assert seed.thumbnail == "https://cdn.example/playlist.jpg"
    assert seed.author == "Curator"
    assert seed.track_count == 25
    assert seed.first_track_url == "https://open.spotify.com/track/track-1"


def test_fastpath_prefers_custom_token_endpoint_for_playlist_seed(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_FAST_PLAYLIST_START", "true")
    monkeypatch.setenv("LAVASRC_SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("LAVASRC_SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT", "http://spotify-tokener:8080/api/token")

    session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "accessToken": "anon-token",
                    "accessTokenExpirationTimestampMs": str(9_999_999_999_999),
                },
            ),
            _FakeResponse(
                200,
                {
                    "name": "Spotify Mix",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-id"},
                    "images": [{"url": "https://cdn.example/playlist.jpg"}],
                    "owner": {"display_name": "Curator"},
                    "tracks": {
                        "total": 25,
                        "items": [
                            {
                                "track": {
                                    "id": "track-1",
                                    "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
                                }
                            }
                        ],
                    },
                },
            ),
        ]
    )

    client = SpotifyFastPathClient(session)
    seed = asyncio.run(
        client.get_playlist_seed("https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=abc")
    )

    assert seed is not None
    assert seed.first_track_url == "https://open.spotify.com/track/track-1"
    assert session.calls[0]["url"] == "http://spotify-tokener:8080/api/token"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer anon-token"


def test_fastpath_uses_client_credentials_when_custom_token_endpoint_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_FAST_PLAYLIST_START", "true")
    monkeypatch.setenv("LAVASRC_SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("LAVASRC_SPOTIFY_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT", raising=False)
    monkeypatch.delenv("SPOTIFY_CUSTOM_TOKEN_ENDPOINT", raising=False)

    session = _FakeSession(
        [
            _FakeResponse(200, {"access_token": "client-token", "expires_in": 3600}),
            _FakeResponse(
                200,
                {
                    "name": "Spotify Mix",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-id"},
                    "images": [{"url": "https://cdn.example/playlist.jpg"}],
                    "owner": {"display_name": "Curator"},
                    "tracks": {
                        "total": 25,
                        "items": [
                            {
                                "track": {
                                    "id": "track-1",
                                    "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
                                }
                            }
                        ],
                    },
                },
            ),
        ]
    )

    client = SpotifyFastPathClient(session)
    seed = asyncio.run(
        client.get_playlist_seed("https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=abc")
    )

    assert seed is not None
    assert session.calls[0]["url"] == "https://accounts.spotify.com/api/token"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer client-token"
