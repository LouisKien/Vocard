from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import aiohttp

from voicelink.pool import Node


def test_node_listener_ignores_close_frames_without_attempting_json_decode(monkeypatch) -> None:
    node = object.__new__(Node)
    node._identifier = "DEFAULT"
    node._logger = logging.getLogger("tests.node_runtime")
    node._available = True
    node._bot = SimpleNamespace(loop=asyncio.new_event_loop())

    json_called = {"value": False}

    class _FakeWebSocket:
        async def receive(self):
            return SimpleNamespace(
                type=aiohttp.WSMsgType.CLOSE,
                data=1000,
                json=lambda: json_called.__setitem__("value", True),
            )

    reconnect_calls = {"count": 0}

    async def fake_connect():
        reconnect_calls["count"] += 1
        node._available = True

    node._websocket = _FakeWebSocket()
    node.connect = fake_connect

    monkeypatch.setattr("voicelink.pool.ExponentialBackoff.delay", lambda self: 0)

    try:
        asyncio.run(node._listen())
    finally:
        node._bot.loop.close()

    assert json_called["value"] is False
    assert reconnect_calls["count"] == 1
