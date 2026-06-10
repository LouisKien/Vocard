from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from voicelink.pool import NodePool
from voicelink.exceptions import TrackLoadError
import voicelink.song_resolver as song_resolver_module
from voicelink.song_resolver import ResolvedSong, SongResolverServer, resolve_song, search_songs


def test_resolve_song_returns_normalized_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object]:
            assert query == "See Tình"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return [
                SimpleNamespace(
                    title="See Tình",
                    author="Hoàng Thùy Linh",
                    source="youtube",
                    uri="https://www.youtube.com/watch?v=abc",
                    thumbnail="https://img.example/cover.jpg",
                    length=180000,
                    album_name=None,
                    album_url=None,
                    artist_url=None,
                    preview_url=None,
                    is_preview=False,
                    track_id="track-id",
                )
            ]

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))

    result = asyncio.run(resolve_song("See Tình", search_type="youtube"))

    assert result.title == "See Tình"
    assert result.author == "Hoàng Thùy Linh"
    assert result.source == "youtube"
    assert result.canonical_url == "https://www.youtube.com/watch?v=abc"
    assert result.search_query == "See Tình Hoàng Thùy Linh"
    assert result.duration_ms == 180000
    assert result.track_id == "track-id"
    assert result.resolved_by == "vocard"


def test_search_songs_returns_multiple_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object]:
            assert query == "See Tình"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return [
                SimpleNamespace(
                    title="See Tình",
                    author="Hoàng Thùy Linh",
                    source="youtube",
                    uri="https://www.youtube.com/watch?v=abc",
                    thumbnail="https://img.example/cover.jpg",
                    length=180000,
                    album_name=None,
                    album_url=None,
                    artist_url=None,
                    preview_url=None,
                    is_preview=False,
                    track_id="track-id-1",
                ),
                SimpleNamespace(
                    title="See Tình live",
                    author="Hoàng Thùy Linh",
                    source="youtube",
                    uri="https://www.youtube.com/watch?v=def",
                    thumbnail="https://img.example/live.jpg",
                    length=200000,
                    album_name=None,
                    album_url=None,
                    artist_url=None,
                    preview_url=None,
                    is_preview=False,
                    track_id="track-id-2",
                ),
            ]

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))

    results = asyncio.run(search_songs("See Tình", search_type="youtube", limit=2))

    assert [item.title for item in results] == ["See Tình", "See Tình live"]
    assert [item.track_id for item in results] == ["track-id-1", "track-id-2"]


def test_search_songs_returns_empty_list_when_no_tracks_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object] | None:
            assert query == "See Tình"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return None

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))

    results = asyncio.run(search_songs("See Tình", search_type="youtube", limit=5))

    assert results == []


def test_search_songs_ranks_exact_match_first(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object]:
            assert query == "Vì Sao Tôi Là Gay"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return [
                SimpleNamespace(
                    title="Bài khác hoàn toàn",
                    author="Ca sĩ khác",
                    source="youtube",
                    uri="https://www.youtube.com/watch?v=zzz",
                    thumbnail=None,
                    length=150000,
                    album_name=None,
                    album_url=None,
                    artist_url=None,
                    preview_url=None,
                    is_preview=False,
                    track_id="track-id-1",
                ),
                SimpleNamespace(
                    title="Vì Sao Tôi Là Gay",
                    author="MiiNa",
                    source="youtube",
                    uri="https://www.youtube.com/watch?v=exact",
                    thumbnail=None,
                    length=180000,
                    album_name=None,
                    album_url=None,
                    artist_url=None,
                    preview_url=None,
                    is_preview=False,
                    track_id="track-id-2",
                ),
            ]

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))

    results = asyncio.run(search_songs("Vì Sao Tôi Là Gay", search_type="youtube", limit=2))

    assert [item.title for item in results] == ["Vì Sao Tôi Là Gay", "Bài khác hoàn toàn"]


def test_search_songs_falls_back_to_direct_lookup_when_primary_search_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object] | None:
            assert query == "Feels"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return None

    class FakeYoutubeDL:
        def __init__(self, _options: dict[str, object]) -> None:
            return None

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def extract_info(self, query: str, download: bool = False) -> dict[str, object]:
            assert query == "ytsearch5:Feels"
            assert download is False
            return {
                "entries": [
                    {
                        "title": "Calvin Harris - Feels",
                        "uploader": "Calvin Harris",
                        "webpage_url": "https://www.youtube.com/watch?v=ozv4q2ov3Mk",
                        "duration": 223,
                        "thumbnail": "https://img.example/feels.jpg",
                    },
                    {
                        "title": "Feels ft. Pharrell Williams, Katy Perry, Big Sean",
                        "uploader": "Calvin Harris",
                        "webpage_url": "https://www.youtube.com/watch?v=jYH-fBHtFhc",
                        "duration": 223,
                        "thumbnail": "https://img.example/feels-2.jpg",
                    },
                    {
                        "title": "Feels acoustic",
                        "uploader": "Artist 3",
                        "webpage_url": "https://www.youtube.com/watch?v=feels-3",
                        "duration": 200,
                        "thumbnail": "https://img.example/feels-3.jpg",
                    },
                    {
                        "title": "Feels remix",
                        "uploader": "Artist 4",
                        "webpage_url": "https://www.youtube.com/watch?v=feels-4",
                        "duration": 210,
                        "thumbnail": "https://img.example/feels-4.jpg",
                    },
                    {
                        "title": "Feels live",
                        "uploader": "Artist 5",
                        "webpage_url": "https://www.youtube.com/watch?v=feels-5",
                        "duration": 205,
                        "thumbnail": "https://img.example/feels-5.jpg",
                    },
                ]
            }

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    results = asyncio.run(search_songs("Feels", search_type="youtube", limit=5))

    assert [result.title for result in results] == [
        "Calvin Harris - Feels",
        "Feels ft. Pharrell Williams, Katy Perry, Big Sean",
        "Feels acoustic",
        "Feels remix",
        "Feels live",
    ]
    assert [result.canonical_url for result in results] == [
        "https://www.youtube.com/watch?v=ozv4q2ov3Mk",
        "https://www.youtube.com/watch?v=jYH-fBHtFhc",
        "https://www.youtube.com/watch?v=feels-3",
        "https://www.youtube.com/watch?v=feels-4",
        "https://www.youtube.com/watch?v=feels-5",
    ]
    assert [result.duration_ms for result in results] == [223000, 223000, 200000, 210000, 205000]


