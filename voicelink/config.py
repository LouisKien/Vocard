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
import os

from pathlib import Path
from dotenv import load_dotenv
from typing import (
    Dict,
    List,
    Any,
    Union,
    Optional
)

from .enums import SearchType

LEGACY_DEFAULT_CONTROLLER_EMBEDS: Dict[str, Dict[str, Any]] = {
    "active": {
        "description": "**Now Playing: ```[@@track_name@@]```\nLink: [Click Me](@@track_url@@) | Requester: @@track_requester_mention@@ | DJ: @@dj@@**",
        "footer": {
            "text": "Queue Length: @@queue_length@@ | Duration: @@track_duration@@ | Volume: @@volume@@% {{loop_mode != 'Off' ?? | Repeat: @@loop_mode@@}}"
        },
        "image": "@@track_thumbnail@@",
        "author": {
            "name": "Music Controller | @@channel_name@@",
            "icon_url": "@@bot_icon@@"
        },
        "color": "@@track_color@@"
    },
    "inactive": {
        "title": {
            "name": "There are no songs playing right now"
        },
        "description": "[Support](@@server_invite_link@@) | [Invite](@@invite_link@@) | [Questionnaire](https://forms.gle/Qm8vjBfg2kp13YGD7)",
        "image": "https://i.imgur.com/dIFBwU7.png",
        "color": "@@default_embed_color@@"
    }
}

LOCALIZED_DEFAULT_CONTROLLER_EMBEDS: Dict[str, Dict[str, Any]] = {
    "active": {
        "description": "**@@t_player.controller.nowPlaying@@: ```[@@track_name@@]```\n@@t_player.controller.link@@: [@@t_player.controller.clickMe@@](@@track_url@@) | @@t_player.controller.requester@@: @@track_requester_mention@@ | @@t_player.controller.dj@@: @@dj@@**",
        "footer": {
            "text": "@@t_player.controller.queueLength@@: @@queue_length@@ | @@t_player.controller.duration@@: @@track_duration@@ | @@t_player.controller.volume@@: @@volume@@%{{loop_mode != 'Off' ?? | @@t_player.controller.repeat@@: @@loop_mode@@}}"
        },
        "image": "@@track_thumbnail@@",
        "author": {
            "name": "@@t_player.controller.title@@ | @@channel_name@@",
            "icon_url": "@@bot_icon@@"
        },
        "color": "@@track_color@@"
    },
    "inactive": {
        "title": {
            "name": "@@t_player.errors.noTrackPlaying@@"
        },
        "description": "[@@t_player.controller.support@@](@@server_invite_link@@) | [@@t_player.controller.invite@@](@@invite_link@@) | [@@t_player.controller.questionnaire@@](https://forms.gle/Qm8vjBfg2kp13YGD7)",
        "image": "https://i.imgur.com/dIFBwU7.png",
        "color": "@@default_embed_color@@"
    }
}

LEGACY_DEFAULT_VOICE_STATUS_TEMPLATE = "{{@@track_name@@ != 'None' ?? @@track_source_emoji@@ Now Playing: @@track_name@@ // Waiting for song requests}}"
LOCALIZED_DEFAULT_VOICE_STATUS_TEMPLATE = "{{@@track_name@@ != 'None' ?? @@track_source_emoji@@ @@t_player.controller.nowPlaying@@: @@track_name@@ // @@t_player.controller.waitingForRequests@@}}"

if os.getenv("VOCARD_SKIP_DOTENV", "").lower() not in {"1", "true", "yes", "on"}:
    load_dotenv()


def normalize_controller_settings(
    controller: Optional[Dict[str, Any]],
    default_controller: Dict[str, Any],
) -> Dict[str, Any]:
    if not controller:
        return copy.deepcopy(default_controller or {})

    normalized = copy.deepcopy(controller)
    if normalized.get("embeds") == LEGACY_DEFAULT_CONTROLLER_EMBEDS:
        replacement_embeds = default_controller.get("embeds", {})
        if not replacement_embeds or replacement_embeds == LEGACY_DEFAULT_CONTROLLER_EMBEDS:
            replacement_embeds = LOCALIZED_DEFAULT_CONTROLLER_EMBEDS
        normalized["embeds"] = copy.deepcopy(replacement_embeds)

    return normalized


def normalize_voice_status_template(template: Optional[str], default_template: str) -> str:
    if template != LEGACY_DEFAULT_VOICE_STATUS_TEMPLATE:
        return template

    if default_template and default_template != LEGACY_DEFAULT_VOICE_STATUS_TEMPLATE:
        return default_template

    return LOCALIZED_DEFAULT_VOICE_STATUS_TEMPLATE

