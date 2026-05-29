from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from voicelink.ipc.client import IPCClient
from voicelink.lyrics import Genius
from voicelink.placeholders import PlayerPlaceholder
from voicelink.transformer import encode


ROOT = Path(__file__).resolve().parents[1]


class _FakeWebSocket:
    def __init__(self) -> None:
        self.close_calls = 0
        self.closed = False

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0
        self.closed = False

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeTask:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


def _make_placeholder() -> PlayerPlaceholder:
    bot_user = SimpleNamespace(
        id=1504518286073659595,
        display_name="CátFanSiTạ",
        display_avatar=SimpleNamespace(url="https://example.com/bot.png"),
        mention="<@1504518286073659595>",
    )
    return PlayerPlaceholder(SimpleNamespace(user=bot_user), player=None)


def test_placeholder_conditionals_support_current_template_comparisons_without_eval() -> None:
    placeholder = _make_placeholder()

    assert placeholder.replace("{{@@track_name@@ != 'None' ?? playing // idle}}", {"track_name": "Song"}) == "playing"
    assert placeholder.replace("{{@@queue_length@@ > 0 ?? queued // empty}}", {"queue_length": "2"}) == "queued"

    source = (ROOT / "voicelink" / "placeholders.py").read_text(encoding="utf8")
    assert "eval(" not in source


def test_placeholder_conditionals_reject_unsafe_expressions() -> None:
    placeholder = _make_placeholder()

    assert placeholder.replace("{{__import__('os').system('true') ?? unsafe // safe}}", {}) == ""
    assert placeholder.replace("{{(lambda: 1)() ?? unsafe // safe}}", {}) == ""


def test_update_script_no_longer_executes_remote_migration_code() -> None:
    source = (ROOT / "update.py").read_text(encoding="utf8")

    assert "MIGRATION_SCRIPT_URL" not in source
    assert "subprocess.run([PYTHON_CMD_NAME, migration_filename], check=True)" not in source
    assert "requests.get(GITHUB_API_URL, timeout=" in source
    assert "requests.get(VOCARD_URL + version + \".zip\", timeout=" in source


def test_mongodb_uri_redaction_masks_credentials() -> None:
    from voicelink.mongodb import _redact_mongodb_uri

    assert _redact_mongodb_uri("mongodb://mongo:secret@mongo:27017/?authSource=admin") == "mongodb://mongo:***@mongo:27017/?authSource=admin"
    assert _redact_mongodb_uri("mongodb://mongo:27017") == "mongodb://mongo:27017"


def test_ipc_disconnect_closes_transport_and_session() -> None:
    async def _run() -> tuple[IPCClient, _FakeWebSocket, _FakeSession, _FakeTask]:
        bot = SimpleNamespace(user=SimpleNamespace(id=123456789), loop=asyncio.get_running_loop())
        client = IPCClient(bot=bot, host="127.0.0.1", port=8000, password="secret")
        websocket = _FakeWebSocket()
        session = _FakeSession()
        task = _FakeTask()

        client._websocket = websocket
        client._session = session
        client._task = task
        client._is_connected = True

        await client.disconnect()
        return client, websocket, session, task

    client, websocket, session, task = asyncio.run(_run())

    assert client.is_connected is False
    assert websocket.close_calls == 1
    assert session.close_calls == 1
    assert task.cancel_calls == 1


def test_ipc_disconnect_is_idempotent_without_active_resources() -> None:
    async def _run() -> None:
        bot = SimpleNamespace(user=SimpleNamespace(id=123456789), loop=asyncio.get_running_loop())
        client = IPCClient(bot=bot, host="127.0.0.1", port=8000, password="secret")
        await client.disconnect()

    asyncio.run(_run())


def test_genius_lyrics_lookup_runs_in_worker_thread(monkeypatch) -> None:
    provider = Genius.__new__(Genius)
    provider.genius = SimpleNamespace(search_song=lambda title, artist: SimpleNamespace(lyrics=f"{artist}:{title}"))
    calls: dict[str, object] = {}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr("voicelink.lyrics.asyncio.to_thread", fake_to_thread)

    result = asyncio.run(provider.get_lyrics("Beauty And A Beat", "Justin Bieber"))

    assert calls["func"] is provider.genius.search_song
    assert result == {"default": "Justin Bieber:Beauty And A Beat"}


def test_bot_container_runs_as_non_root_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf8")
    compose_yml = (ROOT / "docker-compose.yml").read_text(encoding="utf8")

    assert "adduser" in dockerfile or "useradd" in dockerfile
    assert "USER vocard" in dockerfile
    assert 'user: "0:0"' not in compose_yml


def test_transformer_encode_rejects_incomplete_tracks_without_assert() -> None:
    with pytest.raises(ValueError, match="Missing required track keys"):
        encode({"title": "Broken"})

    transformer_source = (ROOT / "voicelink" / "transformer.py").read_text(encoding="utf8")
    player_source = (ROOT / "voicelink" / "player.py").read_text(encoding="utf8")

    assert "assert V3_KEYSET <= track.keys()" not in transformer_source
    assert "assert self.channel is None and not self.is_connected" not in player_source
