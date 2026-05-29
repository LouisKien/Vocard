from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time

from dataclasses import dataclass
from typing import Any, Optional

from .objects import Playlist, Track


SPOTIFY_PLAYLIST_URL_REGEX = re.compile(
    r"https?://open\.spotify\.com/playlist/(?P<id>[A-Za-z0-9]+)"
)


def _first_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def _env_enabled(*names: str, default: bool = False) -> bool:
    value = _first_env(*names)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def spotify_playlist_id_from_query(query: str) -> Optional[str]:
    match = SPOTIFY_PLAYLIST_URL_REGEX.match(query.strip())
    if not match:
        return None
    return match.group("id")


def spotify_fast_playlist_enabled() -> bool:
    return (
        _env_enabled("SPOTIFY_FAST_PLAYLIST_START", default=True)
        and bool(_first_env("LAVASRC_SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_ID"))
        and bool(_first_env("LAVASRC_SPOTIFY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET"))
    )


def spotify_country_code() -> str:
    return (_first_env("LAVASRC_SPOTIFY_COUNTRY_CODE", "SPOTIFY_COUNTRY_CODE", default="VN") or "VN").upper()


def spotify_custom_token_endpoint() -> Optional[str]:
    return _first_env("LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT", "SPOTIFY_CUSTOM_TOKEN_ENDPOINT")


def spotify_fast_playlist_backoff_seconds() -> int:
    raw_value = _first_env("SPOTIFY_FAST_PLAYLIST_BACKOFF_SECONDS", default="300")
    try:
        return max(int(raw_value or 300), 30)
    except (TypeError, ValueError):
        return 300


def extract_first_spotify_track_url(payload: dict[str, Any]) -> Optional[str]:
    tracks = payload.get("tracks", {})
    for item in tracks.get("items", []):
        track = item.get("track") if isinstance(item, dict) else None
        if not track or track.get("is_local"):
            continue

        external_url = ((track.get("external_urls") or {}).get("spotify"))
        if external_url:
            return external_url

        linked_from = track.get("linked_from") or {}
        linked_external = (linked_from.get("external_urls") or {}).get("spotify")
        if linked_external:
            return linked_external

        track_id = track.get("id") or linked_from.get("id")
        if track_id:
            return f"https://open.spotify.com/track/{track_id}"

    return None


@dataclass(slots=True)
class SpotifyPlaylistSeed:
    name: str
    uri: Optional[str]
    thumbnail: Optional[str]
    author: Optional[str]
    track_count: int
    first_track_url: str

    @classmethod
    def from_playlist_payload(cls, payload: dict[str, Any]) -> "SpotifyPlaylistSeed":
        first_track_url = extract_first_spotify_track_url(payload)
        if not first_track_url:
            raise ValueError("Spotify playlist payload does not contain a playable track URL")

        images = payload.get("images") or []
        owner = payload.get("owner") or {}
        playlist_url = (payload.get("external_urls") or {}).get("spotify")
        return cls(
            name=payload.get("name") or "Spotify Playlist",
            uri=playlist_url,
            thumbnail=images[0].get("url") if images else None,
            author=owner.get("display_name"),
            track_count=int((payload.get("tracks") or {}).get("total", 0)),
            first_track_url=first_track_url,
        )


def trim_seeded_track_from_playlist(playlist: Playlist, seeded_track: Track) -> list[Track]:
    remaining: list[Track] = []
    skipped = False
    for track in playlist.tracks:
        if not skipped and (
            (track.identifier and seeded_track.identifier and track.identifier == seeded_track.identifier)
            or (track.uri and seeded_track.uri and track.uri == seeded_track.uri)
        ):
            skipped = True
            continue
        remaining.append(track)
    return remaining


