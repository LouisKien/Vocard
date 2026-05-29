from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import discord
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

    async def get_tracks(self, _query, requester=None, search_type=None):
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

    def get_msg(self, *_keys):
        return ("LIVE", "TRACK_LOAD_POS", "TRACK_LOAD")

    async def refresh_controller_after_queue_update(self):
        self.order.append("refresh_controller")


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


def test_play_refreshes_controller_after_track_confirmation(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Song",
        uri="https://example.com/song",
        author="Artist",
        formatted_length="03:00",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_dispatch_message(*_args, **_kwargs):
        player.order.append("message")
        return None

    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(Basic.play.callback(cog, ctx, query="https://example.com/song", start="0", end="0"))

    assert player.order.index("message") < player.order.index("refresh_controller")


def test_play_refreshes_controller_after_playlist_confirmation(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=True)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    async def fake_send_localized_message(*_args, **_kwargs):
        if _args[1] == "player.playback.playlistLoad":
            player.order.append("message")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
            start="0",
            end="0",
        )
    )

    assert player.order.index("message") < player.order.index("refresh_controller")


def test_play_sends_spotify_playlist_loading_notice_before_lookup_and_cleans_it_up(monkeypatch) -> None:
    player = _FakePlayer(tracks=_make_playlist(), is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())

    class _LoadingMessage:
        async def delete(self):
            player.order.append("delete_loading")

    async def fake_send_localized_message(*_args, **_kwargs):
        key = _args[1]
        if key == "player.playback.spotifyPlaylistLoading":
            player.order.append("loading")
            return _LoadingMessage()
        if key == "player.playback.playlistLoad":
            player.order.append("playlistLoad")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/playlist/37i9dQZF1DWVOaOWiVD1Lf?si=test",
            start="0",
            end="0",
        )
    )

    assert player.order.index("loading") < player.order.index("get_tracks")
    assert player.order.index("get_tracks") < player.order.index("delete_loading")
    assert player.order.index("delete_loading") < player.order.index("playlistLoad")


def test_play_does_not_send_spotify_playlist_loading_notice_for_spotify_track(monkeypatch) -> None:
    track = SimpleNamespace(
        title="Beauty And A Beat",
        uri="https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk",
        author="Justin Bieber",
        formatted_length="03:47",
        is_stream=False,
    )
    player = _FakePlayer(tracks=[track], is_playing=False)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(voice_client=player, id=123),
        author=SimpleNamespace(mention="@user"),
        interaction=None,
    )
    cog = Basic(_FakeBot())
    sent_keys: list[str] = []

    async def fake_send_localized_message(*_args, **_kwargs):
        sent_keys.append(_args[1])
        return None

    async def fake_dispatch_message(*_args, **_kwargs):
        sent_keys.append("dispatch")
        return None

    monkeypatch.setattr("cogs.basic.send_localized_message", fake_send_localized_message)
    monkeypatch.setattr("cogs.basic.dispatch_message", fake_dispatch_message)

    asyncio.run(
        Basic.play.callback(
            cog,
            ctx,
            query="https://open.spotify.com/track/190jyVPHYjAqEaOGmMzdyk?si=test",
            start="0",
            end="0",
        )
    )

    assert "player.playback.spotifyPlaylistLoading" not in sent_keys
    assert "dispatch" in sent_keys


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


def test_invoke_controller_uses_channel_context_instead_of_interaction_response(monkeypatch) -> None:
    captured = {}

    async def fake_dispatch_message(ctx, content=None, **kwargs):
        captured["ctx"] = ctx
        captured["content"] = content
        captured["kwargs"] = kwargs
        return SimpleNamespace(id=42)

    monkeypatch.setattr("voicelink.player.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    fake_channel = SimpleNamespace(send=None, guild=SimpleNamespace(id=123))
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=None,
        bot=SimpleNamespace(get_channel=lambda _id: None),
        context=SimpleNamespace(channel=fake_channel),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
    )

    asyncio.run(voicelink.Player.invoke_controller(fake_player))

    assert isinstance(captured["ctx"], TempCtx)
    assert captured["ctx"].channel is fake_channel


