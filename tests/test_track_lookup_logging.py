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

    async def fake_send(method, path: str):
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
