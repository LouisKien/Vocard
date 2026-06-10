from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from aiohttp import web

from .config import Config
from .enums import SearchType
from .exceptions import NoNodesAvailable, TrackLoadError
from .objects import Playlist, Track
from .pool import NodePool

logger = logging.getLogger(__name__)
AUTOCOMPLETE_LOOKUP_TIMEOUT_SECONDS = 1.0
AUTOCOMPLETE_DIRECT_LOOKUP_TIMEOUT_SECONDS = 1.8
DIRECT_RESOLVE_TIMEOUT_SECONDS = 4.0
_LOW_SIGNAL_TRACK_TERMS = {
    "cover",
    "karaoke",
    "instrumental",
    "live",
    "remix",
    "slowed",
    "reverb",
    "sped",
    "speed",
    "up",
    "nightcore",
    "short",
    "ver",
    "version",
}


@dataclass(frozen=True)
class ResolvedSong:
    query: str
    search_type: str
    title: str
    author: str
    source: str
    canonical_url: str
    search_query: str
    thumbnail: str | None
    duration_ms: int | None
    album_name: str | None
    album_url: str | None
    artist_url: str | None
    preview_url: str | None
    is_preview: bool
    track_id: str | None
    is_playlist: bool
    playlist_name: str | None
    track_count: int
    resolved_by: str = "vocard"


async def resolve_song(query: str, *, search_type: str | None = None) -> ResolvedSong:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")

    node = NodePool.get_node()
    resolved_search_type = SearchType.from_platform(search_type) if search_type else Config().search_platform
    try:
        track, is_playlist, playlist_name, track_count = await _lookup_first_track(
            node,
            normalized_query,
            resolved_search_type,
        )
    except (NoNodesAvailable, TrackLoadError) as exc:
        fallback = await _resolve_song_direct_fallback(
            normalized_query,
            search_type=resolved_search_type.name,
        )
        if fallback is not None:
            logger.debug("Resolved %r through direct fallback after primary lookup failed: %s", normalized_query, exc)
            return fallback
        raise
    return _track_to_resolution(
        track,
        query=normalized_query,
        search_type=resolved_search_type.name,
        is_playlist=is_playlist,
        playlist_name=playlist_name,
        track_count=track_count,
    )


async def search_songs(
    query: str,
    *,
    search_type: str | None = None,
    limit: int = 10,
) -> list[ResolvedSong]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")

    node = NodePool.get_node()
    resolved_search_type = SearchType.from_platform(search_type) if search_type else Config().search_platform
    try:
        tracks = await asyncio.wait_for(
            node.get_tracks(normalized_query, requester=None, search_type=resolved_search_type),
            timeout=AUTOCOMPLETE_LOOKUP_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, NoNodesAvailable, TrackLoadError) as exc:
        logger.debug("Song resolver search returned no quick result for query=%r: %s", normalized_query, exc)
        return await _search_songs_direct_fallback(
            normalized_query,
            search_type=resolved_search_type.name,
            limit=limit,
        )
    if isinstance(tracks, Playlist):
        if not tracks.tracks:
            return await _search_songs_direct_fallback(
                normalized_query,
                search_type=resolved_search_type.name,
                limit=limit,
            )
        track_items = _rank_tracks(normalized_query, tracks.tracks)[:limit]
        return [
            _track_to_resolution(
                track,
                query=normalized_query,
                search_type=resolved_search_type.name,
                is_playlist=True,
                playlist_name=tracks.name,
                track_count=tracks.track_count,
            )
            for track in track_items
        ]
    if not tracks:
        return await _search_songs_direct_fallback(
            normalized_query,
            search_type=resolved_search_type.name,
            limit=limit,
        )
    ranked_tracks = _rank_tracks(normalized_query, list(tracks))
    return [
        _track_to_resolution(
            track,
            query=normalized_query,
            search_type=resolved_search_type.name,
            is_playlist=False,
            playlist_name=None,
            track_count=1,
        )
        for track in ranked_tracks[:limit]
    ]


