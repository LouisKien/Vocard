from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_code_no_longer_references_spotify_fastpath() -> None:
    basic_source = (ROOT / "cogs" / "basic.py").read_text(encoding="utf8")
    player_source = (ROOT / "voicelink" / "player.py").read_text(encoding="utf8")
    pool_source = (ROOT / "voicelink" / "pool.py").read_text(encoding="utf8")

    assert "try_start_spotify_playlist_fast" not in basic_source
    assert "spotify_fastpath" not in player_source
    assert "get_spotify_playlist_seed" not in pool_source


def test_runtime_code_no_longer_emits_perf_timing_markers() -> None:
    runtime_files = [
        ROOT / "voicelink" / "player.py",
        ROOT / "voicelink" / "pool.py",
        ROOT / "voicelink" / "utils.py",
        ROOT / "voicelink" / "mongodb.py",
    ]
    forbidden_markers = [
        "_log_stage_timing",
        "lookup_ms=",
        "message_send_ms=",
        "settings_read_ms=",
        "controller_update_ms",
        "voice_status_ms",
        "do_next_ms",
        "play_request_ms",
        "pause_request_ms",
        "stop_request_ms",
        "teardown_ms",
        "side_effect_ms",
    ]

    combined = "\n".join(path.read_text(encoding="utf8") for path in runtime_files)
    for marker in forbidden_markers:
        assert marker not in combined


def test_experimental_spotify_fastpath_files_are_removed() -> None:
    assert not (ROOT / "voicelink" / "spotify_fastpath.py").exists()
    assert not (ROOT / "tests" / "test_spotify_fastpath.py").exists()
    assert not (ROOT / "tests" / "test_first_audio_benchmark.py").exists()
