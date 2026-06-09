from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from voicelink.pool import NodePool
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