def test_invoke_controller_reposts_new_message_for_forced_queue_update(monkeypatch) -> None:
    deleted: list[str] = []
    dispatched: list[int] = []

    async def fake_dispatch_message(ctx, content=None, **kwargs):
        dispatched.append(ctx.channel.id)
        return SimpleNamespace(id=99)

    async def fail_is_position_fresh():
        raise AssertionError("Forced controller refresh should not depend on position freshness")

    old_controller = SimpleNamespace(id=42, delete=lambda: deleted.append("old"))

    monkeypatch.setattr("voicelink.player.dispatch_message", fake_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    async def delete_old():
        deleted.append("old")

    old_controller.delete = delete_old

    fake_channel = SimpleNamespace(id=456, send=None, guild=SimpleNamespace(id=123))
    fake_player = SimpleNamespace(
        settings={"controller": True},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=old_controller,
        bot=SimpleNamespace(get_channel=lambda _id: None),
        context=SimpleNamespace(channel=fake_channel),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
        is_position_fresh=fail_is_position_fresh,
    )
    fake_player._replace_controller_message = voicelink.Player._replace_controller_message.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=True))

    assert deleted == ["old"]
    assert dispatched == [456]
    assert fake_player.controller.id == 99


def test_invoke_controller_keeps_sticky_request_channel_message_when_forced(monkeypatch) -> None:
    edited: list[str] = []

    async def fake_edit(*, embed=None, view=None):
        edited.append("edited")

    fetched_message = SimpleNamespace(id=55, edit=fake_edit)

    async def fake_fetch_message(message_id):
        assert message_id == 55
        return fetched_message

    def get_channel(channel_id):
        assert channel_id == 777
        return SimpleNamespace(fetch_message=fake_fetch_message, guild=SimpleNamespace(id=123))

    async def fail_dispatch_message(*_args, **_kwargs):
        raise AssertionError("Sticky request-channel controller should be edited instead of re-posted")

    monkeypatch.setattr("voicelink.player.dispatch_message", fail_dispatch_message)
    monkeypatch.setattr("voicelink.player.InteractiveController", lambda player: SimpleNamespace())

    fake_player = SimpleNamespace(
        settings={"controller": True, "music_request_channel": {"text_channel_id": 777, "controller_msg_id": 55}},
        _updating=False,
        channel=SimpleNamespace(),
        build_embed=lambda current: "embed",
        current=SimpleNamespace(),
        controller=None,
        bot=SimpleNamespace(get_channel=get_channel),
        context=SimpleNamespace(channel=SimpleNamespace(id=456)),
        dj=SimpleNamespace(),
        guild=SimpleNamespace(name="Guild", id=123),
        _logger=logging.getLogger("test"),
    )
    fake_player._replace_controller_message = voicelink.Player._replace_controller_message.__get__(fake_player, type(fake_player))

    asyncio.run(voicelink.Player.invoke_controller(fake_player, prefer_new_message=True))

    assert edited == ["edited"]
    assert fake_player.controller is fetched_message


def test_voice_status_cleanup_clears_status_even_when_cached_channel_status_is_missing() -> None:
    recorded = {}

    async def fake_edit(*, status=None):
        recorded["status"] = status

    channel = SimpleNamespace(
        type=discord.ChannelType.voice,
        status=None,
        edit=fake_edit,
    )

    asyncio.run(voicelink.Player._clear_voice_status_for_channel(SimpleNamespace(), channel))

    assert recorded["status"] is None


def test_teardown_clears_voice_status_before_destroy() -> None:
    order: list[str] = []

    async def fake_clear_voice_status(channel):
        order.append(f"clear:{channel.id}")

    async def fake_destroy():
        order.append("destroy")

    fake_player = SimpleNamespace(
        _cancel_inactive_cleanup_timer=lambda: None,
        _cancel_background_tasks=lambda: order.append("cancel_background"),
        controller=None,
        settings={"played_time": 0, "music_request_channel": {}},
        build_embed=lambda current=None: None,
        joinTime=0,
        _start_background_task=lambda coro, label: order.append(f"bg:{label}"),
        _persist_teardown_state=lambda played_time: None,
        _clear_voice_status_for_channel=fake_clear_voice_status,
        _cleanup_controller_message=lambda controller, **kwargs: None,
        is_ipc_connected=False,
        destroy=fake_destroy,
        channel=SimpleNamespace(id=321),
        _tearing_down=False,
        guild=SimpleNamespace(id=123),
        _logger=logging.getLogger("test"),
    )

    asyncio.run(voicelink.Player.teardown(fake_player))

    assert order[:3] == ["cancel_background", "bg:teardown_persist", "clear:321"]
    assert order[-1] == "destroy"


