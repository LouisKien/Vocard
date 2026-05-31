from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from voicelink.enums import SearchType
from voicelink.exceptions import TrackLoadError
from voicelink.pool import Node


def test_node_get_tracks_logs_lavalink_fault_details(caplog) -> None:
    node = object.__new__(Node)
    node._identifier = "DEFAULT"
    node._logger = logging.getLogger("tests.track_lookup")

    async def noop_partner_api(_: bool) -> None:
        return None

    async def fake_send(method, path: str, *, timeout=None, data=None):
        assert "loadtracks?identifier=" in path
        return {
            "loadType": "error",
            "data": {
                "message": "Something went wrong while looking up the track.",
                "severity": "fault",
            },
        }

    node._set_lavasrc_spotify_partner_api = noop_partner_api
    node.send = fake_send

    query = "https://open.spotify.com/playlist/37i9dQZF1DX10zKzsJ2jva?si=test"
    requester = SimpleNamespace(id=123456789)

    with caplog.at_level(logging.ERROR, logger="tests.track_lookup"):
        with pytest.raises(TrackLoadError, match=r"Something went wrong while looking up the track\. \[fault\]"):
            asyncio.run(node.get_tracks(query, requester=requester, search_type=SearchType.YOUTUBE))

    assert "Track lookup failed on node [DEFAULT]" in caplog.text
    assert query in caplog.text
    assert "severity" in caplog.text
    assert "fault" in caplog.text


def test_spotify_urls_do_not_mutate_global_lavasrc_config_per_request() -> None:
    node = object.__new__(Node)
    node._identifier = "DEFAULT"
    node._logger = logging.getLogger("tests.track_lookup")

    async def should_not_be_called(_: bool) -> None:
        raise AssertionError("Node.get_tracks() must not patch global LavaSrc Spotify config per request")

    async def fake_send(method, path: str, *, timeout=None, data=None):
        assert "loadtracks?identifier=" in path
        return {"loadType": "empty"}

    node._set_lavasrc_spotify_partner_api = should_not_be_called
    node.send = fake_send

    requester = SimpleNamespace(id=123456789)

    assert asyncio.run(
        node.get_tracks(
            "https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
            requester=requester,
            search_type=SearchType.YOUTUBE,
        )
    ) is None

    assert asyncio.run(
        node.get_tracks(
            "https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=test",
            requester=requester,
            search_type=SearchType.YOUTUBE,
        )
    ) is None


def test_spotify_playlist_lookup_uses_extended_timeout_and_retries_once_on_timeout() -> None:
    node = object.__new__(Node)
    node._identifier = "DEFAULT"
    node._logger = logging.getLogger("tests.track_lookup")

    calls: list[float | None] = []

    async def fake_send(method, path: str, *, timeout=None, data=None):
        assert "loadtracks?identifier=" in path
        calls.append(getattr(timeout, "total", None))
        if len(calls) == 1:
            raise asyncio.TimeoutError()
        return {"loadType": "empty"}

    node.send = fake_send

    requester = SimpleNamespace(id=123456789)

    assert asyncio.run(
        node.get_tracks(
            "https://open.spotify.com/playlist/6XFOsAdp88ptBCdqUMAfmP?si=test",
            requester=requester,
            search_type=SearchType.YOUTUBE,
        )
    ) is None

    assert len(calls) == 2
    assert calls[0] == 90
    assert calls[1] == 90
