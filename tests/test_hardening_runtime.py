from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp

from voicelink.pool import Node
from voicelink.utils import Ping


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeTask:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _FakePool:
    _nodes = {}


class _DummyBot:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=123456789)
        self.loop = asyncio.get_running_loop()

    def add_listener(self, *_args, **_kwargs) -> None:
        return None


async def _disconnect_node(session: aiohttp.ClientSession | None = None) -> tuple[Node, aiohttp.ClientSession]:
    node = Node(
        pool=_FakePool,
        bot=_DummyBot(),
        host="127.0.0.1",
        port=2333,
        password="secret",
        identifier="DEFAULT",
        session=session,
    )
    node._websocket = _FakeWebSocket()
    node._task = _FakeTask()
    node._available = True

    await node.disconnect()
    return node, node._session


def test_ping_timer_uses_valid_clock_functions() -> None:
    timer = Ping.Timer()

    timer.start()
    timer.stop()

    assert timer._stop >= timer._start


def test_owned_node_session_closes_on_disconnect() -> None:
    node, session = asyncio.run(_disconnect_node())

    assert node._owns_session is True
    assert session.closed is True
    assert node._task.cancel_calls == 1
    assert node._websocket.close_calls == 1


def test_external_node_session_is_not_closed_on_disconnect() -> None:
    async def _run() -> tuple[Node, aiohttp.ClientSession]:
        external_session = aiohttp.ClientSession()
        node, _ = await _disconnect_node(external_session)
        return node, external_session

    node, session = asyncio.run(_run())

    try:
        assert node._owns_session is False
        assert session.closed is False
    finally:
        asyncio.run(session.close())


def test_owned_node_session_uses_conservative_timeout_defaults() -> None:
    async def _run() -> tuple[float | None, int]:
        node = Node(
            pool=_FakePool,
            bot=_DummyBot(),
            host="127.0.0.1",
            port=2333,
            password="secret",
            identifier="DEFAULT",
        )
        try:
            timeout_total = node._session.timeout.total
            connector_limit = node._session.connector.limit
            return timeout_total, connector_limit
        finally:
            await node._session.close()

    timeout_total, connector_limit = asyncio.run(_run())

    assert timeout_total == 30
    assert connector_limit == 20
