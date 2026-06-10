from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lavalink_service_persists_plugins_to_named_volume() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "- lavalink_plugins:/opt/Lavalink/plugins" in compose_text


def test_lavalink_service_does_not_run_as_host_uid_gid_override() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'user: "${UID:-1000}:${GID:-1000}"' not in compose_text


def test_lavalink_service_bootstraps_plugin_directory_before_dropping_privileges() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "setpriv --reuid=lavalink --regid=lavalink --init-groups" in compose_text
