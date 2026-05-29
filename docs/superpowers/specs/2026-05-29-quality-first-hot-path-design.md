# Quality-First Playback Hot Path Design

**Status:** Proposed

**Goal:** Keep the current high-audio-quality Lavalink configuration, while making playback commands (`play`, `pause`, `resume`, `skip`, `back`, `leave`) feel responsive by removing UI, database, and Discord API work from the audio hot path.

**Non-Goals:**
- Do not lower audio quality settings in `lavalink/application.yml`.
- Do not redesign the bot command surface.
- Do not rewrite playlist, queue, or player architecture wholesale.

## Context

This fork targets a single-guild homelab deployment on Intel N4100-class hardware. The current stack favors playback quality with a large audio buffer, high Opus quality, and high resampling quality. That aligns with the deployment goal, but the current Python bot flow mixes latency-sensitive playback operations with slower side-effects:

- Discord message sends and edits
- voice channel status updates
- controller fetch/edit/delete work
- MongoDB settings and user reads/writes
- Lavalink and LavaSrc lookup work for playlists

Because these side-effects run inline with command handling and `Player.do_next()`, the user experiences visible command lag even when the audio path itself is healthy.

## Problem Statement

There are two classes of delay:

1. **Large delay (`~5s`) around initial playback of some playlist tracks**
This most likely comes from track startup failures that trigger the existing retry path in `voicelink/player.py`, where `do_next()` waits 5 seconds before moving on.

2. **Small but frequent delay (`~0.5-1.5s`) across commands like `pause`, `skip`, `back`, `leave`, and normal `play`**
This likely comes from serial waits on Discord API calls, controller updates, localized message sends, and repeated MongoDB-backed settings reads in the same command flow.

The design must address both classes without sacrificing audio quality.

## Design Principles

1. **Playback first**
Anything required to make Lavalink start, stop, pause, resume, seek, or switch tracks stays on the hot path.

2. **Everything else is best-effort**
Controller refresh, voice status updates, history persistence, and command feedback should not delay core playback state changes.

3. **Quality-first stays intact**
Buffering, resampling, encoding quality, and other audio quality knobs remain unchanged unless measurement later proves they are not involved in command latency.

4. **Measure before tuning**
The first implementation phase should add timing instrumentation around each stage, so later changes are driven by evidence instead of guesswork.

## Architecture

### 1. Split the Player Flow Into Hot Path and Side-Effects

The player logic should be treated as two separate pipelines:

- **Hot path**
  - Lavalink `loadtracks`
  - queue mutation
  - Lavalink player `PATCH`/`DELETE`
  - bot voice state connect/disconnect
  - event-driven track progression

- **Side-effect path**
  - controller message update
  - voice channel status update
  - localized success/error messaging
  - Mongo history persistence
  - queue/session metadata persistence

`Player.do_next()` should be refactored so that once a track has been chosen and the Lavalink play request succeeds, the function returns control as quickly as possible. Side-effects should run in background tasks or deferred helpers that never block playback progression.

### 2. Command Handlers Should Acknowledge Fast

Command handlers in `cogs/basic.py` should avoid serial chains like:

1. lookup
2. queue mutation
3. controller update
4. voice status update
5. localized response
6. start playback

Instead, commands should follow a latency-first structure:

1. validate caller/channel state
2. perform the minimum playback mutation
3. trigger playback state change immediately
4. schedule or defer post-action UI work
5. send user-facing confirmation as cheaply as possible

This keeps the user-facing command responsive even when Discord edits or controller work are slow.

### 3. Treat Controller and Voice Status as Eventually Consistent UI

The controller and voice status should not be considered part of command completion. They should be updated as background UI state.

Expected behavior:

- Playback continues even if controller update fails.
- Playback continues even if voice status update fails or is slow.
- Multiple UI updates should be coalesced where possible.
- Slow or failing UI should degrade the interface, not the audio path.

This is especially important because Discord message edits and channel status edits are network-bound and permission-sensitive.

### 4. Reduce Repeated Settings Reads on the Command Path

Today, localized messages and dispatch helpers read guild settings repeatedly, and settings reads take a shared MongoDB lock even on cache hits. For a small homelab bot, this creates unnecessary contention.

The design direction is:

- fetch guild settings once per command when possible
- reuse the same settings snapshot throughout the command
- make cached settings reads lock-free or much cheaper than writes
- keep writes serialized, but make reads cheap

