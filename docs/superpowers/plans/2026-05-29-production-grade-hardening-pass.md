# Production Grade Hardening Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the highest-value runtime and security footguns from the current production branch without regressing the single-guild homelab deployment or Spotify playback path.

**Architecture:** Keep the current runtime behavior and audio quality profile intact, but harden helper subsystems around it: placeholder expression parsing, update tooling, IPC resource lifecycle, lyrics I/O, and container runtime defaults. Prefer narrow refactors with direct regression tests over broad rewrites.

**Tech Stack:** Python 3.14, discord.py, aiohttp, Motor, Docker Compose, pytest, Ruff

---

### Task 1: Lock the target hardening surface with failing tests

**Files:**
- Create: `tests/test_production_grade_hardening.py`
- Modify: `docs/superpowers/plans/2026-05-29-production-grade-hardening-pass.md`

- [ ] Add tests for safe placeholder conditional parsing, updater migration hardening, Mongo URI redaction, IPC disconnect cleanup, non-blocking Genius lookup, container non-root execution, and removal of production `assert` guards.
- [ ] Run: `uv run --with pytest --with-requirements requirements.txt python -m pytest -q tests/test_production_grade_hardening.py`
- [ ] Expected: multiple failures that map directly to the targeted hardening work.

### Task 2: Remove dangerous runtime patterns and tighten helper lifecycles

**Files:**
- Modify: `voicelink/placeholders.py`
- Modify: `update.py`
- Modify: `voicelink/mongodb.py`
- Modify: `voicelink/ipc/client.py`
- Modify: `voicelink/lyrics.py`
- Modify: `voicelink/player.py`
- Modify: `voicelink/transformer.py`
- Modify: `Dockerfile`

- [ ] Replace raw `eval` in placeholder conditionals with a small safe evaluator that supports the expressions already used by controller/status templates.
- [ ] Remove remote migration-script execution from `update.py`, add explicit deprecation messaging, and add request timeouts to remaining network calls.
- [ ] Redact credentials in Mongo URI debug logging.
- [ ] Make IPC disconnect idempotent and close websocket/session resources reliably.
- [ ] Offload blocking Genius lookups from the event loop and centralize lyrics HTTP timeout handling.
- [ ] Replace production `assert` guards in runtime code with explicit validation errors.
- [ ] Drop bot container privileges by creating a dedicated runtime user in `Dockerfile`.

### Task 3: Verify end-to-end production safety signals

**Files:**
- Modify: `README.md` if runtime/deployment guidance changes materially
- Modify: `.env.example` only if new env knobs are introduced

- [ ] Run the new targeted hardening tests to green.
- [ ] Run the full suite: `uv run --with pytest --with-requirements requirements.txt python -m pytest -q`
- [ ] Run lint: `uv run --with ruff ruff check .`
- [ ] Run compile verification: `uv run --with-requirements requirements.txt python -m compileall function.py main.py cogs voicelink tests`
- [ ] Run compose render if container files change: `VOCARD_ENV_FILE=.env.example docker compose config --quiet`
- [ ] Run Docker image build if `Dockerfile` changes: `docker buildx build --platform linux/amd64 --load -t vocard-bot:production-grade-hardening-pass .`