def test_resolve_song_falls_back_to_direct_lookup_when_primary_search_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object] | None:
            assert query == "All Falls Down"
            assert requester is None
            assert getattr(search_type, "name", None) == "YOUTUBE"
            return None

    class FakeYoutubeDL:
        def __init__(self, _options: dict[str, object]) -> None:
            return None

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def extract_info(self, query: str, download: bool = False) -> dict[str, object]:
            assert query == "ytsearch1:All Falls Down"
            assert download is False
            return {
                "entries": [
                    {
                        "title": "Alan Walker - All Falls Down",
                        "uploader": "Alan Walker",
                        "webpage_url": "https://www.youtube.com/watch?v=6RLLOEzdxsM",
                        "duration": 211,
                        "thumbnail": "https://img.example/all-falls-down.jpg",
                    }
                ]
            }

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    result = asyncio.run(resolve_song("All Falls Down", search_type="youtube"))

    assert result.title == "Alan Walker - All Falls Down"
    assert result.author == "Alan Walker"
    assert result.canonical_url == "https://www.youtube.com/watch?v=6RLLOEzdxsM"
    assert result.duration_ms == 211000


def test_search_songs_does_not_use_direct_fallback_for_spotify_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify_url = "https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=test"

    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object] | None:
            assert query == spotify_url
            assert requester is None
            return None

    async def forbidden_direct_fallback(*_args, **_kwargs) -> list[ResolvedSong]:
        raise AssertionError("spotify URL search must stay on the primary Lavalink/LavaSrc path")

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))
    monkeypatch.setattr(song_resolver_module, "_search_songs_direct_fallback", forbidden_direct_fallback)

    results = asyncio.run(search_songs(spotify_url, search_type="youtube", limit=5))

    assert results == []


def test_resolve_song_does_not_use_direct_fallback_for_spotify_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify_url = "https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=test"

    class FakeNode:
        async def get_tracks(self, query: str, *, requester: object, search_type: object) -> list[object] | None:
            assert query == spotify_url
            assert requester is None
            return None

    async def forbidden_direct_fallback(*_args, **_kwargs) -> ResolvedSong | None:
        raise AssertionError("spotify URL resolve must stay on the primary Lavalink/LavaSrc path")

    monkeypatch.setattr(NodePool, "get_node", classmethod(lambda cls, identifier=None: FakeNode()))
    monkeypatch.setattr(song_resolver_module, "_resolve_song_direct_fallback", forbidden_direct_fallback)

    with pytest.raises(TrackLoadError, match="no tracks were returned"):
        asyncio.run(resolve_song(spotify_url, search_type="youtube"))


def test_song_resolver_http_resolve_response_is_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve_song(query: str, *, search_type: str | None = None) -> ResolvedSong:
        assert query == "See Tình"
        assert search_type is None
        return ResolvedSong(
            query="See Tình",
            search_type="YOUTUBE",
            title="See Tình",
            author="Hoàng Thùy Linh",
            source="youtube",
            canonical_url="https://www.youtube.com/watch?v=abc",
            search_query="See Tình Hoàng Thùy Linh",
            thumbnail="https://img.example/cover.jpg",
            duration_ms=180000,
            album_name=None,
            album_url=None,
            artist_url=None,
            preview_url=None,
            is_preview=False,
            track_id="track-id",
            is_playlist=False,
            playlist_name=None,
            track_count=1,
        )

    class FakeRequest:
        async def json(self) -> dict[str, str]:
            return {"query": "See Tình"}

    monkeypatch.setattr(song_resolver_module, "resolve_song", fake_resolve_song)

    server = SongResolverServer(host="127.0.0.1", port=8081)
    response = asyncio.run(server._handle_resolve(FakeRequest()))  # noqa: SLF001
    payload = json.loads(response.text)

    assert payload["query"] == "See Tình"
    assert payload["search_type"] == "YOUTUBE"
    assert payload["track"]["title"] == "See Tình"
    assert payload["track"]["author"] == "Hoàng Thùy Linh"


def test_song_resolver_http_search_returns_empty_track_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_songs(
        query: str,
        *,
        search_type: str | None = None,
        limit: int = 10,
    ) -> list[ResolvedSong]:
        assert query == "See Tình"
        assert search_type is None
        assert limit == 7
        return []

    class FakeRequest:
        async def json(self) -> dict[str, object]:
            return {"query": "See Tình", "limit": 7}

    monkeypatch.setattr(song_resolver_module, "search_songs", fake_search_songs)

    server = SongResolverServer(host="127.0.0.1", port=8081)
    response = asyncio.run(server._handle_search(FakeRequest()))  # noqa: SLF001
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {"query": "See Tình", "search_type": None, "tracks": []}
