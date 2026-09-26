# Muse

Muse is a small self-hosted music server for two listeners. It serves a read-only music library
and its catalog database to a web client: listings, search, playlists, streaming with byte
ranges, likes, listening stats, shared listening, letters, a shared pet and daily playlists.

The repository holds two Python packages:

- `packages/server` (`muse`): the Litestar server.
- `packages/agent` (`muse_agent`): the home agent. It publishes the library to object storage,
  asks a local model for the daily playlists and pulls nightly backups.

## Configuration

The server reads the TOML file named by `MUSE_CONFIG` (default `/etc/muse/muse.toml`); any key
can be overridden with a `MUSE_<SECTION>__<KEY>` environment variable. Start from
`deploy/muse.example.toml`.

The agent reads `MUSE_AGENT_CONFIG` or `%APPDATA%/muse/agent.toml`. Start from
`deploy/agent.example.toml`.

## Users and library

Copy `deploy/users.example.json` to `users.json` in the data directory, put in your names and
set passwords with `uv run muse passwd <user-id>`. `animal` and `theme` go to the web client as
they are; `emoji` and `nick` sign the push notifications.

The catalog is a read-only SQLite file in the schema of `tests/fixtures/catalog_schema.sql`,
with track paths relative to the library. The web client is not part of this repository; the
server serves whatever is built into `web_dir`. User-facing texts are in Russian.

## Development

    uv sync --all-packages --group dev
    uv run pre-commit install
    uv run ruff check . && uv run ruff format --check .
    uv run lint-imports
    uv run ty check
    uv run pytest

Set `MUSE_TEST_REDIS=redis://127.0.0.1:6379/15` to include the Redis cache tests.

    uv run muse db upgrade
    uv run muse serve
    uv run muse passwd <user-id>

## Deployment

`deploy/provision.sh` prepares an Ubuntu host: system users, directories, Redis, the read-only
library mount, systemd units and the firewall. Releases ship from a clean checkout:

    uv run python scripts/deploy.py

The script streams the current commit and the built web client over SSH to
`muse-install-release`, which installs the release, migrates the database and switches over
only after a health check.

## License

MIT