class SongResolverServer:
    def __init__(self, *, host: str = "0.0.0.0", port: int = 8081) -> None:
        self._host = host
        self._port = port
        self._app = web.Application()
        self._app.add_routes(
            [
                web.get("/healthz", self._handle_health),
                web.post("/api/song/resolve", self._handle_resolve),
                web.post("/api/song/search", self._handle_search),
            ]
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()

    async def close(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def _handle_health(self, _: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _handle_resolve(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": "invalid json", "detail": str(exc)}, status=400)

        if not isinstance(payload, dict):
            return web.json_response({"error": "payload must be an object"}, status=400)

        query = str(payload.get("query") or "").strip()
        search_type = payload.get("search_type")
        try:
            result = await resolve_song(query, search_type=str(search_type) if search_type is not None else None)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except NoNodesAvailable as exc:
            return web.json_response({"error": str(exc)}, status=503)
        except TrackLoadError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=502)

        return web.json_response(_resolved_song_to_payload(result))

    async def _handle_search(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": "invalid json", "detail": str(exc)}, status=400)

        if not isinstance(payload, dict):
            return web.json_response({"error": "payload must be an object"}, status=400)

        query = str(payload.get("query") or "").strip()
        search_type = payload.get("search_type")
        limit = _coerce_limit(payload.get("limit"), default=10, maximum=25)
        try:
            results = await search_songs(
                query,
                search_type=str(search_type) if search_type is not None else None,
                limit=limit,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except NoNodesAvailable as exc:
            return web.json_response({"error": str(exc)}, status=503)
        except TrackLoadError as exc:
            logger.debug("Song resolver search returning empty track list for query=%r: %s", query, exc)
            results = []
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=502)

        return web.json_response(
            {
                "query": query,
                "search_type": str(search_type) if search_type is not None else None,
                "tracks": [_resolved_song_to_payload(result)["track"] for result in results],
            }
        )


def _track_to_resolution(
    track: Track,
    *,
    query: str,
    search_type: str,
    is_playlist: bool,
    playlist_name: str | None,
    track_count: int,
) -> ResolvedSong:
    search_query = f"{track.title} {track.author}".strip()
    return ResolvedSong(
        query=query,
        search_type=search_type,
        title=track.title,
        author=track.author,
        source=track.source,
        canonical_url=track.uri,
        search_query=search_query,
        thumbnail=track.thumbnail,
        duration_ms=_coerce_int(track.length),
        album_name=track.album_name,
        album_url=track.album_url,
        artist_url=track.artist_url,
        preview_url=track.preview_url,
        is_preview=track.is_preview,
        track_id=track.track_id,
        is_playlist=is_playlist,
        playlist_name=playlist_name,
        track_count=track_count,
    )


async def _lookup_first_track(
    node: Any,
    query: str,
    search_type: SearchType,
) -> tuple[Track, bool, str | None, int]:
    tracks = await node.get_tracks(query, requester=None, search_type=search_type)
    if isinstance(tracks, Playlist):
        if not tracks.tracks:
            raise TrackLoadError("playlist returned no tracks")
        return tracks.tracks[0], True, tracks.name, tracks.track_count
    if not tracks:
        raise TrackLoadError("no tracks were returned")
    ranked_tracks = _rank_tracks(query, list(tracks))
    return ranked_tracks[0], False, None, 1


def _resolved_song_to_payload(result: ResolvedSong) -> dict[str, Any]:
    return {
        "query": result.query,
        "search_type": result.search_type,
        "track": {
            "title": result.title,
            "author": result.author,
            "sourceName": result.source,
            "uri": result.canonical_url,
            "search_query": result.search_query,
            "thumbnail": result.thumbnail,
            "length": result.duration_ms,
            "albumName": result.album_name,
            "albumUrl": result.album_url,
            "artistUrl": result.artist_url,
            "previewUrl": result.preview_url,
            "isPreview": result.is_preview,
            "track_id": result.track_id,
            "is_playlist": result.is_playlist,
            "playlist_name": result.playlist_name,
            "track_count": result.track_count,
            "resolved_by": result.resolved_by,
        },
    }


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_limit(value: Any, *, default: int, maximum: int) -> int:
    parsed = _coerce_int(value)
    if parsed is None:
        return default
    return max(1, min(maximum, parsed))


def _rank_tracks(query: str, tracks: list[Track]) -> list[Track]:
    return sorted(
        tracks,
        key=lambda track: _song_match_score(
            query,
            title=track.title,
            author=track.author,
            canonical_url=track.uri,
        ),
        reverse=True,
    )


def _song_match_score(query: str, *, title: str, author: str, canonical_url: str) -> int:
    normalized_query = _normalize_match_text(query)
    normalized_title = _normalize_match_text(title)
    normalized_author = _normalize_match_text(author)
    normalized_url = canonical_url.strip().lower()
    combined = " ".join(part for part in (normalized_title, normalized_author) if part).strip()
    query_tokens = set(normalized_query.split())
    candidate_tokens = set(combined.split())

    score = 0
    raw_query = query.strip().lower()
    if raw_query and normalized_url == raw_query:
        score += 2200
    if normalized_title == normalized_query:
        score += 1400
    if combined == normalized_query:
        score += 1300
    if normalized_title.startswith(normalized_query) and normalized_query:
        score += 1000
    if normalized_query and normalized_query in normalized_title:
        score += 850
    if combined.startswith(normalized_query) and normalized_query:
        score += 700
    if normalized_query and normalized_query in combined:
        score += 600
    if raw_query and raw_query in normalized_url:
        score += 250
    if query_tokens:
        score += int(320 * len(query_tokens & candidate_tokens) / len(query_tokens))
    noisy_terms = (candidate_tokens - query_tokens) & _LOW_SIGNAL_TRACK_TERMS
    score -= 70 * len(noisy_terms)
    if normalized_title in {"", "unknown"}:
        score -= 500
    if normalized_author in {"", "unknown"}:
        score -= 120
    return score


def _normalize_match_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    collapsed = re.sub(r"[^a-z0-9]+", " ", without_accents.lower())
    return " ".join(collapsed.split())


async def _resolve_song_direct_fallback(query: str, *, search_type: str) -> ResolvedSong | None:
    results = await _search_songs_direct_fallback(
        query,
        search_type=search_type,
        limit=1,
        timeout_seconds=DIRECT_RESOLVE_TIMEOUT_SECONDS,
    )
    if not results:
        return None
    return results[0]


async def _search_songs_direct_fallback(
    query: str,
    *,
    search_type: str,
    limit: int,
    timeout_seconds: float = AUTOCOMPLETE_DIRECT_LOOKUP_TIMEOUT_SECONDS,
) -> list[ResolvedSong]:
    if limit < 1:
        return []
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _search_songs_directly,
                query,
                search_type,
                limit,
            ),
            timeout=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Direct song fallback returned no result for query=%r: %s", query, exc, exc_info=True)
        return []


def _search_songs_directly(query: str, search_type: str, limit: int) -> list[ResolvedSong]:
    ytdlp = _load_yt_dlp()
    direct_limit = max(1, min(limit, 1))
    candidates = _build_direct_candidates(query, limit=direct_limit)
    last_error: Exception | None = None
    with ytdlp.YoutubeDL(_ytdlp_options()) as ydl:
        for candidate in candidates:
            try:
                info = ydl.extract_info(candidate, download=False)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            results = [
                result
                for result in (
                    _resolved_song_from_ytdlp_entry(entry, query=query, search_type=search_type)
                    for entry in _flatten_ytdlp_entries(info)
                )
                if result is not None
            ]
            if results:
                return results[:direct_limit]
    if last_error is not None:
        raise last_error
    return []


def _build_direct_candidates(query: str, *, limit: int) -> list[str]:
    normalized_query = query.strip()
    if _is_probably_url(normalized_query):
        return [normalized_query]
    return [f"ytsearch{max(1, limit)}:{normalized_query}"]


def _load_yt_dlp() -> Any:
    try:
        import yt_dlp  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"yt-dlp is unavailable: {exc}") from exc
    return yt_dlp


def _ytdlp_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
    }


def _flatten_ytdlp_entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries")
    if isinstance(entries, list) and entries:
        flattened: list[dict[str, Any]] = []
        for entry in entries:
            if isinstance(entry, dict):
                flattened.extend(_flatten_ytdlp_entries(entry))
        return flattened
    return [info] if isinstance(info, dict) else []


def _resolved_song_from_ytdlp_entry(
    entry: dict[str, Any],
    *,
    query: str,
    search_type: str,
) -> ResolvedSong | None:
    canonical_url = _ytdlp_entry_url(entry, query=query)
    if not canonical_url:
        return None
    title = str(entry.get("title") or query).strip() or query
    author = str(
        entry.get("uploader")
        or entry.get("channel")
        or entry.get("artist")
        or "Unknown"
    ).strip() or "Unknown"
    duration_seconds = _coerce_int(entry.get("duration"))
    duration_ms = duration_seconds * 1000 if duration_seconds is not None else None
    thumbnail = str(entry.get("thumbnail") or "").strip() or None
    return ResolvedSong(
        query=query,
        search_type=search_type,
        title=title,
        author=author,
        source=_infer_source_from_url(canonical_url),
        canonical_url=canonical_url,
        search_query=f"{title} {author}".strip(),
        thumbnail=thumbnail,
        duration_ms=duration_ms,
        album_name=None,
        album_url=None,
        artist_url=None,
        preview_url=None,
        is_preview=False,
        track_id=str(entry.get("id") or "").strip() or None,
        is_playlist=False,
        playlist_name=None,
        track_count=1,
        resolved_by="direct",
    )


def _ytdlp_entry_url(entry: dict[str, Any], *, query: str) -> str | None:
    for key in ("webpage_url", "url", "original_url"):
        value = str(entry.get(key) or "").strip()
        if _is_probably_url(value):
            return value
    entry_id = str(entry.get("id") or "").strip()
    extractor = str(entry.get("extractor_key") or entry.get("ie_key") or "").lower()
    if entry_id and "youtube" in extractor:
        return f"https://www.youtube.com/watch?v={entry_id}"
    return query if _is_probably_url(query) else None


def _infer_source_from_url(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    if "soundcloud.com" in hostname:
        return "soundcloud"
    if "spotify.com" in hostname:
        return "spotify"
    return "youtube"


def _is_probably_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)
