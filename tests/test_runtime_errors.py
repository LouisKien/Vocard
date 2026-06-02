from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from cogs.basic import Basic
from cogs.listeners import Listeners, sanitize_track_exception_message
from voicelink.language import LangHandler
from voicelink.lyrics import A_ZLyrics, _fetch_json, _fetch_text
from voicelink.player import Player

ROOT = Path(__file__).resolve().parents[1]


def test_youtube_track_exception_message_is_sanitized_for_discord_ui() -> None:
    raw_error = {
        "message": """
(yts.version: 1.18.1) All clients failed to load the item.

Client [ANDROID_VR] failed: This video is not availableThis video is not available
    at dev.lavalink.youtube.clients.skeleton.Client.getPlayabilityStatus(Client.java:77)
Client [WEB_EMBEDDED_PLAYER] failed: Video player configuration errorVideo player configuration error
    at dev.lavalink.youtube.track.YoutubeAudioTrack.process(YoutubeAudioTrack.java:120)
"""
    }

    message = sanitize_track_exception_message(raw_error, source_name="youtube")

    assert "All clients failed" not in message
    assert "Client [" not in message
    assert "at dev.lavalink" not in message
    assert "Không thể phát bài này" in message


def test_player_add_track_does_not_return_from_finally() -> None:
    player_source = (ROOT / "voicelink" / "player.py").read_text(encoding="utf8")
    module = ast.parse(player_source)
    add_track = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "add_track"
    )

    for try_node in (node for node in ast.walk(add_track) if isinstance(node, ast.Try)):
        assert not any(isinstance(node, ast.Return) for node in ast.walk(ast.Module(body=try_node.finalbody, type_ignores=[])))


def test_player_human_member_check_ignores_undeafened_bots() -> None:
    bot_member = SimpleNamespace(bot=True, voice=SimpleNamespace(self_deaf=False))
    human_member = SimpleNamespace(bot=False, voice=SimpleNamespace(self_deaf=True))

    assert Player._has_human_members([bot_member]) is False
    assert Player._has_human_members([bot_member, human_member]) is True


def test_azlyrics_html_parser_is_imported() -> None:
    find_all = A_ZLyrics().htmlFindAll("<html><b>Song</b></html>")

    assert find_all("b")[0].text == "Song"


def test_ipc_client_has_single_send_method() -> None:
    ipc_source = (ROOT / "voicelink" / "ipc" / "client.py").read_text(encoding="utf8")
    module = ast.parse(ipc_source)
    ipc_client = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef) and node.name == "IPCClient"
    )
    send_methods = [
        node for node in ipc_client.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "send"
    ]

    assert len(send_methods) == 1


def test_default_language_is_vietnamese() -> None:
    LangHandler.init()

    assert LangHandler._default_lang == "VN"
    assert LangHandler._get_lang(None, "player.errors.noTrackFound").startswith("Không tìm thấy")


def test_vietnamese_slash_command_localization_exists() -> None:
    vi_localization = json.loads((ROOT / "local_langs" / "vi.json").read_text(encoding="utf8"))

    assert vi_localization["Loads your input into the queue."] == "Thêm nội dung bạn nhập vào hàng đợi."
    assert vi_localization["Deezer"] == "Deezer"
    assert vi_localization["Lists all the bot commands."] == "Liệt kê toàn bộ lệnh của bot."
    assert vi_localization["Stage announce template"] == "Mẫu thông báo sân khấu"
    assert vi_localization["Which setting to restore to defaults."] == "Chọn cài đặt cần khôi phục về mặc định."
    reference_localization = json.loads((ROOT / "local_langs" / "es-ES.json").read_text(encoding="utf8"))
    assert set(reference_localization) <= set(vi_localization)


def test_fetch_text_returns_none_when_request_times_out(monkeypatch) -> None:
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *args, **kwargs):
            raise asyncio.TimeoutError()

    monkeypatch.setattr("voicelink.lyrics.aiohttp.ClientSession", lambda *args, **kwargs: _FakeSession())

    assert asyncio.run(_fetch_text("https://example.com")) is None


def test_fetch_json_returns_none_when_request_times_out(monkeypatch) -> None:
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *args, **kwargs):
            raise asyncio.TimeoutError()

    monkeypatch.setattr("voicelink.lyrics.aiohttp.ClientSession", lambda *args, **kwargs: _FakeSession())

    assert asyncio.run(_fetch_json("https://example.com")) is None


