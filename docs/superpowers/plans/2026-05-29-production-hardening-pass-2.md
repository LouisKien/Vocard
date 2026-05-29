# Production Hardening Pass 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the current homelab fork for production by improving runtime reliability, cache efficiency, and resource discipline without lowering audio quality.

**Architecture:** This pass keeps the existing quality-first playback design and single-guild deployment model. It improves the code around that path: network session management, Mongo cache access, queue/runtime correctness, and container defaults.

**Tech Stack:** Python 3.14, discord.py, aiohttp, Motor/MongoDB, Lavalink 4.2.2, Docker Compose

---

### Task 1: Lock Down the Runtime Contract

**Files:**
- Create: `tests/test_hardening_runtime.py`
- Modify: `voicelink/pool.py`
- Modify: `voicelink/utils.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the focused tests and verify they fail for the expected reasons**
- [ ] **Step 3: Add node session ownership, request timeout defaults, and the utility timer fix**
- [ ] **Step 4: Re-run the focused tests and verify they pass**

### Task 2: Reduce Hot-Path Database Cost

**Files:**
- Modify: `tests/test_mongodb_cache.py`
- Modify: `main.py`
- Modify: `voicelink/mongodb.py`
- Modify: `cogs/basic.py` if a hot-path user lookup benefits from the cached user helper

- [ ] **Step 1: Write failing cache fast-path tests**
- [ ] **Step 2: Run the focused tests and verify they fail**
- [ ] **Step 3: Implement cached user access and apply cache-first lookups in hot call sites**
- [ ] **Step 4: Re-run the focused tests and verify they pass**

### Task 3: Clean Critical Runtime Footguns

**Files:**
- Create: `tests/test_queue_runtime_hardening.py`
- Modify: `voicelink/queue.py`
- Modify: `function.py`
- Modify: `main.py`
- Modify: `voicelink/player.py`
- Modify: `voicelink/ipc/client.py`
- Modify: `voicelink/__init__.py`
- Modify: `voicelink/views/__init__.py`

- [ ] **Step 1: Write failing tests for queue/runtime edge cases that should raise explicit domain errors**
- [ ] **Step 2: Run the focused tests and verify they fail**
- [ ] **Step 3: Replace broad exception handling in the selected critical modules with explicit handling**
- [ ] **Step 4: Re-run the focused tests and verify they pass**

### Task 4: Tune Containers for Homelab Stability

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `README.md`

- [ ] **Step 1: Add conservative runtime defaults for Lavalink JVM heap and Mongo WiredTiger cache**
- [ ] **Step 2: Keep bot defaults aligned with stdout logging and production-safe Python runtime behavior**
- [ ] **Step 3: Document the new operational knobs in the README and `.env.example`**

### Task 5: Full Verification and Commit

**Files:**
- Modify: `tests/test_production_cleanup.py` only if additional cleanup assertions are needed

- [ ] **Step 1: Run focused regression tests for the new hardening work**
- [ ] **Step 2: Run the full test suite**
- [ ] **Step 3: Run compile verification**
- [ ] **Step 4: Run lint verification with `ruff`**
- [ ] **Step 5: Stage and commit the production hardening pass**
