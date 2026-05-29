# Spotify Fast First-Track Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start Spotify playlist playback faster by resolving and playing the first Spotify track immediately, then backfilling the remaining playlist entries in the background without changing non-Spotify sources.

**Architecture:** Add a Spotify-only fast-path that uses Spotify Web API metadata to find the first playable track quickly, keeps the existing LavaSrc playlist lookup as the authoritative backfill path, and falls back to the current full-playlist flow whenever the fast-path is unavailable or fails. Keep command/UI behavior compatible by using the normal immediate track-load response first, then queueing the rest of the playlist asynchronously.

**Tech Stack:** Python 3.14, discord.py, aiohttp, Lavalink 4.2.2, LavaSrc 4.8.3, pytest.

---

### Task 1: Add Spotify Fast-Path Helpers

**Files:**
- Create: `voicelink/spotify_fastpath.py`
- Modify: `voicelink/pool.py`
- Test: `tests/test_spotify_fastpath.py`

- [ ] Parse Spotify playlist URLs and expose a Spotify-only feature flag.
- [ ] Fetch a cached Spotify app token and playlist seed metadata from Spotify Web API using existing env credentials.
- [ ] Return the first playable Spotify track URL plus lightweight playlist metadata.
- [ ] Add tests for URL detection, feature gating, first-track extraction, and fallback-safe behavior.

### Task 2: Add Player-Side Progressive Backfill

**Files:**
- Modify: `voicelink/player.py`
- Modify: `voicelink/queue.py` only if insertion helpers are needed
- Test: `tests/test_spotify_fastpath.py`

- [ ] Add a player helper that starts the first Spotify track immediately when the fast-path is available.
- [ ] Backfill the full playlist through the existing LavaSrc `loadtracks` path in a background task.
- [ ] Remove the duplicated first track from the backfill result and insert the remaining tracks immediately after the seeded track/current track.
- [ ] Add tests that verify ordering, duplicate skipping, and fallback to the existing path on failure.

### Task 3: Wire Spotify-Only Commands and Operator Defaults

**Files:**
- Modify: `cogs/basic.py`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_hot_path_execution.py`

- [ ] Use the Spotify fast-path only for Spotify playlist URLs in playback commands; leave all other sources unchanged.
- [ ] Preserve the hot-path work from the previous refactor so audio still starts before UI side-effects.
- [ ] Document the feature flag and operator expectations for progressive Spotify playlist loading.
- [ ] Run the targeted tests, then the full suite, compile checks, and `git diff --check`.
