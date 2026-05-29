from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import voicelink

from cogs.basic import Basic
from function import sync_single_guild_app_commands
from voicelink.views.controller import Tracks
from voicelink.utils import TempCtx, dispatch_message

ROOT = Path(__file__).resolve().parents[1]


class _FakeTree:
    def add_command(self, _command) -> None:
        return None

    def remove_command(self, _name, type=None) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.tree = _FakeTree()


class _FakePlayer:
    def __init__(self, *, tracks, is_playing: bool = False) -> None:
        self._tracks = tracks
        self._is_playing = is_playing
        self.order: list[str] = []
        self.settings = {"lang": "VN", "silent_msg": False}
        self.channel = SimpleNamespace(mention="#music", members=[])
        self.node = SimpleNamespace(_available=True)
        self.current = SimpleNamespace(requester=SimpleNamespace())
        self.queue = SimpleNamespace(
            _repeat=SimpleNamespace(mode=voicelink.LoopType.OFF),
            skipto=lambda index: self.order.append(f"skipto:{index}"),
            backto=lambda index: self.order.append(f"backto:{index}"),
        )

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def is_user_join(self, _author) -> bool:
        return True

    def is_privileged(self, _author) -> bool:
        return True

    async def get_tracks(self, _query, requester=None):
        self.order.append("get_tracks")
        return self._tracks

    async def add_track(self, _tracks, **_kwargs):
        self.order.append("add_track")
        return 1

    async def do_next(self):
        self.order.append("do_next")
        self._is_playing = True

    async def stop(self):
        self.order.append("stop")

    async def set_repeat(self, mode):
        self.order.append(f"repeat:{mode.name}")


def _make_playlist() -> voicelink.Playlist:
    return voicelink.Playlist(
        playlist_info={"name": "Demo playlist"},
        tracks=[
            {
                "encoded": "abc",
                "info": {
                    "identifier": "id-1",
                    "title": "Song 1",
                    "author": "Artist",
                    "uri": "https://example.com/1",
                    "length": 1000,
                    "sourceName": "spotify",
                },
            }
        ],
        requester=SimpleNamespace(id=1),
    )


def test_play_starts_playlist_playback_before_sending_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="spotify-playlist", start="0", end="0"))

    assert player.order.index("do_next") < player.order.index("message")


def test_skip_stops_audio_before_sending_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=[], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(),
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        player.order.append("message")

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(Basic.skip.callback(cog, ctx, index=0))

    assert player.order.index("stop") < player.order.index("message")


def test_player_do_next_does_not_inline_await_controller_or_voice_status() -> None:
    player_source = (ROOT / "voicelink" / "player.py").read_text(encoding="utf8")
    module = ast.parse(player_source)
    do_next = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_next"
    )
    awaited_attrs = {
        node.value.func.attr
        for node in ast.walk(do_next)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
    }

    assert "invoke_controller" not in awaited_attrs
    assert "update_voice_status" not in awaited_attrs


def test_dispatch_message_uses_provided_settings_without_fetch(monkeypatch) -> None:
    sent_payload: dict = {}

    async def fail_get_settings(_guild_id: int):
        raise AssertionError("dispatch_message should reuse the provided settings snapshot")

    async def fake_send(*, content=None, embed=None, allowed_mentions=None, silent=False, delete_after=None, ephemeral=False, view=None, file=None):
        kwargs = {
            "content": content,
            "embed": embed,
            "allowed_mentions": allowed_mentions,
            "silent": silent,
            "delete_after": delete_after,
            "ephemeral": ephemeral,
            "view": view,
            "file": file,
        }
        sent_payload.update(kwargs)
        return SimpleNamespace()

    channel = SimpleNamespace(
        id=456,
        guild=SimpleNamespace(id=123),
        send=fake_send,
    )
    ctx = TempCtx(author=SimpleNamespace(), channel=channel)
    settings = {"silent_msg": True, "music_request_channel": {"text_channel_id": 456}}

    monkeypatch.setattr("voicelink.utils.MongoDBHandler.get_settings", fail_get_settings)

    asyncio.run(dispatch_message(ctx, "hello", settings=settings))

    assert sent_payload["silent"] is True
    assert sent_payload["delete_after"] == 10


def test_controller_tracks_dropdown_is_hard_capped_to_25_options() -> None:
    queue_tracks = [
        SimpleNamespace(
            title=f"Song {index}",
            author="Artist",
            formatted_length="03:00",
            is_stream=False,
            emoji="🎵",
        )
        for index in range(1, 31)
    ]
    player = SimpleNamespace(
        queue=SimpleNamespace(is_empty=False, tracks=lambda: queue_tracks),
        _ph=SimpleNamespace(replace=lambda value, _data: value),
        get_msg=lambda key: "TRUC TIEP" if key == "common.status.live" else key,
    )

    select = Tracks(player=player, btn_data={"label": "chon bai", "max_options": 10})

    assert len(select.options) == 25
    assert select.options[-1].label.startswith("25.")


def test_single_guild_sync_purges_legacy_global_commands() -> None:
    class _FakeCommandTree:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def copy_global_to(self, guild=None) -> None:
            self.calls.append(("copy_global_to", getattr(guild, "id", None)))

        async def sync(self, guild=None):
            self.calls.append(("sync", getattr(guild, "id", None)))
            return []

        async def fetch_commands(self):
            self.calls.append(("fetch_commands", None))
            return [SimpleNamespace(name="play")]

        def clear_commands(self, guild=None) -> None:
            self.calls.append(("clear_commands", getattr(guild, "id", None)))

    tree = _FakeCommandTree()

    asyncio.run(sync_single_guild_app_commands(tree, 1231657902280937694, logging.getLogger("test")))

    assert tree.calls == [
        ("copy_global_to", 1231657902280937694),
        ("sync", 1231657902280937694),
        ("fetch_commands", None),
        ("clear_commands", None),
        ("sync", None),
    ]


def test_single_guild_sync_skips_global_purge_when_no_legacy_commands_exist() -> None:
    class _FakeCommandTree:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def copy_global_to(self, guild=None) -> None:
            self.calls.append(("copy_global_to", getattr(guild, "id", None)))

        async def sync(self, guild=None):
            self.calls.append(("sync", getattr(guild, "id", None)))
            return []

        async def fetch_commands(self):
            self.calls.append(("fetch_commands", None))
            return []

        def clear_commands(self, guild=None) -> None:
            self.calls.append(("clear_commands", getattr(guild, "id", None)))

    tree = _FakeCommandTree()

    asyncio.run(sync_single_guild_app_commands(tree, 1231657902280937694, logging.getLogger("test")))

    assert tree.calls == [
        ("copy_global_to", 1231657902280937694),
        ("sync", 1231657902280937694),
        ("fetch_commands", None),
    ]