def test_lyrics_command_returns_not_found_when_safe_lookup_times_out(monkeypatch) -> None:
    cog = Basic(SimpleNamespace(tree=SimpleNamespace(add_command=lambda *_args, **_kwargs: None)))
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=None),
        author=SimpleNamespace(),
        deferred=False,
    )
    messages: list[str] = []

    async def fake_defer():
        ctx.deferred = True

    async def fake_send_localized_message(_ctx, key, *args, **kwargs):
        messages.append(key)
        return None

    async def fake_fetch_lyrics(_title, _artist):
        raise asyncio.TimeoutError()

    ctx.defer = fake_defer
    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.voicelink.fetch_lyrics", fake_fetch_lyrics)

    asyncio.run(Basic.lyrics.callback(cog, ctx, title="Song", artist="Artist"))

    assert ctx.deferred is True
    assert messages == ["lyrics.notFound"]


def test_track_exception_listener_schedules_recovery_and_notifies_user(monkeypatch) -> None:
    listener = object.__new__(Listeners)
    order: list[str] = []
    failed_track = SimpleNamespace(track_id="track-1", uri="https://example.com/1")

    async def fake_send(_message, delete_after=None):
        order.append("message")

    async def fake_sleep(seconds):
        order.append(f"sleep:{seconds}")

    async def fake_stop():
        order.append("stop")
        player._current = None

    async def fake_do_next():
        order.append("do_next")

    def fake_start_background_task(coro, label):
        order.append(label)
        return asyncio.create_task(coro)

    player = SimpleNamespace(
        _current=failed_track,
        current=failed_track,
        is_playing=True,
        _tearing_down=False,
        context=SimpleNamespace(send=fake_send),
        guild=SimpleNamespace(id=123),
        get_msg=lambda *_args: "Không thể phát bài này. Mình sẽ bỏ qua và phát bài tiếp theo sau 5 giây.",
        stop=fake_stop,
        do_next=fake_do_next,
        _start_background_task=fake_start_background_task,
        _track_exception_recovery_task=None,
    )

    monkeypatch.setattr("cogs.listeners.asyncio.sleep", fake_sleep)

    async def run_test():
        await Listeners.on_voicelink_track_exception(listener, player, failed_track, {"message": "Something broke when playing the track."})
        task = player._track_exception_recovery_task
        assert task is not None
        await task

    asyncio.run(run_test())

    assert order == ["track_exception_recovery", "message", "sleep:5", "stop", "do_next"]


def test_track_exception_recovery_skips_when_player_has_already_moved_on(monkeypatch) -> None:
    listener = object.__new__(Listeners)
    order: list[str] = []
    failed_track = SimpleNamespace(track_id="track-1", uri="https://example.com/1")
    next_track = SimpleNamespace(track_id="track-2", uri="https://example.com/2")

    async def fake_send(_message, delete_after=None):
        order.append("message")

    async def fake_sleep(seconds):
        order.append(f"sleep:{seconds}")
        player._current = next_track
        player.current = next_track

    async def fake_stop():
        order.append("stop")

    async def fake_do_next():
        order.append("do_next")

    def fake_start_background_task(coro, label):
        order.append(label)
        return asyncio.create_task(coro)

    player = SimpleNamespace(
        _current=failed_track,
        current=failed_track,
        is_playing=True,
        _tearing_down=False,
        context=SimpleNamespace(send=fake_send),
        guild=SimpleNamespace(id=123),
        get_msg=lambda *_args: "Không thể phát bài này. Mình sẽ bỏ qua và phát bài tiếp theo sau 5 giây.",
        stop=fake_stop,
        do_next=fake_do_next,
        _start_background_task=fake_start_background_task,
        _track_exception_recovery_task=None,
    )

    monkeypatch.setattr("cogs.listeners.asyncio.sleep", fake_sleep)

    async def run_test():
        await Listeners.on_voicelink_track_exception(listener, player, failed_track, {"message": "Something broke when playing the track."})
        task = player._track_exception_recovery_task
        assert task is not None
        await task

    asyncio.run(run_test())

    assert order == ["track_exception_recovery", "message", "sleep:5"]
