from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from cogs.listeners import sanitize_track_exception_message
from voicelink.language import LangHandler
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


def test_default_language_is_vietnamese() -> None:
    LangHandler.init()

    assert LangHandler._default_lang == "VN"
    assert LangHandler._get_lang(None, "player.errors.noTrackFound").startswith("Không tìm thấy")


def test_vietnamese_slash_command_localization_exists() -> None:
    vi_localization = json.loads((ROOT / "local_langs" / "vi.json").read_text(encoding="utf8"))

    assert vi_localization["play"] == "phat"
    assert vi_localization["Loads your input into the queue."] == "Thêm nội dung bạn nhập vào hàng đợi."
    assert vi_localization["settings"] == "cai_dat"
    assert vi_localization["Deezer"] == "Deezer"
    assert vi_localization["Lists all the bot commands."] == "Liệt kê toàn bộ lệnh của bot."
    assert vi_localization["Stage announce template"] == "Mẫu thông báo sân khấu"
    assert vi_localization["Which setting to restore to defaults."] == "Chọn cài đặt cần khôi phục về mặc định."
    reference_localization = json.loads((ROOT / "local_langs" / "es-ES.json").read_text(encoding="utf8"))
    assert set(reference_localization) <= set(vi_localization)


def test_vietnamese_playlist_subcommand_names_are_unique() -> None:
    vi_localization = json.loads((ROOT / "local_langs" / "vi.json").read_text(encoding="utf8"))
    playlist_commands = [
        "play",
        "view",
        "create",
        "delete",
        "share",
        "permission",
        "rename",
        "inbox",
        "add",
        "remove",
        "clear",
        "export",
        "import",
    ]
    translated_names = [vi_localization.get(name, name) for name in playlist_commands]

    assert len(translated_names) == len(set(translated_names))
