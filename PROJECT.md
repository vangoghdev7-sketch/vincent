# Vincent + Vincent — One Project

Two cooperating stacks, one folder, one launcher. Nothing here is a copy or a
reinstall: the running software stays where it was installed and this repo just
points at it and drives it.

## The two UIs

| UI | URL | What it is | How it runs |
|----|-----|------------|-------------|
| **Vincent** | http://localhost:3000 | Operator dashboard (frontend) + backend `:8000` | podman/docker containers (`vincent_os-frontend` / `-backend`) |
| **Vincent / Vincent OS** | http://localhost:20128 | AI router dashboard + OpenAI-compatible API (`/v1/*`) | npm-global `vincent_os`, detached process |

The Vincent top bar has a **VINCENT** button that opens `:20128` (appears
after a frontend image rebuild — see below), and Vincent drives Vincent as
an AI operator through the installed `vincent_os` openclaw skill, so the two
act as one app.

## How they are connected

**Vincent → Vincent (AI operator).** The repo ships an openclaw skill at
`openclaw-skills/vincent_os/` (`sb.ask()`, `sb.run_playbook()`,
`sb.send_command()`, HMAC signer). It is symlinked into Vincent's openclaw at
`~/.openclaw/skills/vincent_os`. Because Vincent runs on the same host, the
skill talks to `http://127.0.0.1:8000` as **local operator** (loopback, no HMAC
secret needed — HMAC is only for remote/Tor agents). Vincent can now query
telemetry, drop map pins, run playbooks, and monitor autonomously.

**Vincent ↔ Vincent LLM.** Vincent's OpenAI-compatible endpoint is
`http://localhost:20128/v1` (model `vincent`, zero-key). From inside the backend
container the host is reachable as `http://host.containers.internal:20128/v1`
(verified). Vincent's own backend does not call an LLM by design — the AI
lives on Vincent's side and consumes Vincent as a tool API.

## Launch (both stacks)

```bash
./unified.sh start          # links + Vincent containers up + ensure Vincent OS up
./unified.sh status         # health of both + skill install check
./unified.sh stop           # stop Vincent containers (Vincent OS left running)
./unified.sh stop-vincent_os # explicitly stop the shared Vincent OS router
./unified.sh links          # (re)create the ./vincent symlink index only
```

`start` is safe to re-run: it runs `<engine> compose up -d` from this directory
with **no `-f` flag**, so both `docker-compose.yml` and
`docker-compose.override.yml` are merged (the exact pair the running containers
were created with) and healthy containers are not recreated. Vincent OS is only
started if `:20128` is not already answering.

> Do **not** use `./compose.sh` to bring the stack up here: it passes
> `-f docker-compose.yml` only and would drop the override env on a recreate.

## ./vincent — the symlink index

`./vincent/` is a browsable, gitignored set of OUTWARD symlinks to the real,
running pieces (never moved, never reinstalled):

| link | target |
|------|--------|
| `vincent/config` | `~/.vincent` (live state + secrets) |
| `vincent/vincent_os-config` | `~/.vincent_os` (live router DB + encryption key) |
| `vincent/openclaw-agents` | `~/.openclaw/agents` (6 `vincent-*` agents) |
| `vincent/openclaw-skill` | `~/.openclaw/skills/vincent_os` (the binding into Vincent) |
| `vincent/cli-venv` | pipx venv for `vincent-cli` (shebang-pinned) |
| `vincent/bin` | `~/.local/bin` (`vincent-*` wrapper scripts) |
| `vincent/vincent_os-global` | npm-global `vincent_os` module |

**Do not** `git add vincent/` — the paths are host-specific and some targets
hold secrets. It is gitignored on purpose.

## VINCENT button (frontend)

The top-bar button was added in `frontend/src/components/TopRightControls.tsx`
(+ `controls.vincent` in the four locale files). The frontend runs from a
prebuilt GHCR image, so the button only appears after a rebuild + restart:

```bash
# only when you want to deploy the UI change (recreates the frontend container)
podman compose -f docker-compose.yml -f docker-compose.override.yml \
  build frontend && podman compose up -d frontend
```

## Guardrails

- The pipx `vincent-cli` venv and the npm-global `vincent_os` module are
  path-pinned — never move or reinstall them.
- Never symlink the individual `*.sqlite` / `*.db` files (active WAL); only the
  parent config directories are linked.
- Vincent OS has no supervisor of its own; `unified.sh` is its start hook.

## Known issue (not caused by this integration)

The `vincent_os-backend` container is CPU-saturated: its fast-tier ingest
cycle (`update_fast_data`) runs ~65s and Tor mesh gate-pulls to dead `.onion`
peers block on 45s timeouts, which stalls the event loop so `:8000` stops
answering HTTP for stretches. The UI shell at `:3000` loads but live data and
Vincent's skill calls will hang during those stalls. This is a pre-existing
performance/config problem, tracked separately.
