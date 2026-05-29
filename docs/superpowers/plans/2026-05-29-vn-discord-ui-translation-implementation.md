# Vietnamese Discord UI Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Discord-visible UI text consistent in Vietnamese when guild language is `VN`, while preserving existing slash/prefix command names.

**Architecture:** Add per-key language fallback in `LangHandler`, move hardcoded Discord UI strings into runtime language files, and wire translated labels/placeholders through the affected views. Keep other locales safe by falling back to `EN`.

**Tech Stack:** Python 3, discord.py, JSON language packs, pytest

---

### Task 1: Add tests for fallback and UI localization targets

**Files:**
- Create: `tests/test_vietnamese_ui_translation.py`
- Test: `tests/test_vietnamese_ui_translation.py`

- [ ] **Step 1: Write failing tests**

Add tests covering:

- `LangHandler._get_lang("FR", "help.menu.title")` falls back to English instead of `Not found!`
- `HelpView` uses the fork GitHub URL
- VN runtime texts exist for new help/debug/embed-builder/inbox/pagination keys
- `local_langs/vi.json` keeps command keys stable while descriptions are Vietnamese

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_vietnamese_ui_translation.py -q
```

Expected: FAIL because new keys and fallback behavior do not exist yet.

- [ ] **Step 3: Commit after green**

```bash
git add tests/test_vietnamese_ui_translation.py
git commit -m "test: cover vietnamese discord ui localization"
```

### Task 2: Add localization keys and fallback behavior

**Files:**
- Modify: `voicelink/language.py`
- Modify: `langs/EN.json`
- Modify: `langs/VN.json`

- [ ] **Step 1: Implement per-key fallback in `LangHandler`**

Use locale value, then `EN`, then default locale before returning `Not found!`.

- [ ] **Step 2: Add new runtime language keys**

Add help/debug/embed-builder/inbox/pagination/playlist share keys to `EN` and `VN`.

- [ ] **Step 3: Run the targeted tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_vietnamese_ui_translation.py -q
```

Expected: some tests still fail until views consume the new keys.

- [ ] **Step 4: Commit partial localization infrastructure**

```bash
git add voicelink/language.py langs/EN.json langs/VN.json
git commit -m "feat: add localized discord ui runtime strings"
```

### Task 3: Replace hardcoded English Discord UI strings in views

**Files:**
- Modify: `voicelink/views/help.py`
- Modify: `voicelink/views/pagination.py`
- Modify: `voicelink/views/embed_builder.py`
- Modify: `voicelink/views/inbox.py`
- Modify: `voicelink/views/playlist.py`
- Modify: `voicelink/views/debug.py`
- Modify: `cogs/settings.py`

- [ ] **Step 1: Route view labels/placeholders/titles through language keys**

Use guild/user language where the view already has access to guild settings; otherwise use cached guild settings from the author context.

- [ ] **Step 2: Update GitHub button URL**

Point Discord help UI to:

```text
https://github.com/LouisKien/Vocard
```

- [ ] **Step 3: Keep command names unchanged**

Do not modify slash command names or prefix command names during this pass.

- [ ] **Step 4: Run the targeted tests again**

Run:

```bash
.venv/bin/python -m pytest tests/test_vietnamese_ui_translation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit view translation changes**

```bash
git add voicelink/views/help.py voicelink/views/pagination.py voicelink/views/embed_builder.py voicelink/views/inbox.py voicelink/views/playlist.py voicelink/views/debug.py cogs/settings.py
git commit -m "feat: translate discord ui labels for vietnamese"
```

### Task 4: Clean up Vietnamese slash-command descriptions only

**Files:**
- Modify: `local_langs/vi.json`

- [ ] **Step 1: Adjust Vietnamese descriptions and labels**

Keep command identifiers unchanged; only improve displayed Vietnamese descriptions and labels.

- [ ] **Step 2: Run targeted tests and any existing localization tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_vietnamese_ui_translation.py tests/test_runtime_errors.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit slash-command description cleanup**

```bash
git add local_langs/vi.json
git commit -m "chore: polish vietnamese discord command descriptions"
```

### Task 5: Verify end-to-end and scan for remaining mixed English UI

**Files:**
- Modify as needed: `langs/VN.json`, `local_langs/vi.json`, affected view files

- [ ] **Step 1: Run static scans for obvious English UI leftovers**

Run:

```bash
rg -n "Select Category!|Edit Content|Accept|Dismiss|Reload Cogs|Synchronizing all your commands|Github|Document|Get Started|The node could not be found|Click Me To Save The Changes" cogs voicelink langs local_langs
```

Expected: no remaining runtime VN-facing English strings except intentional command names and upstream comments.

- [ ] **Step 2: Run full verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall function.py main.py cogs voicelink tests
```

Expected: PASS.

- [ ] **Step 3: Final commit**

```bash
git add langs/EN.json langs/VN.json local_langs/vi.json voicelink/language.py voicelink/views/help.py voicelink/views/pagination.py voicelink/views/embed_builder.py voicelink/views/inbox.py voicelink/views/playlist.py voicelink/views/debug.py cogs/settings.py tests/test_vietnamese_ui_translation.py docs/superpowers/specs/2026-05-29-vn-discord-ui-translation-design.md docs/superpowers/plans/2026-05-29-vn-discord-ui-translation-implementation.md
git commit -m "feat: complete vietnamese discord ui translation pass"
```