The bot should behave as if settings are effectively in-memory during a command, with eventual consistency for writes.

### 5. Playlist Lookup Should Optimize Time-to-First-Audio

Spotify playlist lookup is a special case. Even in quality-first mode, the system should optimize for **time to first playable track**, not time to fully resolve the entire playlist before any audio starts.

The desired model is:

- fetch playlist metadata
- resolve enough of the playlist to play the first valid track quickly
- continue resolving or preparing the remaining items without blocking first playback

If the current Lavalink/LavaSrc flow cannot support full progressive resolution directly, the implementation should still measure and isolate lookup stages so we can tell whether the delay is:

- Spotify metadata fetch
- LavaSrc provider resolution
- YouTube source lookup
- first Lavalink play request

## Data Flow

### `play` / `playtop` / `forceplay`

1. Validate voice/channel/guild constraints.
2. Run lookup and capture timing.
3. Mutate queue.
4. If player is idle, issue the Lavalink play request immediately.
5. Schedule controller refresh, voice status refresh, and history persistence outside the hot path.
6. Send command feedback without forcing extra settings reads if possible.

### `pause` / `resume`

1. Validate player and permission state.
2. Send Lavalink pause toggle immediately.
3. Update internal paused state.
4. Schedule UI refresh as a background step.
5. Send response.

### `skip` / `back`

1. Validate player and permission state.
2. Mutate queue/repeat state.
3. Stop current track immediately so Lavalink emits the next event.
4. Return command feedback quickly.
5. Let event-driven progression handle UI refresh.

### `leave`

1. Validate permission state.
2. Acknowledge the command quickly.
3. Disconnect/destroy player.
4. Perform cleanup UI and persistence as best-effort teardown work.

## Error Handling

### Playback Errors

Playback failures remain high priority and must still surface clearly, but recovery behavior should not hide where time is spent.

The implementation should:

- preserve user-friendly messages for track failures
- log stage-specific timing and failure context
- distinguish lookup failures from playback-start failures
- distinguish first-track failure in a playlist from later-track failure

### UI and Persistence Errors

UI and persistence failures should be demoted relative to playback:

- controller update failure: warning or debug depending on severity
- voice status permission failure: warning, not blocking
- history/settings persistence failure: warning unless data integrity is at risk

These failures should never prevent audio progression.

## Observability

The implementation should add structured timing logs for:

- `lookup_ms`
- `queue_mutation_ms`
- `play_request_ms`
- `controller_update_ms`
- `voice_status_ms`
- `settings_read_ms`
- `message_send_ms`
- `teardown_ms`

Each timing record should include at least:

- guild ID
- command/action name
- node identifier
- source type when known
- query or track/playlist identifier when safe to log

The purpose is not heavy telemetry infrastructure. The goal is enough evidence in Docker logs to pinpoint where latency lives on a small homelab deployment.

## Testing Strategy

The implementation should add tests for:

- command hot paths not awaiting controller/status helpers inline
- cached settings reads no longer taking the same slow path as writes
- playback continues when controller update fails
- playback continues when voice status update fails
- timing instrumentation logs lookup and play stages
- playlist startup path preserves current playback behavior while reducing blocking side-effects

Where runtime timing is hard to assert directly, tests should focus on call ordering and whether side-effects are awaited inline versus scheduled separately.

## Rollout Plan

1. Add instrumentation only.
2. Measure real-world timings on production-like workloads.
3. Refactor hot path boundaries without changing quality settings.
4. Re-measure to confirm improvements.
5. Only then decide whether any deeper playlist-resolution changes are still needed.

## Success Criteria

The design is successful if:

- audio quality settings remain unchanged
- `pause`, `resume`, `skip`, `back`, and `leave` feel materially faster to the user
- normal single-track `play` starts faster or at least no slower
- Spotify playlist startup no longer spends extra time on avoidable Python-side UI/DB work
- logs clearly show where time is spent when a command still feels slow

## Risks

- Background tasks may introduce ordering issues if they assume state that changes immediately after playback transitions.
- Controller/UI eventual consistency may briefly show stale data.
- Making reads cheaper than writes in Mongo cache code must avoid data races and stale mutation bugs.
- Playlist startup optimization may be limited by Lavalink/LavaSrc behavior that cannot be changed from the Python layer alone.

## Recommended Next Step

Write an implementation plan that starts with instrumentation and hot-path separation before making any playlist-specific behavioral changes.
