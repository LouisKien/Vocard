# Quality-First Playback Hot Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep current audio-quality tuning while making playback commands respond quickly by separating Lavalink control flow from UI, persistence, and repeated settings access.

**Architecture:** Add lightweight timing instrumentation first, then refactor `Player` and command handlers so playback-changing operations complete before controller/status/history work. Reduce repeated guild-settings reads and avoid blocking cached reads on the same global lock path used for writes.

**Tech Stack:** Python 3.14, discord.py, aiohttp, Motor/MongoDB, Lavalink 4.2.2, LavaSrc 4.8.3, pytest.

---

### Task 1: Add Timing Instrumentation for Hot Paths

**Files:**
- Modify: `voicelink/pool.py`
- Modify: `voicelink/player.py`
- Modify: `voicelink/utils.py`
- Test: `tests/test_track_lookup_logging.py`
- Create: `tests/test_hot_path_logging.py`

- [ ] Add helper logging methods for lookup, play request, controller update, voice status update, settings reads, and teardown timing.
- [ ] Instrument `Node.get_tracks()` to emit `lookup_ms` for success and failure paths.
- [ ] Instrument `Player.play()`, `Player.do_next()`, `Player.invoke_controller()`, `Player.update_voice_status()`, and `dispatch_message()` so logs show which stage is slow.
- [ ] Add tests that assert timing logs exist for lookup and playback transitions.
- [ ] Run targeted tests for the new logging behavior.

### Task 2: Separate Playback Hot Path From UI Side-Effects

**Files:**
- Modify: `voicelink/player.py`
- Test: `tests/test_hot_path_execution.py`

- [ ] Introduce background helper scheduling for controller refresh, voice-status refresh, and history persistence.
- [ ] Refactor `Player.do_next()` so the Lavalink play request completes before controller/status updates are awaited.
- [ ] Keep playback progression correct when side-effects fail; log them without blocking audio.
- [ ] Add tests that verify controller and voice-status helpers are not awaited inline on the hot path.
- [ ] Run focused tests for `Player.do_next()` ordering.

### Task 3: Make Command Handlers Return Faster

**Files:**
- Modify: `cogs/basic.py`
- Modify: `voicelink/player.py`
- Test: `tests/test_command_hot_path.py`

- [ ] Refactor `play`, `playtop`, and `forceplay` so queue mutation and initial playback happen before expensive follow-up UI work.
- [ ] Refactor `pause`, `resume`, `skip`, `back`, and `leave` so Lavalink state changes happen first and non-essential follow-up work happens afterward.
- [ ] Preserve existing user-facing responses and permissions behavior unless hot-path separation requires a harmless timing change.
- [ ] Add tests that assert playback-changing commands call their critical player methods before side-effect helpers.
- [ ] Run targeted command-path tests.

### Task 4: Reduce Settings and Message Path Contention

**Files:**
- Modify: `voicelink/mongodb.py`
- Modify: `voicelink/language.py`
- Modify: `voicelink/utils.py`
- Test: `tests/test_mongodb_cache.py`
- Create: `tests/test_settings_hot_path.py`

- [ ] Add a cheaper cache-hit path for guild settings reads that avoids the same lock/write path where safe.
- [ ] Add optional settings snapshot reuse so `send_localized_message()` and `dispatch_message()` do not trigger repeated settings reads within one command flow.
- [ ] Update language/message helpers to accept a pre-fetched settings snapshot when available.
- [ ] Add tests that verify cached settings reads avoid repeated underlying fetch work and that a single command can reuse one settings snapshot.
- [ ] Run focused settings/cache tests.

### Task 5: Verify End-to-End Behavior and Commit

**Files:**
- Modify: `README.md` if behavior or observability notes need operator guidance.

- [ ] Run the full test suite.
- [ ] Run `python -m compileall` for touched modules.
- [ ] Run `git diff --check`.
- [ ] Review logs/output to confirm instrumentation names are useful for production debugging.
- [ ] Commit the implementation with a playback hot-path message.
