from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from voicelink.config import (
    Config,
    LOCALIZED_DEFAULT_VOICE_STATUS_TEMPLATE,
    normalize_controller_settings,
    normalize_voice_status_template,
)
from voicelink.language import LangHandler
from voicelink.placeholders import PlayerPlaceholder
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


def test_default_controller_templates_render_in_vietnamese_for_vn_guilds() -> None:
    LangHandler.init()

    bot_user = SimpleNamespace(
        id=1504518286073659595,
        display_name="CátFanSiTạ",
        display_avatar=SimpleNamespace(url="https://example.com/bot.png"),
        mention="<@1504518286073659595>",
    )
    requester = SimpleNamespace(
        id=621322694138265610,
        name="cá nóc chan",
        display_name="cá nóc chan",
        display_avatar=SimpleNamespace(url="https://example.com/requester.png"),
        mention="<@621322694138265610>",
    )
    track = SimpleNamespace(
        title="Muộn rồi mà sao còn",
        uri="https://www.youtube.com/watch?v=vTjA-C0bwDA",
        author="Sơn Tùng M-TP",
        is_stream=False,
        length=289000,
        requester=requester,
        source="youtube",
        emoji="🎵",
        thumbnail="https://example.com/track.png",
    )
    player = SimpleNamespace(
        current=track,
        channel=SimpleNamespace(name="Phòng biệt giam"),
        settings={},
        volume=100,
        queue=SimpleNamespace(count=24, repeat="Off"),
        dj=SimpleNamespace(mention="<@621322694138265610>"),
        get_msg=lambda key: LangHandler._get_lang("VN", key),
    )
    placeholder = PlayerPlaceholder(SimpleNamespace(user=bot_user), player)

    for settings_name in ("settings.defaults.json", "settings.json"):
        raw_settings = json.loads((ROOT / settings_name).read_text(encoding="utf8"))
        sanitized_settings = dict(raw_settings)
        sanitized_settings["client_id"] = ""
        sanitized_settings["server_id"] = ""
        Config(sanitized_settings)
        controller = normalize_controller_settings(raw_settings["default_controller"], Config().controller)
        active_embed = PlayerPlaceholder.build_embed(controller["embeds"]["active"], placeholder)
        inactive_embed = PlayerPlaceholder.build_embed(controller["embeds"]["inactive"], placeholder)

        assert active_embed.author.name == "Bảng điều khiển nhạc | Phòng biệt giam"
        assert "**Đang phát:" in active_embed.description
        assert "Liên kết: [Mở bài hát]" in active_embed.description
        assert "Người yêu cầu:" in active_embed.description
        assert "DJ:" in active_embed.description
        assert active_embed.footer.text == "Độ dài hàng đợi: 24 | Thời lượng: 04:49 | Âm lượng: 100%"

        assert inactive_embed.title == "Hiện tại không có bài hát nào đang phát"
        assert "[Hỗ trợ](" in inactive_embed.description
        assert "[Mời bot](" in inactive_embed.description
        assert "[Biểu mẫu góp ý](" in inactive_embed.description


def test_legacy_default_controller_is_upgraded_without_overwriting_customizations() -> None:
    settings = json.loads((ROOT / "settings.defaults.json").read_text(encoding="utf8"))

    legacy_controller = {
        "embeds": {
            "active": {
                "description": "**Now Playing: ```[@@track_name@@]```\nLink: [Click Me](@@track_url@@) | Requester: @@track_requester_mention@@ | DJ: @@dj@@**",
                "footer": {
                    "text": "Queue Length: @@queue_length@@ | Duration: @@track_duration@@ | Volume: @@volume@@% {{loop_mode != 'Off' ?? | Repeat: @@loop_mode@@}}"
                },
                "image": "@@track_thumbnail@@",
                "author": {
                    "name": "Music Controller | @@channel_name@@",
                    "icon_url": "@@bot_icon@@",
                },
                "color": "@@track_color@@",
            },
            "inactive": {
                "title": {
                    "name": "There are no songs playing right now",
                },
                "description": "[Support](@@server_invite_link@@) | [Invite](@@invite_link@@) | [Questionnaire](https://forms.gle/Qm8vjBfg2kp13YGD7)",
                "image": "https://i.imgur.com/dIFBwU7.png",
                "color": "@@default_embed_color@@",
            },
        },
        "buttons": [{"tracks": {"label": "@@t_player.dropdown.trackSelect@@", "max_options": 10}}],
    }

    normalized = normalize_controller_settings(legacy_controller, settings["default_controller"])
    custom = normalize_controller_settings(
        {
            "embeds": {
                "active": {
                    "description": "custom controller",
                }
            }
        },
        settings["default_controller"],
    )

    assert normalized["embeds"] == settings["default_controller"]["embeds"]
    assert normalized["buttons"] == legacy_controller["buttons"]
    assert custom["embeds"]["active"]["description"] == "custom controller"


def test_legacy_voice_status_template_is_upgraded_to_localized_default() -> None:
    assert normalize_voice_status_template(
        "{{@@track_name@@ != 'None' ?? @@track_source_emoji@@ Now Playing: @@track_name@@ // Waiting for song requests}}",
        "{{@@track_name@@ != 'None' ?? @@track_source_emoji@@ Now Playing: @@track_name@@ // Waiting for song requests}}",
    ) == LOCALIZED_DEFAULT_VOICE_STATUS_TEMPLATE
