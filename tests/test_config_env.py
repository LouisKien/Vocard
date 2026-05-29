from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
BASE_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYENV_ROOT",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)


def base_env(**overrides: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    env.update({
        "PYENV_VERSION": "3.14.3",
        "VOCARD_SKIP_DOTENV": "true",
        "VOCARD_IGNORE_SETTINGS_JSON": "true",
    })
    env.update(overrides)
    return env


def run_repo_python(code: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=ROOT,
        env=env or base_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def test_function_module_imports_without_settings_json() -> None:
    result = run_repo_python(
        "import function; print('ok')",
        env=base_env(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_settings_json_can_be_ignored_for_isolated_test_runs() -> None:
    result = run_repo_python(
        """
from function import settings_override_exists
print(settings_override_exists())
""",
        env=base_env(VOCARD_IGNORE_SETTINGS_JSON="true"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_load_settings_uses_defaults_and_env_overrides() -> None:
    env = base_env(
        DISCORD_TOKEN="discord-token",
        SERVER_ID="123456789012345678",
        MONGO_INITDB_ROOT_USERNAME="mongo",
        MONGO_INITDB_ROOT_PASSWORD="secret",
        MONGODB_URL="mongodb://mongo:secret@mongo:27017",
        MONGODB_NAME="vocard",
        LAVALINK_HOST="lavalink",
        LAVALINK_PORT="2333",
        LAVALINK_PASSWORD="youshallnotpass",
        LAVASRC_SPOTIFY_CLIENT_ID="spotify-client",
        LAVASRC_SPOTIFY_CLIENT_SECRET="spotify-secret",
        BOT_PREFIX="!",
        BOT_ACTIVITY_JSON=json.dumps(
            [{"type": "listening", "name": "/music", "status": "idle"}]
        ),
        DEFAULT_LANGUAGE="VN",
        BOT_ACCESS_USER_IDS="11,22,33",
        DEFAULT_MAX_QUEUE="42",
        LOG_FILE_ENABLE="false",
        CHECK_UPSTREAM_UPDATES="false",
        INACTIVE_PLAYER_CLEANUP_SECONDS="321",
        CACHE_CLEANUP_SECONDS="654",
        DEFAULT_PLAYLIST_NAME="Pinned",
    )
    result = run_repo_python(
        """
import json
from function import load_settings
print(json.dumps(load_settings(), sort_keys=True))
""",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)

    assert settings["token"] == "discord-token"
    assert settings["server_id"] == 123456789012345678
    assert settings["prefix"] == "!"
    assert settings["default_max_queue"] == 42
    assert settings["bot_access_user"] == [11, 22, 33]
    assert settings["activity"] == [{"type": "listening", "name": "/music", "status": "idle"}]
    assert settings["default_language"] == "VN"
    assert settings["logging"]["file"]["enable"] is False
    assert settings["playlist_settings"]["default_playlist_name"] == "Pinned"
    assert settings["timer_settings"]["inactive_player_cleanup"] == 321
    assert settings["timer_settings"]["cache_cleanup"] == 654
    assert settings["check_upstream_updates"] is False
    assert settings["nodes"]["DEFAULT"]["host"] == "lavalink"
    assert settings["nodes"]["DEFAULT"]["port"] == 2333
    assert settings["nodes"]["DEFAULT"]["password"] == "youshallnotpass"


def test_config_accepts_missing_client_id_and_parses_required_env() -> None:
    env = base_env(
        DISCORD_TOKEN="discord-token",
        SERVER_ID="987654321098765432",
        MONGODB_URL="mongodb://mongo:secret@mongo:27017",
        MONGODB_NAME="vocard",
    )
    result = run_repo_python(
        """
import json
from voicelink.config import Config
config = Config({
    "token": None,
    "client_id": 0,
    "mongodb_url": None,
    "mongodb_name": None,
    "nodes": {},
})
print(json.dumps({
    "token": config.token,
    "client_id": config.client_id,
    "server_id": config.server_id,
    "mongodb_url": config.mongodb_url,
    "mongodb_name": config.mongodb_name,
}))
""",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["token"] == "discord-token"
    assert payload["client_id"] == 0
    assert payload["server_id"] == 987654321098765432
    assert payload["mongodb_url"] == "mongodb://mongo:secret@mongo:27017"
    assert payload["mongodb_name"] == "vocard"


def test_load_settings_accepts_legacy_env_aliases() -> None:
    env = base_env(
        BOT_TOKEN="legacy-discord-token",
        DISCORD_GUILD_ID="123456789012345678",
        BOT_NAME="CatFanSiTa",
        MONGODB_URL="mongodb://mongodb:27017",
        MONGODB_NAME="vocard",
    )
    result = run_repo_python(
        """
import json
from function import load_settings
print(json.dumps(load_settings(), sort_keys=True))
""",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)

    assert settings["token"] == "legacy-discord-token"
    assert settings["server_id"] == 123456789012345678
    assert settings["bot_name"] == "CatFanSiTa"


def test_config_accepts_legacy_env_aliases() -> None:
    env = base_env(
        BOT_TOKEN="legacy-discord-token",
        DISCORD_GUILD_ID="123456789012345678",
    )
    result = run_repo_python(
        """
import json
from voicelink.config import Config
config = Config({"token": "", "server_id": 0})
print(json.dumps({
    "token": config.token,
    "server_id": config.server_id,
    "bot_name": config.bot_name,
}))
""",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["token"] == "legacy-discord-token"
    assert payload["server_id"] == 123456789012345678
    assert payload["bot_name"] == "Vocard"


def test_lavalink_config_accepts_legacy_spotify_aliases() -> None:
    application_yml = (ROOT / "lavalink" / "application.yml").read_text(encoding="utf8")

    assert "spotify: ${LAVASRC_SPOTIFY_ENABLED:${SPOTIFY_ENABLED:false}}" in application_yml
    assert "clientId: ${LAVASRC_SPOTIFY_CLIENT_ID:${SPOTIFY_CLIENT_ID:}}" in application_yml
    assert "clientSecret: ${LAVASRC_SPOTIFY_CLIENT_SECRET:${SPOTIFY_CLIENT_SECRET:}}" in application_yml
    assert "spDc: ${LAVASRC_SPOTIFY_SP_DC:${SPOTIFY_SP_DC:}}" in application_yml
    assert "countryCode: ${LAVASRC_SPOTIFY_COUNTRY_CODE:${SPOTIFY_COUNTRY_CODE:VN}}" in application_yml
    assert "preferPartnerApi: ${LAVASRC_SPOTIFY_PREFER_PARTNER_API:${SPOTIFY_PREFER_PARTNER_API:true}}" in application_yml
    assert "preferV1SearchApi: ${LAVASRC_SPOTIFY_PREFER_V1_SEARCH_API:${SPOTIFY_PREFER_V1_SEARCH_API:true}}" in application_yml
    assert "customTokenEndpoint: ${LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT:${SPOTIFY_CUSTOM_TOKEN_ENDPOINT:}}" in application_yml


def test_compose_manages_spotify_tokener_service() -> None:
    compose_yml = (ROOT / "docker-compose.yml").read_text(encoding="utf8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf8")

    assert "path: ${VOCARD_ENV_FILE:-.env}" in compose_yml
    assert "required: false" in compose_yml
    assert "LAVALINK_PASSWORD: ${LAVALINK_PASSWORD:-change-me}" in compose_yml
    assert "  spotify-tokener:" in compose_yml
    assert "image: ${SPOTIFY_TOKENER_IMAGE:-ghcr.io/topi314/spotify-tokener:master@" in compose_yml
    assert "SPOTIFY_TOKENER_ADDR=0.0.0.0:8080" in compose_yml
    assert "spotify-tokener:" in compose_yml
    assert "condition: service_healthy" in compose_yml
    assert "LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT=http://spotify-tokener:8080/api/token" in env_example


def test_lavalink_audio_quality_profile_is_high() -> None:
    application_yml = (ROOT / "lavalink" / "application.yml").read_text(encoding="utf8")

    assert "opusEncodingQuality: 10" in application_yml
    assert "resamplingQuality: HIGH" in application_yml
    assert "frameBufferDurationMs: 10000" in application_yml


def test_youtube_source_has_current_playback_fallback_client() -> None:
    application_yml = (ROOT / "lavalink" / "application.yml").read_text(encoding="utf8")

    assert "\n    clients:\n" in application_yml
    assert "- TVHTML5_SIMPLY" in application_yml
    assert "TVHTML5EMBEDDED" not in application_yml


def test_mongo_image_supports_non_avx_homelab_cpu() -> None:
    compose_yml = (ROOT / "docker-compose.yml").read_text(encoding="utf8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf8")

    assert "image: ${MONGO_IMAGE:-mongo:4.4.29-focal}" in compose_yml
    assert "MONGO_IMAGE=mongo:4.4.29-focal" in env_example
    assert "mongo admin" in compose_yml
    assert "mongosh" not in compose_yml


def test_main_uses_path_safe_cog_loading() -> None:
    main_py = (ROOT / "main.py").read_text(encoding="utf8")

    assert "func.ROOT_DIR + '/cogs'" not in main_py
    assert "func.ROOT_DIR / \"cogs\"" in main_py


def test_env_example_contains_homelab_contract() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf8")
    keys = {
        line.split("=", 1)[0].strip()
        for line in env_example.splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
    }
    required = {
        "VOCARD_ENV_FILE",
        "COMPOSE_PROJECT_NAME",
        "DISCORD_TOKEN",
        "SERVER_ID",
        "MONGO_IMAGE",
        "MONGO_INITDB_ROOT_USERNAME",
        "MONGO_INITDB_ROOT_PASSWORD",
        "MONGODB_MAX_POOL_SIZE",
        "MONGODB_MIN_POOL_SIZE",
        "MONGODB_URL",
        "MONGODB_NAME",
        "LAVALINK_HOST",
        "LAVALINK_PORT",
        "LAVALINK_PASSWORD",
        "LAVASRC_SPOTIFY_CLIENT_ID",
        "LAVASRC_SPOTIFY_CLIENT_SECRET",
        "LAVASRC_SPOTIFY_COUNTRY_CODE",
        "LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT",
        "SPOTIFY_TOKENER_IMAGE",
    }

    assert required <= keys


def test_env_example_covers_compose_and_lavalink_canonical_placeholders() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf8")
    keys = {
        line.split("=", 1)[0].strip()
        for line in env_example.splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
    }
    placeholders = set()
    for relative_path in ("docker-compose.yml", "lavalink/application.yml"):
        text = (ROOT / relative_path).read_text(encoding="utf8")
        placeholders.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text))

    legacy_fallbacks = {
        "SPOTIFY_ENABLED",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_COUNTRY_CODE",
        "SPOTIFY_SP_DC",
        "SPOTIFY_PREFER_PARTNER_API",
        "SPOTIFY_PREFER_V1_SEARCH_API",
        "SPOTIFY_CUSTOM_TOKEN_ENDPOINT",
    }

    assert placeholders - legacy_fallbacks <= keys


def test_runtime_config_validation_reports_actionable_missing_env() -> None:
    result = run_repo_python(
        """
from main import bot_config, validate_runtime_config

try:
    validate_runtime_config(bot_config)
except RuntimeError as exc:
    print(str(exc))
else:
    raise AssertionError("validate_runtime_config should fail without required env")
""",
        env=base_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "DISCORD_TOKEN" in result.stdout
    assert "SERVER_ID" in result.stdout
    assert "MONGODB_URL" in result.stdout
    assert ".env.example" in result.stdout
