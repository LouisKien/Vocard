"""MIT License

Copyright (c) 2023 - present Vocard Development

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import copy
import json
import os
import logging
import voicelink
import tempfile
import discord

from pathlib import Path
from discord.ext import commands
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT_DIR / "settings.json"
DEFAULT_SETTINGS_FILE = ROOT_DIR / "settings.defaults.json"

logger: logging.Logger = logging.getLogger("vocard")

def open_json(path: str) -> dict:
    try:
        target = Path(path)
        if not target.is_absolute():
            target = ROOT_DIR / target

        with open(target, encoding="utf8") as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

def update_json(path: str, new_data: dict) -> None:
    target = Path(path)
    if not target.is_absolute():
        target = ROOT_DIR / target

    if not target.exists():
        return

    data = open_json(path)
    if not data:
        data = new_data
    else:
        data.update(new_data)

    with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=target.parent, delete=False) as temp_file:
        json.dump(data, temp_file, indent=4)
        temp_path = Path(temp_file.name)

    temp_path.replace(target)

def settings_override_exists() -> bool:
    return SETTINGS_FILE.exists() and _get_env("VOCARD_IGNORE_SETTINGS_JSON") not in {"1", "true", "yes", "on"}

def _get_env(name: str) -> Optional[str]:
    if name not in os.environ:
        return None
    return os.environ[name]

def _get_first_env(*names: str) -> Optional[str]:
    for name in names:
        value = _get_env(name)
        if value is not None and value != "":
            return value
    return None

def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")

def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)

def _parse_json(value: Optional[str]) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)

def _parse_int_list(value: Optional[str]) -> Optional[list[int]]:
    if value is None:
        return None
    if value.strip() == "":
        return []
    return [int(item.strip()) for item in value.split(",") if item.strip()]

def _set_nested(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = data
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value

def _apply_env_override(
    settings: dict[str, Any],
    env_name: str,
    path: tuple[str, ...],
    parser,
) -> None:
    raw_value = _get_env(env_name)
    value = parser(raw_value)
    if value is not None:
        _set_nested(settings, path, value)

def load_settings() -> dict[str, Any]:
    source = SETTINGS_FILE if settings_override_exists() else DEFAULT_SETTINGS_FILE
    settings = copy.deepcopy(open_json(str(source)))

    token = _get_first_env("DISCORD_TOKEN", "BOT_TOKEN", "TOKEN")
    if token:
        settings["token"] = token

    client_id = _parse_int(_get_env("CLIENT_ID"))
    if client_id is not None:
        settings["client_id"] = client_id

    genius_token = _get_env("GENIUS_TOKEN")
    if genius_token is not None:
        settings["genius_token"] = genius_token

    bot_name = _get_env("BOT_NAME")
    if bot_name not in {None, ""}:
        settings["bot_name"] = bot_name

    default_language = _get_env("DEFAULT_LANGUAGE")
    if default_language not in {None, ""}:
        settings["default_language"] = default_language.upper()

    server_id = _parse_int(_get_first_env("SERVER_ID", "DISCORD_GUILD_ID"))
    if server_id is not None:
        settings["server_id"] = server_id

    _apply_env_override(settings, "MONGODB_URL", ("mongodb_url",), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "MONGODB_NAME", ("mongodb_name",), lambda value: value if value not in {None, ""} else None)

    if "BOT_PREFIX" in os.environ:
        settings["prefix"] = os.environ["BOT_PREFIX"] or None

    _apply_env_override(settings, "BOT_ACTIVITY_JSON", ("activity",), _parse_json)
    _apply_env_override(settings, "BOT_ACCESS_USER_IDS", ("bot_access_user",), _parse_int_list)
    _apply_env_override(settings, "EMBED_COLOR", ("embed_color",), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "DEFAULT_MAX_QUEUE", ("default_max_queue",), _parse_int)
    _apply_env_override(settings, "DEFAULT_SEARCH_PLATFORM", ("default_search_platform",), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "LYRICS_PLATFORM", ("lyrics_platform",), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "CHECK_UPSTREAM_UPDATES", ("check_upstream_updates",), _parse_bool)

    _apply_env_override(settings, "LOG_FILE_ENABLE", ("logging", "file", "enable"), _parse_bool)
    _apply_env_override(settings, "LOG_FILE_PATH", ("logging", "file", "path"), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "LOG_MAX_HISTORY", ("logging", "max_history"), _parse_int)
    _apply_env_override(settings, "LOG_LEVEL_DISCORD", ("logging", "level", "discord"), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "LOG_LEVEL_VOCARD", ("logging", "level", "vocard"), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "LOG_LEVEL_IPC_CLIENT", ("logging", "level", "ipc_client"), lambda value: value if value not in {None, ""} else None)

    _apply_env_override(settings, "IPC_ENABLE", ("ipc_client", "enable"), _parse_bool)
    _apply_env_override(settings, "IPC_HOST", ("ipc_client", "host"), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "IPC_PORT", ("ipc_client", "port"), _parse_int)
    _apply_env_override(settings, "IPC_PASSWORD", ("ipc_client", "password"), lambda value: value if value not in {None, ""} else None)
    _apply_env_override(settings, "IPC_SECURE", ("ipc_client", "secure"), _parse_bool)

    _apply_env_override(settings, "BOT_ACTIVITY_UPDATE_SECONDS", ("timer_settings", "bot_activity_update"), _parse_int)
    _apply_env_override(settings, "INACTIVE_PLAYER_CLEANUP_SECONDS", ("timer_settings", "inactive_player_cleanup"), _parse_int)
    _apply_env_override(settings, "CACHE_CLEANUP_SECONDS", ("timer_settings", "cache_cleanup"), _parse_int)

    _apply_env_override(settings, "PLAYLIST_MAX_PLAYLISTS", ("playlist_settings", "max_playlists"), _parse_int)
    _apply_env_override(settings, "PLAYLIST_MAX_TRACKS", ("playlist_settings", "max_tracks_per_playlist"), _parse_int)
    _apply_env_override(settings, "DEFAULT_PLAYLIST_NAME", ("playlist_settings", "default_playlist_name"), lambda value: value if value not in {None, ""} else None)

    lavalink_host = _get_env("LAVALINK_HOST")
    if lavalink_host not in {None, ""}:
        _set_nested(settings, ("nodes", "DEFAULT", "host"), lavalink_host)

    lavalink_port = _parse_int(_get_env("LAVALINK_PORT"))
    if lavalink_port is not None:
        _set_nested(settings, ("nodes", "DEFAULT", "port"), lavalink_port)

    lavalink_password = _get_env("LAVALINK_PASSWORD")
    if lavalink_password not in {None, ""}:
        _set_nested(settings, ("nodes", "DEFAULT", "password"), lavalink_password)

    lavalink_secure = _parse_bool(_get_env("LAVALINK_SECURE"))
    if lavalink_secure is not None:
        _set_nested(settings, ("nodes", "DEFAULT", "secure"), lavalink_secure)

    lavalink_identifier = _get_env("LAVALINK_NODE_IDENTIFIER")
    if lavalink_identifier not in {None, ""}:
        _set_nested(settings, ("nodes", "DEFAULT", "identifier"), lavalink_identifier)

    return settings

def cooldown_check(ctx: commands.Context) -> Optional[commands.Cooldown]:
    if ctx.author.id in voicelink.Config().bot_access_user:
        return None
    cooldown = voicelink.Config().cooldowns_settings.get(f"{ctx.command.parent.qualified_name} {ctx.command.name}" if ctx.command.parent else ctx.command.name)
    if not cooldown:
        return None
    return commands.Cooldown(cooldown[0], cooldown[1])

def get_aliases(name: str) -> list:
    return voicelink.Config().aliases_settings.get(name, [])


def should_translate_app_command_context(location: discord.app_commands.TranslationContextLocation) -> bool:
    return location in {
        discord.app_commands.TranslationContextLocation.command_description,
        discord.app_commands.TranslationContextLocation.group_description,
        discord.app_commands.TranslationContextLocation.parameter_description,
    }


async def sync_single_guild_app_commands(
    tree: discord.app_commands.CommandTree,
    guild_id: int,
    logger: logging.Logger,
) -> None:
    guild = discord.Object(id=guild_id)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)

    try:
        legacy_global_commands = await tree.fetch_commands()
    except Exception as exc:
        logger.warning("Failed to inspect legacy global slash commands for cleanup.", exc_info=exc)
        return

    if not legacy_global_commands:
        return

    tree.clear_commands(guild=None)
    try:
        await tree.sync()
    except Exception as exc:
        logger.warning("Failed to clear legacy global slash commands.", exc_info=exc)
        return

    logger.info(
        "Cleared %s legacy global slash command(s); single-guild mode now uses guild-scoped commands only.",
        len(legacy_global_commands),
    )
