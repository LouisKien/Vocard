# Production Hardening Design

## Goal

Bring this single-guild homelab fork closer to production-grade operation without reducing audio quality. The work should prioritize runtime reliability, resource efficiency on low-end hardware, and maintainable behavior in the hottest code paths.

## Constraints

- Keep the current Lavalink quality-first audio settings intact.
- Do not reintroduce Spotify fast-start or performance timing log noise.
- Favor changes with measurable operational value over broad refactors.
- Preserve the current single-guild model and Docker deployment flow.

## Reviewed Areas

- Docker runtime and service-level resource defaults.
- Lavalink node HTTP/session lifecycle and failure behavior.
- MongoDB cache and request paths used on common commands.
- Queue primitives and player/runtime helpers that still use broad exception handling.
- Package entrypoints and utility modules where cleanup can remove hidden runtime risk.

## Approaches Considered

### 1. Large-scale architecture refactor

Split `player.py`, `basic.py`, and cache/database code aggressively into many smaller units.

Trade-off:
- Improves long-term structure.
- Creates a large regression surface and does not directly guarantee better production behavior in one pass.

### 2. Quality trade-down for latency

Reduce Lavalink buffer and encoding settings to chase responsiveness.

Trade-off:
- May make commands feel snappier.
- Conflicts directly with the requirement to keep audio quality first.

### 3. Targeted production hardening

Keep the quality-first audio path unchanged and focus on the subsystems that still risk instability, unnecessary latency, or wasted resources.

Trade-off:
- Highest operational value per line changed.
- Leaves large files structurally large for now, but makes them safer and cheaper to run.

## Chosen Design

Use targeted production hardening.

### Runtime and resource hardening

- Give Lavalink node sessions explicit `aiohttp` timeouts and conservative connector limits so failed upstream calls do not hang indefinitely.
- Track whether a Lavalink node owns its HTTP session and close owned sessions during disconnect/teardown to avoid resource leakage.
- Improve REST error surfaces to preserve status/body context for production debugging.
- Tighten Docker resource defaults for homelab operation without reducing audio quality:
  - conservative Mongo WiredTiger cache limit
  - conservative Lavalink JVM heap defaults
  - safer Python container defaults

### Cache and hot-path efficiency

- Add a no-lock fast path for cached user data, mirroring the current settings cache optimization.
- Use cached settings/user data in hot call sites before falling back to async DB reads.
- Keep Mongo on the cold path whenever data is already in memory.

### Runtime correctness and exception hygiene

- Remove broad exception handlers in critical runtime modules where explicit exceptions are safer and more debuggable.
- Fix the latent `timer()` reference left behind in `voicelink/utils.py`.
- Clean queue helpers so they fail with explicit queue/domain exceptions instead of swallowing unrelated errors.
- Clean a small set of package/export modules so the project moves closer to a reliable lint baseline.

### Quality preservation

- Do not lower Lavalink `opusEncodingQuality`, `resamplingQuality`, or buffer settings.
- Do not reduce source quality or change the current LavaSrc/youtube plugin strategy.

## Expected Outcome

- Fewer hidden runtime failures caused by swallowed exceptions.
- Lower chance of stuck network operations or leaked node sessions.
- Less Mongo overhead on repeated guild/user lookups.
- Better resource discipline for Intel N4100-class homelab hardware.
- Cleaner source with fewer production footguns, while preserving current audio fidelity.
