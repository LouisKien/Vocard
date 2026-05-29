# Controller Bump On Queue Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the music controller visible near the latest queue-add activity by re-posting it at the bottom of chat when users add tracks or playlists and the existing controller has drifted away.

**Architecture:** Add a production-safe controller refresh path inside `voicelink.Player` that can either edit the existing controller or intentionally re-post a fresh controller message at the bottom of the target text channel. Wire queue-add commands to call that path after their confirmation messages, while preserving sticky request-channel behavior.

**Tech Stack:** Python 3.14, discord.py hybrid commands, existing `voicelink.Player` controller lifecycle, pytest.

---

### Task 1: Lock the new queue-add controller behavior with tests

**Files:**
- Modify: `tests/test_hot_path_execution.py`
- Test: `tests/test_hot_path_execution.py`

- [ ] Add failing tests that prove queue-add commands call a dedicated controller refresh path after sending confirmation messages.
- [ ] Add a failing test that proves the refresh path re-posts a controller when the existing one is stale and the guild is not using a sticky request channel.
- [ ] Add a failing test that proves sticky request-channel mode keeps editing the pinned controller instead of spawning a new copy.

### Task 2: Add a force-bump controller refresh path in Player

**Files:**
- Modify: `voicelink/player.py`
- Test: `tests/test_hot_path_execution.py`

- [ ] Implement a `refresh_controller_after_queue_update()` helper that routes through `invoke_controller()` with an explicit `prefer_new_message` flag.
- [ ] Extend `invoke_controller()` so non-sticky controllers can intentionally delete-and-repost when forced, while sticky request-channel controllers keep the existing pinned message.
- [ ] Keep teardown, permissions, and best-effort cleanup behavior intact.

### Task 3: Wire queue-add commands to the new refresh path

**Files:**
- Modify: `cogs/basic.py`
- Modify: `cogs/playlist.py`
- Test: `tests/test_hot_path_execution.py`

- [ ] Call the controller refresh helper after successful queue-add confirmation in the user-facing add flows: `play`, context-menu `play`, `search` selection, `playtop`, `forceplay`, queue import, and playlist play.
- [ ] Avoid calling it on pure playback-control commands like pause/skip/leave.
- [ ] Preserve current behavior when controller feature is disabled or no target text channel is available.

### Task 4: Verify production safety

**Files:**
- Modify: `tests/test_hot_path_execution.py`

- [ ] Run focused controller tests to prove the new behavior and stale/sticky branches.
- [ ] Run the full pytest suite in the repo runtime container.
- [ ] Run `python3 -m compileall function.py main.py cogs voicelink tests` and `git diff --check`.