def test_teardown_suppresses_forbidden_voice_status_warning_noise(monkeypatch) -> None:
    debug_messages: list[str] = []
    warning_messages: list[str] = []
    order: list[str] = []

    class _FakeForbidden(Exception):
        pass

    monkeypatch.setattr("voicelink.player.errors.Forbidden", _FakeForbidden)

    async def fake_clear_voice_status(_channel):
        raise _FakeForbidden()

    async def fake_destroy():
        order.append("destroy")

    logger = SimpleNamespace(
        debug=lambda message, *args, **kwargs: debug_messages.append(message % args if args else message),
        warning=lambda message, *args, **kwargs: warning_messages.append(message % args if args else message),
    )

    fake_player = SimpleNamespace(
        _cancel_inactive_cleanup_timer=lambda: None,
        _cancel_background_tasks=lambda: None,
        controller=None,
        settings={"played_time": 0, "music_request_channel": {}},
        build_embed=lambda current=None: None,
        joinTime=0,
        _start_background_task=lambda coro, label: order.append(f"bg:{label}"),
        _persist_teardown_state=lambda played_time: None,
        _clear_voice_status_for_channel=fake_clear_voice_status,
        _cleanup_controller_message=lambda controller, **kwargs: None,
        is_ipc_connected=False,
        destroy=fake_destroy,
        channel=SimpleNamespace(id=321),
        _tearing_down=False,
        guild=SimpleNamespace(id=123),
        _logger=logger,
    )

    asyncio.run(voicelink.Player.teardown(fake_player))

    assert order == ["bg:teardown_persist", "destroy"]
    assert warning_messages == []
    assert debug_messages == [
        "Skipped clearing voice status during teardown for guild 123 due to missing permissions or disconnect timing."
    ]


def test_update_voice_status_is_skipped_while_tearing_down() -> None:
    recorded = {"called": False}

    async def fake_edit(*, status=None):
        recorded["called"] = True

    fake_player = SimpleNamespace(
        _tearing_down=True,
        settings={},
        channel=SimpleNamespace(type=discord.ChannelType.voice, edit=fake_edit),
        _ph=SimpleNamespace(variables={}),
    )

    asyncio.run(voicelink.Player.update_voice_status(fake_player))

    assert recorded["called"] is False


def test_schedule_post_playback_updates_cancels_pending_voice_status_task() -> None:
    cancelled = {"called": False}
    scheduled = []

    class _PendingTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            cancelled["called"] = True

    fake_player = SimpleNamespace(
        _voice_status_task=_PendingTask(),
        _start_background_task=lambda coro, label: scheduled.append(label) or SimpleNamespace(add_done_callback=lambda _cb: None),
        is_ipc_connected=False,
        update_voice_status=lambda **kwargs: None,
        invoke_controller=lambda: None,
        send_ws=lambda payload: None,
    )

    voicelink.Player._schedule_post_playback_updates(fake_player, SimpleNamespace(track_id="track-1"))

    assert cancelled["called"] is True
    assert scheduled == ["controller_side_effect", "voice_status_side_effect"]


def test_update_voice_status_uses_track_snapshot_when_current_is_already_cleared() -> None:
    recorded = {"status": "unset"}

    async def fake_edit(*, status=None):
        recorded["status"] = status

    class _FakePlaceholder:
        def __init__(self) -> None:
            self.variables = {"track_name": lambda: "None"}

        def replace(self, text: str, variables: dict[str, str]) -> str:
            return variables.get("track_name", "")

    fake_player = SimpleNamespace(
        _tearing_down=False,
        settings={"stage_announce_template": "{{@@track_name@@ != 'None' ?? @@track_name@@}}"},
        channel=SimpleNamespace(type=discord.ChannelType.voice, edit=fake_edit, status=None),
        current=None,
        _ph=_FakePlaceholder(),
        bot=SimpleNamespace(
            user=SimpleNamespace(
                id=1,
                display_name="Vocard",
                display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
            )
        ),
        get_msg=lambda key: "LIVE" if key == "common.status.live" else key,
    )

    snapshot = SimpleNamespace(
        title="Track Snapshot",
        uri="https://example.com/track",
        author="Artist",
        is_stream=False,
        length=1234,
        requester=None,
        source="youtube",
        emoji="🎵",
        thumbnail="https://example.com/thumb.png",
    )

    asyncio.run(voicelink.Player.update_voice_status(fake_player, track_snapshot=snapshot))

    assert recorded["status"] == "Track Snapshot"


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
