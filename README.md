# Vocard Homelab Fork

This fork keeps the upstream Vocard bot baseline and packages it for a small single-guild homelab deployment. It is designed for one Discord server, Docker Compose, no dashboard container, no public MongoDB/Lavalink ports, and environment-driven secrets.

## What Runs

The Compose stack starts four services:

- `bot`: local Vocard image on `python:3.14.5-slim-bookworm`.
- `lavalink`: `ghcr.io/lavalink-devs/lavalink:4.2.2`.
- `spotify-tokener`: pinned `ghcr.io/topi314/spotify-tokener` helper for LavaSrc Spotify token refresh.
- `mongo`: `mongo:4.4.29-focal` with a named persistent volume.

Lavalink plugins are pinned in `lavalink/application.yml`:

- `com.github.topi314.lavasrc:lavasrc-plugin:4.8.3`
- `dev.lavalink.youtube:youtube-plugin:1.18.1`

## Can I Run It Immediately After Clone?

`docker compose up` can be executed from a fresh clone without failing because `.env` is missing, but the bot cannot log in until real credentials are provided. This is intentional: Discord tokens, server IDs, Mongo passwords, Lavalink passwords, and Spotify credentials must not be committed.

For a real run, copy the example env and fill the required values first:

```bash
cp .env.example .env
$EDITOR .env
docker compose up -d --build
```

The first Lavalink boot may take a few minutes because pinned plugins are downloaded into the `lavalink_plugins` volume. Later starts reuse that volume.

## Required Env Values

Fill these in `.env` before production use:

- `DISCORD_TOKEN`: Discord bot token. Legacy `BOT_TOKEN` and `TOKEN` are still accepted by the bot.
- `SERVER_ID`: the only Discord guild this bot will serve. Legacy `DISCORD_GUILD_ID` is still accepted.
- `MONGO_IMAGE`: defaults to `mongo:4.4.29-focal` for Intel N4100 and other non-AVX CPUs.
- `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `MONGODB_URL`, `MONGODB_NAME`.
- `MONGODB_MAX_POOL_SIZE`, `MONGODB_MIN_POOL_SIZE`: default to `10` and `0` for a small single-guild homelab.
- `MONGODB_SERVER_SELECTION_TIMEOUT_MS`, `MONGODB_CONNECT_TIMEOUT_MS`, `MONGODB_SOCKET_TIMEOUT_MS`, `MONGODB_WAIT_QUEUE_TIMEOUT_MS`: keep Mongo fail-fast instead of hanging on broken I/O.
- `MONGO_WIREDTIGER_CACHE_SIZE_GB`: defaults to `0.25` to keep Mongo memory usage sane on low-end homelab machines.
- `LAVALINK_HOST`, `LAVALINK_PORT`, `LAVALINK_PASSWORD`.
- `LAVALINK_JAVA_OPTS`: defaults to `-Xms128m -Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=200` to avoid oversized JVM defaults on small hosts.
- `LAVALINK_SPOTIFY_PLAYLIST_TIMEOUT_SECONDS`: defaults to `90` so slow Spotify playlist lookups do not get cut off by the bot-side REST client after only 30 seconds.
- `LAVASRC_SPOTIFY_CLIENT_ID`, `LAVASRC_SPOTIFY_CLIENT_SECRET`.

`CLIENT_ID` is optional; the bot derives it from Discord after login. `DEFAULT_LANGUAGE=VN` is the homelab default; message strings use `langs/VN.json`, and Discord slash-command localization uses `local_langs/vi.json`.

## Spotify Notes

Spotify is handled by LavaSrc, not by a separate ad-hoc container. The Compose-managed `spotify-tokener` service is wired through:

```env
LAVASRC_SPOTIFY_CUSTOM_TOKEN_ENDPOINT=http://spotify-tokener:8080/api/token
```

For generated/editorial playlists, set `LAVASRC_SPOTIFY_SP_DC` from your logged-in `open.spotify.com` browser cookie. Slow Spotify playlist lookups are expected; this fork keeps a longer bot-side timeout for Spotify playlist `loadtracks` requests instead of failing after the default 30-second REST read window.

## Single-Guild Behavior

When `SERVER_ID` is set:

- Messages and interactions outside that guild are ignored.
- The bot auto-leaves unauthorized guilds on startup and future joins.
- Slash commands are synced only to the allowed guild.
- Foreign guild Mongo documents are not deleted; the bot simply stops reading/writing unauthorized guild state.

## Operations

Useful commands:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
docker compose logs -f lavalink
docker compose down
```

MongoDB and Lavalink plugin jars persist in named volumes:

- `mongo_data`
- `lavalink_plugins`

The Compose defaults in this fork intentionally favor stability on small homelab hardware:

- MongoDB is pinned to `4.4` for non-AVX CPUs and uses a conservative WiredTiger cache cap by default.
- Lavalink keeps the quality-first audio settings in `lavalink/application.yml`, but the JVM heap is bounded so the music node does not over-claim RAM.
- The bot container enables Python fault-handler output, runs as an unprivileged `vocard` user, and writes logs to stdout/stderr by default for Docker-native troubleshooting.

To reset all persisted data, explicitly remove volumes:

```bash
docker compose down -v
```

## Production Defaults

This fork defaults to homelab-safe operation:

- MongoDB is pinned to 4.4 because MongoDB 5+ requires AVX on x86_64 and will not start on Intel N4100-class CPUs.
- MongoDB and Lavalink are only reachable on the internal Compose network.
- Bot logs go to Docker stdout/stderr by default via `LOG_FILE_ENABLE=false`.
- The bot image drops root privileges at runtime; only the bot process writes inside `/app`.
- Lavalink built-in YouTube is disabled; the pinned YouTube plugin handles search.
- YouTube playback uses `TVHTML5_SIMPLY` and `MWEB` as extra fallback clients for `youtube-source 1.18.1`.
- Audio quality is set high with `opusEncodingQuality: 10`, `resamplingQuality: HIGH`, and a larger frame buffer.
- Upstream update checks are disabled by default with `CHECK_UPSTREAM_UPDATES=false`.
- Remote migration execution via `python update.py -m` is intentionally disabled in this fork; use `git pull` plus `docker compose up -d --build` and run any database migrations manually.

Rotate any token or secret that has been pasted into chat or logs before exposing this bot beyond local testing.

## Local Verification

Run the test suite before changing deployment code:

```bash
PYENV_VERSION=3.14.3 .venv/bin/pytest -q
PYENV_VERSION=3.14.3 .venv/bin/python -m compileall function.py main.py voicelink tests
docker compose config --quiet
```