class Config:
    _instance: Optional['Config'] = None
    WORKING_DIR: Path = Path(__file__).resolve().parent.parent
    LAST_SESSION_FILE_DIR: str = WORKING_DIR / "last-session.json"

    def __new__(cls, settings: Dict[str, Any] = None) -> 'Config':
        """
        Singleton pattern to ensure only one instance of Config exists.
        If settings are provided, creates a new instance that replaces the old one.
        
        Args:
            settings (Dict[str, Any], optional): A dictionary containing configuration settings. Defaults to None.
                                               If provided, creates a new instance that replaces the old one.
        """
        if settings is not None:
            instance = super(Config, cls).__new__(cls)
            instance.__init__(settings)
            cls._instance = instance
            return instance
            
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            
        return cls._instance

    def __init__(self, settings: Dict[str, Any] = None) -> None:
        """
        Initialize configuration settings. 
        
        Args:
            settings (Dict[str, Any], optional): A dictionary containing configuration settings.
                                               If None, uses empty dict with default values.
        """
        if hasattr(self, 'initialized'):
            return
            
        settings = settings or {}

        self.token: str = settings.get("token") or os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
        self.bot_name: str = settings.get("bot_name") or os.getenv("BOT_NAME") or "Vocard"
        self.default_language: str = (settings.get("default_language") or os.getenv("DEFAULT_LANGUAGE") or "VN").upper()

        client_id = settings.get("client_id")
        env_client_id = os.getenv("CLIENT_ID")
        self.client_id: int = int(client_id) if client_id not in (None, "", 0, "0") else int(env_client_id) if env_client_id else 0

        server_id = settings.get("server_id")
        env_server_id = os.getenv("SERVER_ID") or os.getenv("DISCORD_GUILD_ID")
        self.server_id: int = int(server_id) if server_id not in (None, "", 0, "0") else int(env_server_id) if env_server_id else 0

        self.genius_token: str = settings.get("genius_token") or os.getenv("GENIUS_TOKEN")
        self.mongodb_url: str = settings.get("mongodb_url") or os.getenv("MONGODB_URL")
        self.mongodb_name: str = settings.get("mongodb_name") or os.getenv("MONGODB_NAME")
        
        self.invite_link: str = "https://discord.gg/wRCgB7vBQv"
        self.nodes: Dict[str, Dict[str, Union[str, int, bool]]] = settings.get("nodes", {})
        self.max_queue: int = settings.get("default_max_queue", 1000)
        self.search_platform: SearchType = SearchType.from_platform(settings.get("default_search_platform", "youtube")) or SearchType.YOUTUBE
        self.bot_prefix: str = settings.get("prefix", "")
        self.activity: List[Dict[str, str]] = settings.get("activity", [{"listen": "/help"}])
        self.logging: Dict[Union[str, Dict[str, Union[str, bool]]]] = settings.get("logging", {})
        self.embed_color: str = int(settings.get("embed_color", "0xb3b3b3"), 16)
        self.bot_access_user: List[int] = settings.get("bot_access_user", [])
        self.sources_settings: Dict[Dict[str, str]] = settings.get("sources_settings", {})
        self.cooldowns_settings: Dict[str, List[int]] = settings.get("cooldowns", {})
        self.aliases_settings: Dict[str, List[str]] = settings.get("aliases", {})
        self.controller: Dict[str, Dict[str, Any]] = normalize_controller_settings(
            settings.get("default_controller", {}),
            settings.get("default_controller", {}),
        )
        self.voice_status_template: str = normalize_voice_status_template(
            settings.get("default_voice_status_template", ""),
            settings.get("default_voice_status_template", ""),
        )
        self.lyrics_platform: str = settings.get("lyrics_platform", "A_ZLyrics").lower()
        self.ipc_client: Dict[str, Union[str, bool, int]] = settings.get("ipc_client", {})
        self.resolver_http: Dict[str, Union[str, bool, int]] = settings.get("resolver_http", {})
        self.playlist_settings: Dict[str, Union[str, int]] = settings.get("playlist_settings", {})
        self.timer_settings: Dict[str, int] = settings.get("timer_settings", {})
        self.version: str = settings.get("version", "")
        self.check_upstream_updates: bool = bool(settings.get("check_upstream_updates", False))
        
        self.initialized = True

    def is_allowed_guild(self, guild_id: Optional[int]) -> bool:
        if not self.server_id:
            return True
        return guild_id == self.server_id
    
    @classmethod
    def get_source_config(cls, source: str, type: str) -> Union[str, None]:
        """
        Get source configuration for a specific source and type.
        
        Args:
            source (str): The source identifier (e.g., 'youtube', 'spotify').
                            Case-insensitive and spaces are removed.
            type (str): The type of configuration to retrieve (e.g., 'emoji', 'color').
        
        Returns:
            Union[str, None]: The configuration value for the specified source and type.
                            Returns None if either the source or type doesn't exist.
        
        Example:
            >>> Config().get_source("youtube", "emoji")
            "🎵"
        """
        if not isinstance(source, str) or not isinstance(type, str):
            return None
            
        normalized_source: str = source.lower().strip().replace(" ", "")
        source_settings: dict[str, str] = cls._instance.sources_settings.get(
            normalized_source,
            cls._instance.sources_settings.get("others", {})
        )
        
        return source_settings.get(type)
    
    @classmethod
    def get_playlist_config(cls) -> tuple[int, int, str]:
        config = cls._instance.playlist_settings
        return config.get("max_playlists", 5), config.get("max_tracks_per_playlist", 500), config.get("default_playlist_name", "Favourite")
