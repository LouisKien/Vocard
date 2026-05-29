from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from voicelink.language import LangHandler
from voicelink.views.help import HelpView


ROOT = Path(__file__).resolve().parents[1]


def test_language_handler_falls_back_to_english_for_missing_runtime_keys() -> None:
    LangHandler.init()

    assert LangHandler._get_lang("FR", "help.menu.title") == "{0} Help Menu"


def test_help_view_uses_fork_github_link() -> None:
    fake_bot = SimpleNamespace(cogs={})
    fake_author = SimpleNamespace(display_name="Kien")

    view = HelpView(fake_bot, fake_author)
    github_buttons = [child for child in view.children if getattr(child, "url", None) == "https://github.com/LouisKien/Vocard"]

    assert len(github_buttons) == 1
    assert github_buttons[0].url == "https://github.com/LouisKien/Vocard"


def test_vietnamese_runtime_language_pack_includes_new_discord_ui_keys() -> None:
    lang = json.loads((ROOT / "langs" / "VN.json").read_text(encoding="utf8"))

    assert lang["help"]["menu"]["title"] == "Menu trợ giúp của {0}"
    assert lang["help"]["buttons"]["github"] == "GitHub"
    assert lang["debug"]["panel"]["title"] == "📄 Bảng điều khiển debug"
    assert lang["embedBuilder"]["buttons"]["editContent"] == "Sửa nội dung"
    assert lang["inbox"]["buttons"]["accept"] == "Chấp nhận"
    assert lang["playlist"]["permissions"]["granted"].startswith("Đã cấp")
    assert lang["settings"]["actions"]["resetDone"] == "Đã đặt lại `{0}` về mặc định của máy chủ."


def test_vietnamese_local_command_descriptions_stay_translated_without_renaming_commands() -> None:
    vi_localization = json.loads((ROOT / "local_langs" / "vi.json").read_text(encoding="utf8"))

    assert vi_localization["play"] == "phat"
    assert vi_localization["playlist"] == "playlist"
    assert vi_localization["Grant or revoke permissions for a playlist."] == "Cấp hoặc thu hồi quyền cho playlist."
    assert vi_localization["Toggles the music controller."] == "Bật/tắt bảng điều khiển nhạc."


def test_ui_source_files_no_longer_contain_known_english_discord_labels() -> None:
    expectations = {
        "voicelink/views/help.py": [
            "Select Category!",
            "Get Started",
            "View new updates of Vocard.",
            "How to use Vocard.",
            "https://github.com/ChocoMeow/Vocard",
        ],
        "voicelink/views/embed_builder.py": [
            "Edit Content",
            "Edit Author",
            "Edit Image",
            "Edit Footer",
            "Add Field",
            "Remove Field",
            "Apply",
            "Reset",
            "You have already reached the maximum of fields!",
            "There are no fields to remove!",
        ],
        "voicelink/views/inbox.py": [
            "Select a message to view ..",
            "Accept",
            "Dismiss",
            "Click Me To Save The Changes",
            "Message Info:",
        ],
        "voicelink/views/debug.py": [
            "Reload Cogs",
            "Synchronizing all your commands and language settings!",
            "The node could not be found!",
            "Create Node",
            "Please ensure that you have selected a node!",
        ],
        "cogs/settings.py": [
            "You are not able to use this command!",
            "📄 Debug Panel",
        ],
    }

    for relative_path, banned_snippets in expectations.items():
        source = (ROOT / relative_path).read_text(encoding="utf8")
        for snippet in banned_snippets:
            assert snippet not in source, f"{relative_path} still contains {snippet!r}"
