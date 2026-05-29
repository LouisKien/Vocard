# Production Hardening Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the single-guild homelab fork safer and leaner for production without broad behavior changes.

**Architecture:** Keep the current Vocard structure and focus on targeted hardening: remove runtime footguns, make config/test behavior deterministic, and verify Docker artifacts without leaving local containers running. Avoid large rewrites of playback, queue, and Lavalink integration.

**Tech Stack:** Python 3.14, discord.py, aiohttp, pymongo, Docker Compose, Lavalink 4.2.2, LavaSrc 4.8.3.

---

### Task 1: Runtime Safety Fixes

**Files:**
- Modify: `voicelink/player.py`
- Modify: `tests/test_runtime_errors.py`

- [ ] Add a regression test that catches `return` inside `finally` in `voicelink/player.py`.
- [ ] Refactor the affected method so exceptions are not swallowed by `finally`.
- [ ] Run `uv run --python 3.14.3 --with-requirements requirements.txt --with pytest pytest tests/test_runtime_errors.py -q`.

### Task 2: Config and Test Determinism

**Files:**
- Modify: `function.py`
- Modify: `tests/test_config_env.py`

- [ ] Verify tests do not depend on a local `.venv` path or local `settings.json`.
- [ ] Add or adjust tests for the config-isolation behavior.
- [ ] Keep production behavior backward compatible unless `VOCARD_IGNORE_SETTINGS_JSON=true` is set.

### Task 3: Hot-Path Cleanup

**Files:**
- Modify only files with clear, low-risk duplication or exception-handling issues discovered during review.

- [ ] Inspect `voicelink/player.py`, `voicelink/pool.py`, `voicelink/mongodb.py`, `cogs/basic.py`, and `cogs/playlist.py`.
- [ ] Apply only behavior-preserving cleanup that reduces exception swallowing, repeated parsing, or noisy logs.
- [ ] Add focused tests where behavior could regress.

### Task 4: Docker and Production Verification

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, or docs only if review finds a concrete issue.

- [ ] Run `docker compose --env-file .env.example config --quiet`.
- [ ] Run a Docker build verification without starting the full stack.
- [ ] If any container is started for validation, stop it before completion.

### Task 5: Final Verification and Commit

- [ ] Run the full pytest suite through `uv run --python 3.14.3 --with-requirements requirements.txt --with pytest pytest -q`.
- [ ] Run `PYENV_VERSION=3.14.3 python3 -m compileall function.py main.py cogs voicelink tests`.
- [ ] Run `git diff --check`.
- [ ] Confirm `docker compose ps` has no local test stack running from this worktree.
- [ ] Commit the changes with a production-hardening message.