class SpotifyFastPathClient:
    def __init__(self, session, logger: Optional[logging.Logger] = None) -> None:
        self._session = session
        self._logger = logger
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._rate_limited_until: float = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _parse_retry_after(headers: dict[str, Any]) -> int:
        retry_after = headers.get("Retry-After") if headers else None
        try:
            return max(int(float(retry_after)), 1)
        except (TypeError, ValueError):
            return spotify_fast_playlist_backoff_seconds()

    def _activate_rate_limit_cooldown(self, headers: Optional[dict[str, Any]], *, reason: str) -> None:
        delay = self._parse_retry_after(headers or {})
        self._rate_limited_until = max(self._rate_limited_until, time.time() + delay)
        if self._logger:
            self._logger.warning(
                "Spotify fast-path disabled for %ss after rate limit: %s",
                delay,
                reason,
            )

    async def _get_custom_access_token(self) -> Optional[str]:
        endpoint = spotify_custom_token_endpoint()
        if not endpoint:
            return None

        async with self._session.request(method="GET", url=endpoint) as resp:
            if resp.status == 429:
                body = await resp.text()
                self._activate_rate_limit_cooldown(resp.headers, reason=f"custom token endpoint: {body}")
                return None
            if resp.status >= 300:
                body = await resp.text()
                raise RuntimeError(f"Spotify custom token request failed: {body}")

            payload = await resp.json()
            access_token = payload.get("accessToken") or payload.get("access_token")
            if not access_token:
                raise RuntimeError("Spotify custom token response did not include an access token")

            expiry_ms = payload.get("accessTokenExpirationTimestampMs")
            if expiry_ms:
                self._token_expires_at = max((int(expiry_ms) / 1000) - 60, time.time() + 60)
            else:
                self._token_expires_at = time.time() + max(int(payload.get("expires_in", 3600)) - 60, 60)
            self._token = access_token
            return self._token

    async def _get_access_token(self) -> Optional[str]:
        if not spotify_fast_playlist_enabled():
            return None
        if time.time() < self._rate_limited_until:
            return None
        if self._token and time.time() < self._token_expires_at:
            return self._token

        async with self._lock:
            if time.time() < self._rate_limited_until:
                return None
            if self._token and time.time() < self._token_expires_at:
                return self._token

            custom_token_endpoint = spotify_custom_token_endpoint()
            if custom_token_endpoint:
                return await self._get_custom_access_token()

            client_id = _first_env("LAVASRC_SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_ID")
            client_secret = _first_env("LAVASRC_SPOTIFY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET")
            if not client_id or not client_secret:
                return None

            basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf8")).decode("ascii")
            async with self._session.request(
                method="POST",
                url="https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {basic_auth}"},
                data={"grant_type": "client_credentials"},
            ) as resp:
                if resp.status == 429:
                    body = await resp.text()
                    self._activate_rate_limit_cooldown(resp.headers, reason=f"client credentials token: {body}")
                    return None
                if resp.status >= 300:
                    body = await resp.text()
                    raise RuntimeError(f"Spotify token request failed: {body}")

                payload = await resp.json()
                self._token = payload["access_token"]
                self._token_expires_at = time.time() + max(int(payload.get("expires_in", 3600)) - 60, 60)
                return self._token

    async def get_playlist_seed(self, query: str) -> Optional[SpotifyPlaylistSeed]:
        playlist_id = spotify_playlist_id_from_query(query)
        if not playlist_id or not spotify_fast_playlist_enabled():
            return None
        if time.time() < self._rate_limited_until:
            return None

        token = await self._get_access_token()
        if not token:
            return None

        fields = (
            "name,external_urls.spotify,images,owner.display_name,"
            "tracks.total,tracks.items(track(id,is_local,external_urls.spotify,linked_from.id,linked_from.external_urls.spotify))"
        )
        async with self._session.request(
            method="GET",
            url=f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": fields, "market": spotify_country_code()},
        ) as resp:
            if resp.status == 429:
                body = await resp.text()
                self._activate_rate_limit_cooldown(resp.headers, reason=f"playlist seed request: {body}")
                return None
            if resp.status >= 300:
                body = await resp.text()
                raise RuntimeError(f"Spotify playlist seed request failed: {body}")

            payload = await resp.json()
            return SpotifyPlaylistSeed.from_playlist_payload(payload)
