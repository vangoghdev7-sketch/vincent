# VincentOS

**A unified OSINT intelligence command center under one identity: Vincent.**

VincentOS combines a real-time, multi-domain OSINT platform with the Vincent AI brain into a single operating surface. One map, one command channel, one identity. The platform aggregates live telemetry from 60+ public intelligence feeds — aircraft, ships, satellites, conflict zones, CCTV networks, GPS jamming, internet-connected devices, police scanners, mesh radio nodes, and breaking geopolitical events — onto one dark-ops map. Vincent, the resident AI brain, sees everything the operator sees and can act on the map in real time as a co-analyst.

Built with Next.js, MapLibre GL, FastAPI, and Python for the intelligence platform, and Vincent OS for the Vincent AI brain. The two run side by side and behave as one application.

---

## One identity: Vincent

VincentOS is two cooperating planes in one folder, driven by one launcher. Nothing is copied or reinstalled — the running software stays where it was installed, and this repository points at it and drives it.

| Plane | URL | What it is | How it runs |
|-------|-----|------------|-------------|
| **Intelligence platform** | http://localhost:3000 | Operator dashboard (frontend) + backend on `:8000` | Docker/Podman containers (`vincent_os-frontend` / `vincent_os-backend`) |
| **Vincent (AI brain)** | http://localhost:20128 | Vincent OS AI router dashboard + OpenAI-compatible API (`/v1/*`), model `vincent`, zero-key | npm-global `vincent_os`, detached process |

The dashboard's top bar carries a **VINCENT** button that opens `:20128`, and Vincent drives the platform as an AI operator through the installed `vincent_os` OpenClaw skill. The two act as one app: the map is Vincent's instrument, and Vincent is the analyst at the controls.

Designed for analysts, researchers, radio operators, and anyone who wants to see what the world looks like when every public signal is on the same map — with an AI brain that can read it, reason over it, and mark it up alongside you.

---

## Why this exists

A surprising amount of global telemetry is already public: aircraft ADS-B broadcasts, maritime AIS signals, satellite orbital data, earthquake sensors, mesh radio networks, police scanner feeds, environmental monitoring stations, and internet infrastructure telemetry. This data is scattered across dozens of tools and APIs. VincentOS combines all of it into a single interface and puts an AI brain behind the glass.

The project introduces no new surveillance capabilities — it aggregates and visualizes existing public datasets. It is fully open so anyone can audit exactly what data is accessed and how. There are no accounts, no product telemetry, and no analytics; the dashboard talks only to your self-hosted backend. Sensitive recon and Shodan queries never hit third-party APIs from the browser — they are proxied through the backend with SSRF guards and local-operator auth. Operator-supplied keys stay in your local deployment, but live OSINT features necessarily make outbound requests to the public data providers you enable or query.

---

## Quick start

### Option A — Unified launcher (Vincent-native, recommended)

From the repository root, `unified.sh` brings up the platform containers and ensures the Vincent brain is answering on `:20128`. It never moves or reinstalls anything.

```bash
./unified.sh start          # links + platform containers up + ensure Vincent OS up
./unified.sh status         # health of both planes + skill install check
./unified.sh stop           # stop platform containers (Vincent OS left running)
./unified.sh stop-vincent_os # explicitly stop the shared Vincent OS brain
./unified.sh links          # (re)create the ./vincent symlink index only
```

`start` is safe to re-run. It runs `<engine> compose up -d` from the repository directory with no `-f` flag, so both `docker-compose.yml` and `docker-compose.override.yml` are merged (the exact pair the running containers were created with) and healthy containers are not recreated. Vincent OS is started only if `:20128` is not already answering.

> Do **not** use `./compose.sh` to bring the stack up here: it passes `-f docker-compose.yml` only and would drop the override environment on a recreate.

**Prerequisite for the brain:** the Vincent brain is the npm-global `vincent_os` router, installed separately and answering on `:20128`. It is not bundled with the platform images. If `:20128` is not up, `unified.sh` attempts to start the installed `vincent_os` binary; if none is found, install and start it before the VINCENT button and AI operator features come alive.

### Option B — Platform only (Docker)

The intelligence platform runs on its own from pre-built images in GitHub Container Registry.

```bash
docker compose pull
docker compose up -d
```

Open `http://localhost:3000` to view the dashboard. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine.

**Podman users:** `podman compose` is a wrapper and still needs a Compose provider installed. If you see `looking up compose provider failed`, install `podman-compose` and run `podman-compose pull` followed by `podman-compose up -d` from inside the repository folder. On bash-compatible shells you can also use `./compose.sh --engine podman pull` and `./compose.sh --engine podman up -d`.

**Backend port already in use?** The browser only needs port `3000`, but the backend API is also published on host port `8000` for local diagnostics. If another app already uses `8000`, create or edit `.env` next to `docker-compose.yml` and set `BACKEND_PORT=8001`, then run `docker compose up -d`. Leave `BACKEND_URL` as `http://backend:8000` — that is the Docker-internal address.

**Blank news, bases, or wastewater after several minutes?** Check for backend OOM restarts with `docker events --since 30m --filter container=vincent_os-backend --filter event=oom`. The default compose file gives the backend 4GB; if your host has less memory, reduce enabled feeds or set `BACKEND_MEMORY_LIMIT=3G` and expect heavier layers to warm more gradually.

---

## Ports at a glance

| Port | Plane | Exposure | Purpose |
|------|-------|----------|---------|
| `3000` | Intelligence platform (frontend) | Browser-facing | The operator dashboard. This is the only port the browser needs. |
| `8000` | Intelligence platform (backend) | `127.0.0.1` only | FastAPI backend for local diagnostics and the AI command channel. Inside Docker it is reached as `http://backend:8000`. |
| `20128` | Vincent brain (Vincent OS) | Host | OpenAI-compatible API (`/v1`), model `vincent`, zero-key, plus the router dashboard. |

---

## How Vincent connects

**Vincent to platform (AI operator).** The repository ships an OpenClaw skill at `openclaw-skills/vincent_os/` (`sb.ask()`, `sb.run_playbook()`, `sb.send_command()`, HMAC signer). It is symlinked into Vincent's OpenClaw at `~/.openclaw/skills/vincent_os`. Because Vincent runs on the same host, the skill talks to `http://127.0.0.1:8000` as **local operator** — loopback, no HMAC secret needed (HMAC is only for remote or Tor agents). Vincent can query telemetry, drop map pins, run playbooks, and monitor autonomously.

**Platform to Vincent (the brain).** Vincent's OpenAI-compatible endpoint is `http://localhost:20128/v1` (model `vincent`, zero-key). From inside the backend container the host is reachable as `http://host.containers.internal:20128/v1`. The intelligence backend does not call an LLM by design — the AI lives on Vincent's side and consumes the platform as a tool API. This keeps the brain and the sensor plane cleanly decoupled: swap the model behind Vincent OS without touching the platform, and reshape the platform without retraining the brain.

### The ./vincent symlink index

`./vincent/` is a browsable, gitignored set of outward symlinks to the real, running pieces (never moved, never reinstalled):

| Link | Target |
|------|--------|
| `vincent/config` | `~/.vincent` (live state and secrets) |
| `vincent/vincent_os-config` | `~/.vincent_os` (live router DB and encryption key) |
| `vincent/openclaw-agents` | `~/.openclaw/agents` (the `vincent-*` agents) |
| `vincent/openclaw-skill` | `~/.openclaw/skills/vincent_os` (the binding into Vincent) |
| `vincent/cli-venv` | pipx venv for `vincent-cli` |
| `vincent/bin` | `~/.local/bin` (`vincent-*` wrapper scripts) |
| `vincent/vincent_os-global` | npm-global `vincent_os` module |

Do **not** `git add vincent/` — the paths are host-specific and some targets hold secrets. It is gitignored on purpose.

---

## How to update

The platform uses pre-built container images — no local building required.

```bash
docker compose pull
docker compose up -d
```

`pull` grabs the latest images, `up -d` restarts the containers. Podman users should run the equivalent provider command, for example `podman-compose pull` and `podman-compose up -d`, or `./compose.sh --engine podman pull` and `./compose.sh --engine podman up -d`.

**Building from source instead of pulling?** If `docker compose up` shows `RUN apt-get`, `RUN npm ci`, or `RUN pip install`, it is building from source rather than pulling pre-built images, and your clone predates a repository history rewrite. A normal `git pull` cannot fix this — back up any local config (`.env`, etc.), remove the clone, re-clone fresh, then `docker compose pull` and `docker compose up -d`.

Other troubleshooting: force re-pull with `docker compose pull --no-cache`, prune old images with `docker image prune -f`, and check logs with `docker compose logs -f backend`.

### Update integrity

Container updates are delivered through signed registries. The legacy ZIP self-updater verifies release archives through this chain, in order: `MESH_UPDATE_SHA256` when an operator pins a digest explicitly, then `backend/data/release_digests.json` for bundled release pins, then the release `SHA256SUMS.txt` asset when a bundled pin is not present. The updater keeps the operator override path intact instead of failing closed on missing bundled digests, so existing installs are not stranded by a release-process mistake.

### CSP hardening

The production frontend ships with a hydration-compatible CSP and a strict nonce-only CSP in `Content-Security-Policy-Report-Only`. Set `VINCENT_STRICT_CSP=1` only after verifying the exact build hydrates correctly in your deployment. Runtime Google Fonts are not required; the bundled Next font pipeline serves the dashboard font from the app build.

---

<details>
<summary>Kubernetes / Helm (advanced)</summary>

For high-availability deployments or home-lab clusters, the platform supports deployment via Helm. The chart is based on the `bjw-s-labs` template and provides a modular setup for both the backend and frontend.

**1. Add the repository:**
```bash
helm repo add bjw-s-labs https://bjw-s-labs.github.io/helm-charts/
helm repo update
```

**2. Install the chart:**
```bash
# Default — pulls images from GHCR
helm install vincent_os ./helm/chart --create-namespace --namespace vincent_os

# GitLab registry variant
helm install vincent_os ./helm/chart --create-namespace --namespace vincent_os \
  -f helm/chart/values.yaml \
  -f helm/chart/values-gitlab.yaml
```

**3. Key features:**
- **Modular architecture** — scale the intelligence backend and the HUD frontend independently.
- **Security context** — runs with restricted UIDs (1001) for container hardening.
- **Ingress ready** — compatible with Traefik, Cert-Manager, and Gateway API for secure external access.

</details>

---

<details>
<summary>Experimental testnet — no privacy guarantee</summary>

The platform ships **InfoNet** (a decentralized intelligence mesh plus the Sovereign Shell governance economy), an **agentic AI command channel** (Vincent via OpenClaw, and any HMAC-signing agent), **Time Machine snapshot playback**, and **SAR satellite ground-change detection**. This is an experimental testnet — not a private messenger and not a production governance system.

| Channel | Privacy status | Details |
|---|---|---|
| **Meshtastic / APRS** | **PUBLIC** | RF radio transmissions are public and interceptable by design. |
| **InfoNet gate chat** | **OBFUSCATED** | Messages are obfuscated with gate personas and canonical payload signing, but not end-to-end encrypted. Metadata is not hidden despite being designed around Tor and Reticulum (work in progress). |
| **Dead Drop DMs** | **STRONGEST CURRENT LANE** | Token-based epoch mailbox with SAS word verification. Strongest lane in this build, but not yet confidently private. |
| **Sovereign Shell governance** | **PUBLIC LEDGER** | Petitions, votes, upgrade hashes, and dispute stakes are signed events on a public hashchain. Pseudonymous via gate persona, but governance actions are intentionally observable. |
| **Privacy primitives (RingCT / stealth / DEX)** | **NOT YET WIRED** | Locked protocol contracts are in place, but the cryptographic scheme has not been chosen. The `privacy-core` Rust crate is the integration target for a future sprint. |

**Do not transmit anything sensitive on any channel.** Treat all lanes as open and public for now. End-to-end encryption and deeper native hardening are the next milestones. If you fork this project, keep these labels intact and do not make stronger privacy claims than the implementation supports.

For a full picture of what the mesh defends against and what it does not, read the threat model and the claims reconciliation under `docs/mesh/`. Every statement above is mapped there to the code path that enforces it (or does not).

</details>

---

<details>
<summary>Features</summary>

### Vincent AI command channel — OpenClaw and compatible agents

VincentOS exposes a bidirectional agentic AI command channel: a signed, tier-gated bridge that gives a compatible AI agent full read/write access to the intelligence platform. **Vincent is the resident agent**, driving the platform through the `vincent_os` OpenClaw skill on loopback. The channel is also an open protocol — any LLM-driven agent that signs requests with HMAC-SHA256 (Claude Code, GPT, LangChain, or a custom client) can connect as an analyst that sees the same data as the operator and can act on the map. The platform does not bundle model weights or an agent runtime; it provides the surface, and Vincent (or any agent) brings the reasoning.

- **Single command channel** — `POST /api/ai/channel/command` accepts `{cmd, args}` and dispatches to any registered tool.
- **Batched concurrent execution** — `POST /api/ai/channel/batch` accepts up to 20 commands in one request, run concurrently with a fan-out result map. Cuts agent latency by an order of magnitude over sequential calls.
- **Tier-gated access** — `OPENCLAW_ACCESS_TIER` controls which commands are callable: `restricted` exposes the read-only set, `full` adds writes and injection. A discovery endpoint returns `available_commands` so the agent can introspect its own capabilities.
- **HMAC-SHA256 signing** — every command is signed `HMAC-SHA256(secret, METHOD|path|timestamp|nonce|sha256(body))` with timestamp and nonce replay protection. Supports local mode (no config, loopback trust) and remote mode (agent on a different machine or VPS).

Capabilities: full telemetry access across all 40+ layers; compact cross-layer search (`search_telemetry`, `search_news`, `entities_near`, `brief_area`, `find_flights`/`find_ships`/`find_entity`, `correlate_entity`); the SSRF-guarded recon toolkit on the channel (`osint_lookup`, `entity_expand`, `osint_sweep`); AI intel pins (14 categories, confidence scores, TTL, batch placement); map control (fly-to, satellite lookups, region dossiers); SAR ground-change inspection and AOI management; native layer injection; Wormhole mesh participation; Sovereign Shell governance participation; geocoding and proximity scans; news and GDELT near a location; alert delivery to Discord and Telegram; and structured intelligence reports. Every channel call is logged and auditable.

**Connect an agent:** open the AI Intel panel in the left sidebar, click **Connect Agent**, and copy the HMAC secret. For Vincent on the same host, no secret is needed — the skill talks to `http://127.0.0.1:8000` as local operator over loopback. For remote agents, use the HMAC contract above. Discovery: `GET /api/ai/tools` and `GET /api/ai/capabilities`.

**Docker Compose and remote agents:** the dashboard talks to the backend over Docker's private bridge (trusted automatically). An agent on the host (outside the container) hits `http://localhost:8000` from the Docker gateway IP, where HMAC is required. In AI Intel → **Connect Agent**, click **Bootstrap** then **Reveal**, copy `VINCENT_HMAC_SECRET` into your agent environment, and restart the backend once so `data/openclaw.env` on the `backend_data` volume is loaded. Smoke-test with:

```bash
export VINCENT_URL=http://127.0.0.1:8000
export VINCENT_HMAC_SECRET=<from Connect Agent modal>
python openclaw-skills/vincent_os/verify_hmac.py
```

Use the backend port (`:8000`), not the dashboard port (`:3000`). Hand-rolled signers must hash the exact POST bytes: `json.dumps(payload, separators=(",", ":"), sort_keys=True)`.

The Vincent skill exposes a three-tool fast path over this channel — `sb.ask("natural language question")` for reads (the server routes to the fastest command), `sb.run_playbook("hot_snapshot")` for pre-batched snapshots, and `sb.channel_status()` for liveness. Named playbooks include `hot_snapshot`, `morning_brief`, `status_check`, `monitor_heartbeat`, `track_snapshot`, `jet_recon`, `area_brief`, and `entity_recon`.

### InfoNet — decentralized intelligence mesh and Sovereign Shell

A decentralized intelligence communication and governance layer built directly into the platform. No accounts, no signup, no identity required.

Communication layer: the InfoNet experimental testnet is a global, obfuscated message relay using Tor and Reticulum, with a three-tab Mesh Chat panel (INFONET gate chat, MESH Meshtastic radio, DEAD DROP peer-to-peer exchange), a gate persona system with Ed25519 signing and SAS word verification, and a built-in Mesh Terminal CLI (`send`, `dm`, market commands, gate state inspection; type `help` for all commands). Crypto stack: Ed25519 signing, X25519 Diffie-Hellman, AES-GCM with HKDF, and a hash-chain commitment system.

Sovereign Shell governance economy: on-chain parameter changes via signed petitions and a type-safe governance DSL (`UPDATE_PARAM`, `BATCH_UPDATE_PARAMS`, `ENABLE_FEATURE`, `DISABLE_FEATURE`); upgrade-hash governance (80% supermajority, 40% quorum, 67% Heavy-Node activation); resolution and dispute markets with bonded evidence; gate suspension/shutdown/appeal flows; bootstrap eligible-node-one-vote for the first 100 markets; two-tier state with epoch finality; adaptive polling; and verbatim backend rejection reasons on every write.

Privacy primitive runway: anonymous credential scaffolding (nullifiers, challenge-response, two-phase commit receipts) where today's challenge-response is an HMAC-based placeholder for integration testing, not a production zero-knowledge proof; locked protocol contracts in `services/infonet/privacy/contracts.py` for ring signatures, stealth addresses, Pedersen commitments, range proofs, and DEX matching; and a clear path to wire a chosen cryptographic scheme into the locked protocols without API churn.

> InfoNet messages are obfuscated but not end-to-end encrypted. The Meshtastic/APRS mesh is inherently public. The privacy primitive contracts are scaffolded but not yet wired. Do not send anything sensitive on any channel.

### Recon toolkit and Shodan (security-first)

Adapted from the OSIRIS recon stack (MIT) with the platform's proxy model. All lookups run **server-side only**: the browser calls your self-hosted `/api/osint/*` and `/api/tools/shodan/*` routes, and outbound requests are made by the backend after SSRF validation. Recon requires local-operator access.

- **IP / DNS / WHOIS** — ip-api.com geolocation, Google DNS-over-HTTPS, RDAP registrant data with optional HTTP security-header scoring.
- **Certificates and BGP** — crt.sh subdomain discovery, bgpview.io ASN/prefix lookups.
- **Threat intel** — AlienVault OTX pulses, Tor exit-node checks, optional per-IP/domain reputation.
- **Sanctions** — OpenSanctions `us_ofac_sdn` index, cross-checked on WHOIS entities and IP ISP/org strings.
- **CVE / MAC / GitHub / leaks** — MITRE CVE API, MAC vendor lookup, GitHub profile recon, public breach checks.
- **IP sweep** — `/api/osint/sweep/scan` geolocates a target /24–/32 and proxies Shodan InternetDB host discovery server-side.
- **SSRF guard** — private, loopback, link-local, and metadata hostnames are blocked before any user-supplied fetch.
- **Entity graph** — select any map entity to resolve aircraft, vessels, companies, persons, IPs, and countries into a node/link graph (Wikidata SPARQL + OFAC + in-memory flight/ship store) via `GET /api/entity/expand`.
- **Shodan overlay** — query Shodan with your own API key; results plot as a live overlay with configurable markers.

### Aviation, maritime, and rail

Real-time commercial, private, and military flights via OpenSky and adsb.lol, with private-jet owner identification, persistent breadcrumb trails, holding-pattern detection, shape-accurate aircraft icons, and grounded detection. AIS vessel stream of 25,000+ ships via aisstream.io with type classification and clustering; a Carrier Strike Group tracker that estimates all active US Navy carrier positions from automated GDELT news scraping; cruise/passenger and fishing-activity (Global Fishing Watch) layers. Amtrak and DigiTraffic European rail positions in real time.

### Space, satellites, and imagery

Orbital tracking via CelesTrak TLE + SGP4 (2,000+ satellites, no key), color-coded by mission type, with SatNOGS and TinyGS ground-station networks. NASA GIBS (MODIS Terra) daily imagery with a 30-day time slider, high-res Esri World Imagery, a right-click Sentinel-2 intel card (10m resolution), Sentinel Hub Process API via Copernicus CDSE, and VIIRS nightlights. Five visual modes via the STYLE button: DEFAULT (dark basemap), SATELLITE, FLIR (thermal), NVG (night vision), and CRT (retro terminal).

### SAR ground-change detection

Synthetic Aperture Radar detects ground changes through cloud cover, at night, anywhere on Earth. Mode A (catalog) uses free Sentinel-1 scene metadata from the Alaska Satellite Facility, no account required. Mode B (full anomalies) delivers real-time ground-change alerts from NASA OPERA and Copernicus EGMS with a free NASA Earthdata account. Anomaly types cover ground deformation, surface-water change, vegetation disturbance, damage assessments, and coherence change, with color-coded pins, an in-map AOI editor, and Vincent integration (`sar_pin_click`, `sar_focus_aoi`) for collaborative analyst workflows.

### SDR, SIGINT, and surveillance

500+ public KiwiSDR receivers with an embedded live tuner, Meshtastic MQTT mesh radio, APRS-IS positioning, GPS jamming detection from aircraft NAC-P degradation analysis, and a scanner-style Radio Intercept panel with OpenMHZ police/fire feeds. CCTV mesh of 22,000+ live cameras from 21 ingestors across 10 countries, with automatic video/MJPEG/HLS/embed feed rendering and clustered map display.

### Environmental, hazard, and infrastructure

NASA FIRMS fire hotspots, Smithsonian volcanoes, severe-weather polygons, OpenAQ air quality, USGS earthquakes, and a live NOAA space-weather badge. Internet outage monitoring (IODA), 2,000+ data centers, global military bases, 35,000+ power plants (WRI), submarine cables (TeleGeography-derived GeoJSON), malware C2 (abuse.ch Feodo + URLhaus), SCM supplier risk scoring, CISA KEV cyber threats, a country risk index, and Telegram OSINT (public `t.me/s` war/OSINT channels scraped hourly, risk-scored, geoparsed, and plotted with inline media).

### Time Machine, additional layers, and tools

Time Machine is a media-style transport for the entire telemetry feed: a live/snapshot toggle that pauses the polling loop instantly, an hourly snapshot index, frame interpolation for moving entities, variable playback speed, and profile-aware, operator-side-only storage. Additional tools include a day/night solar terminator, a global markets ticker, a point-to-point measurement tool, and a LOCATE bar that flies to coordinates or place names via OSM Nominatim. A read-only API Keys panel (Settings) surfaces the absolute backend `.env` path with existence and writability indicators and a `CONFIGURED` / `NOT CONFIGURED` badge per key — key values never reach the browser.

</details>

---

<details>
<summary>Data sources and APIs</summary>

| Source | Data | Update frequency | API key required |
|---|---|---|---|
| OpenSky Network | Commercial and private flights | ~60s | **Yes** |
| adsb.lol | Military aircraft | ~60s | No |
| aisstream.io | AIS vessel positions | Real-time WebSocket | **Yes** |
| CelesTrak | Satellite orbital positions (TLE + SGP4) | ~60s | No |
| USGS Earthquake | Global seismic events | ~60s | No |
| GDELT Project | Global conflict events | ~6h | No |
| DeepState Map | Ukraine frontline | ~30min | No |
| Shodan | Internet-connected device search | On-demand | **Yes** |
| OpenSanctions | OFAC SDN sanctions index | 24h cache | No |
| abuse.ch Feodo + URLhaus | Malware C2 / distribution URLs | ~5min (opt-in) | No |
| CISA KEV | Known exploited CVEs | ~5min (opt-in) | No |
| ip-api.com | IP geolocation (recon, entity graph) | On-demand | No |
| Google Public DNS | DNS-over-HTTPS lookups (recon) | On-demand | No |
| RDAP.org | Domain registration data (recon) | On-demand | No |
| crt.sh | Certificate transparency (recon) | On-demand | No |
| bgpview.io | BGP/ASN routing (recon) | On-demand | No |
| TeleGeography (static) | Submarine cable routes | Static | No |
| ASFINAG | Austria motorway webcams | ~10min | No |
| Amtrak | US train positions | ~60s | No |
| DigiTraffic | European rail positions | ~60s | No |
| Global Fishing Watch | Fishing vessel activity | ~1hr | **Yes** (`GFW_API_TOKEN`) |
| Telegram public previews | War/OSINT channel posts | ~1hr | No (optional `TELEGRAM_OSINT_CHANNELS`) |
| Transport for London, NYC DOT, TxDOT | CCTV cameras (UK, US) | ~10min | No |
| Caltrans, WSDOT, GDOT, IDOT, MDOT | CCTV cameras (5 US states) | ~10min | No |
| Spain DGT, Madrid City | CCTV cameras (Spain) | ~10min | No |
| Singapore LTA | Singapore traffic cameras | ~10min | **Yes** |
| Windy Webcams | Global webcams | ~10min | No |
| SatNOGS | Amateur satellite ground stations | ~30min | No |
| TinyGS | LoRa satellite ground stations | ~30min | No |
| Meshtastic MQTT | Mesh radio node positions | Real-time | No |
| APRS-IS | Amateur radio positions | Real-time TCP | No |
| KiwiSDR | Public SDR receiver locations | ~30min | No |
| OpenMHZ | Police/fire scanner feeds | Real-time | No |
| Smithsonian GVP | Holocene volcanoes | Static (cached) | No |
| OpenAQ | Air quality PM2.5 stations | ~120s | No |
| NOAA / NWS | Severe weather alerts and polygons | ~120s | No |
| WRI Global Power Plant DB | 35,000+ power plants | Static (cached) | No |
| Military base datasets | Global military installations | Static (cached) | No |
| NASA FIRMS | NOAA-20 VIIRS fire/thermal hotspots | ~120s | No |
| NOAA SWPC | Space weather Kp index and solar events | ~120s | No |
| IODA (Georgia Tech) | Regional internet outage alerts | ~120s | No |
| NASA GIBS | MODIS Terra daily satellite imagery | Daily (24–48h delay) | No |
| Esri World Imagery | High-res satellite basemap | Static | No |
| MS Planetary Computer | Sentinel-2 L2A scenes (right-click) | On-demand | No |
| Copernicus CDSE | Sentinel Hub imagery (Process API) | On-demand | **Yes** (free) |
| VIIRS Nightlights | Night-time light change detection | Static | No |
| RestCountries | Country profile data | On-demand (cached 24h) | No |
| Wikidata SPARQL | Head of state data | On-demand (cached 24h) | No |
| Wikipedia API | Location summaries and aircraft images | On-demand (cached) | No |
| OSM Nominatim | Place name geocoding (LOCATE bar) | On-demand | No |
| CARTO Basemaps | Dark map tiles | Continuous | No |

**Outbound privacy and audit:** each self-hosted install uses its own backend IP and per-install User-Agent handle. See [docs/OUTBOUND_DATA.md](docs/OUTBOUND_DATA.md) for what contacts third parties, the opt-in and environment controls, and accepted tradeoffs.

</details>

---

<details>
<summary>Developer setup (run from source)</summary>

#### Prerequisites

- **Node.js** 18+ and npm.
- **Python** 3.10, 3.11, or 3.12 with `pip`. Python 3.13+ may have dependency compatibility issues; 3.11 or 3.12 is recommended.
- API keys for aisstream.io (required for ships), and optionally OpenSky (OAuth2) and Singapore LTA.

#### Installation

```bash
# Backend setup
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install .

# Create .env with your API keys
echo "AIS_API_KEY=your_aisstream_key" >> .env
echo "OPENSKY_CLIENT_ID=your_opensky_client_id" >> .env
echo "OPENSKY_CLIENT_SECRET=your_opensky_secret" >> .env

# Frontend setup
cd ../frontend
npm ci
```

#### Running

```bash
# From the frontend directory — starts frontend and backend concurrently
npm run dev
```

This starts the Next.js frontend on `http://localhost:3000` and the FastAPI backend on `http://localhost:8000`.

> **Running the backend outside Docker** (`cd backend && python main.py`): the dev server binds loopback only (`127.0.0.1:8000`) so other machines on your LAN cannot hit admin/local-trust routes with an empty `ADMIN_KEY`. Set `VINCENT_DEV_BIND_ALL=true` only when you deliberately need `0.0.0.0`, and use a strong `ADMIN_KEY` for any non-local callers.

#### Local AIS receiver (optional)

You can feed your own AIS ship data in using an RTL-SDR dongle and [AIS-catcher](https://github.com/jvde-github/AIS-catcher). Point the decoder at `http://localhost:4000/api/ais/feed` and ships detected by your antenna appear alongside the global AIS stream. Range depends on the antenna — typically 20–40 nautical miles with a basic setup.

</details>

---

<details>
<summary>Data layers</summary>

All 41 layers are independently toggleable from the left panel. Layers on by default include commercial/private/military flights and tracked aircraft, GPS jamming, carriers/military/cargo and civilian vessels, cruise/passenger and tracked yachts, fishing activity, trains, satellites, SatNOGS, TinyGS, earthquakes, fire hotspots, volcanoes, weather alerts, air quality, Ukraine frontline and air alerts, global incidents, CCTV mesh, internet outages, data centers, military bases, KiwiSDR, Meshtastic, APRS, scanners, day/night cycle, Telegram OSINT, and SAR.

Layers off by default (opt-in): MODIS Terra daily imagery, high-res satellite, Sentinel Hub, VIIRS nightlights, power plants, Shodan overlay, road freight trends, submarine cables, malware C2, SCM suppliers, and cyber threats.

Recon and entity tools are not map layers — they live in the left sidebar and on selection:

| Tool | Dashboard access | Agent command | Description |
|---|---|---|---|
| Recon Toolkit | Local operator (`/api/osint/*`) | `osint_lookup`, `osint_sweep`† | IP, DNS, WHOIS, certs, BGP, sanctions, CVE, MAC, GitHub, leaks, threats, subnet sweep |
| Entity Graph | Local operator (`/api/entity/expand`) | `entity_expand` | Wikidata + OFAC + live-store relationship graph |
| SCM Risk panel | Local operator (`/api/scm-suppliers`) | `get_layer_slice(["scm_suppliers"])` | Supplier threat rollup + map markers |
| Tool discovery | — | `osint_tools` | Lists recon lookup types and entity-expand schemas |

† `osint_sweep` (active InternetDB scan) requires `OPENCLAW_ACCESS_TIER=full`.

</details>

---

<details>
<summary>Environment variables</summary>

### Backend (`backend/.env`)

```env
# Required for airplane telemetry — startup env check flags these as critical
OPENSKY_CLIENT_ID=your_opensky_client_id      # OAuth2 — global flight state vectors
OPENSKY_CLIENT_SECRET=your_opensky_secret     # OAuth2 — paired with Client ID above

# Optional (enhances data quality)
AIS_API_KEY=your_aisstream_key                # Maritime vessel tracking — ships layer empty without it
LTA_ACCOUNT_KEY=your_lta_key                  # Singapore CCTV cameras
SHODAN_API_KEY=your_shodan_key                # Shodan device search overlay
SH_CLIENT_ID=your_sentinel_hub_id             # Copernicus CDSE Sentinel Hub imagery
SH_CLIENT_SECRET=your_sentinel_hub_secret     # Paired with Sentinel Hub Client ID
MESH_SAR_EARTHDATA_USER=                      # NASA Earthdata user (SAR Mode B — OPERA products)
MESH_SAR_EARTHDATA_TOKEN=                     # NASA Earthdata token (paired with user)
MESH_SAR_COPERNICUS_USER=                     # Copernicus Data Space user (SAR Mode B — EGMS / EMS)
MESH_SAR_COPERNICUS_TOKEN=                    # Copernicus token (paired with user)
OPENCLAW_ACCESS_TIER=restricted               # Agent tier: "restricted" (read-only) or "full"
# OPENCLAW_HMAC_SECRET=                        # Optional; UI Bootstrap persists to data/openclaw.env in Docker
GFW_API_TOKEN=your_gfw_token                  # Global Fishing Watch — fishing_activity layer
TELEGRAM_OSINT_ENABLED=true                   # Telegram OSINT layer (default on)
TELEGRAM_OSINT_CHANNELS=osintdefender,...     # Comma-separated public channel slugs

# Private-lane privacy-core pinning (required when Arti or RNS is enabled)
PRIVACY_CORE_MIN_VERSION=0.1.0
PRIVACY_CORE_ALLOWED_SHA256=your_privacy_core_sha256
# PRIVACY_CORE_LIB=                            # Optional override for a non-default shared library path
```

When `MESH_ARTI_ENABLED=true` or `MESH_RNS_ENABLED=true`, backend startup fails closed unless the loaded `privacy-core` artifact reports a version at or above `PRIVACY_CORE_MIN_VERSION` and matches one of the hashes in `PRIVACY_CORE_ALLOWED_SHA256`. Generate the hash with `sha256sum ./privacy-core/target/release/libprivacy_core.so` (or `Get-FileHash ...\privacy_core.dll -Algorithm SHA256` on Windows), then confirm authenticated `GET /api/wormhole/status` shows the same `privacy_core.version`, `privacy_core.library_path`, and `privacy_core.library_sha256`.

### Frontend

| Variable | Where to set | Purpose |
|---|---|---|
| `BACKEND_URL` | `environment` in `docker-compose.yml`, or shell env | URL the Next.js server uses to proxy API calls to the backend. Defaults to `http://backend:8000`. Runtime variable — no rebuild needed. |
| `BACKEND_PORT` | repo-root `.env` or shell env before `docker compose up` | Host port used to expose the backend API for local diagnostics. Defaults to `8000`; set `BACKEND_PORT=8001` if `8000` is already in use. Does not change the Docker-internal `BACKEND_URL`. |

**How it works:** the frontend proxies all `/api/*` requests through the Next.js server to `BACKEND_URL` using Docker's internal networking. Browsers only talk to port 3000; the backend host port is only for local diagnostics. For local dev without Docker, `BACKEND_URL` defaults to `http://localhost:8000`.

</details>

---

<details>
<summary>Architecture</summary>

VincentOS is composed of an intelligence platform and a decoupled AI brain:

- **Operator UI (Next.js + MapLibre GL)** — WebGL map render with clustering, the news/SIGINT feed, the Sovereign Shell governance panels, Mesh Chat and the Mesh Terminal, and the Time Machine snapshot transport that scrubs the whole telemetry feed. All API calls proxy through the Next.js server via `/api/[...path]` to `BACKEND_URL`.
- **Backend service plane (FastAPI)** — an APScheduler data fetcher on fast and slow tiers pulling every source (flights, ships, satellites, quakes, fires, CCTV, SAR, and more), a snapshot store feeding Time Machine, and the agentic AI channel (`POST /api/ai/channel/command` and `/batch`), HMAC-SHA256 signed and tier-gated (`restricted` read-only / `full` read+write+inject).
- **Decentralized layer (InfoNet testnet)** — a mesh hashchain of Ed25519-signed events with two-tier finality, the Sovereign Shell governance economy, and the Wormhole/InfoNet relay transport with gate personas and Dead Drop mailboxes.
- **Privacy core (Rust crate)** — Argon2id, Ed25519/X25519, AES-GCM, and HKDF today, with locked protocol contracts for ring signatures, stealth addresses, Pedersen commitments, and blind-signature issuance whose cryptographic primitive lands in a future sprint.
- **Vincent brain (Vincent OS, `:20128`)** — an OpenAI-compatible router (model `vincent`, zero-key) that consumes the platform as a tool API through the `vincent_os` OpenClaw skill. The brain is a separate process; the backend contains no LLM by design.

Distribution: images are published to GitHub Container Registry (`ghcr.io/bigbodycobain/vincent_os-{backend,frontend}`) with a GitLab mirror, multi-arch for `linux/amd64` and `linux/arm64` (Raspberry Pi 5 supported).

</details>

---

<details>
<summary>Project structure</summary>

```
Projeto_Vincent_OSINT/Vincent OS/
├── unified.sh                      # Vincent-native launcher — platform containers + Vincent OS brain
├── vincent/                        # Gitignored outward symlink index into the running Vincent pieces
├── openclaw-skills/vincent_os/   # OpenClaw skill Vincent drives the platform with (SKILL.md, sb_query.py, HMAC signer)
├── backend/
│   ├── main.py                     # FastAPI app, middleware, API routes
│   ├── config/news_feeds.json      # User-customizable RSS feed list
│   ├── services/
│   │   ├── data_fetcher.py         # Core scheduler — orchestrates all data sources
│   │   ├── ais_stream.py           # AIS WebSocket client
│   │   ├── carrier_tracker.py      # OSINT carrier position estimator (GDELT scraping)
│   │   ├── cctv_pipeline.py        # Multi-source CCTV ingestion pipeline
│   │   ├── ssrf_guard.py           # SSRF validation for operator recon fetches
│   │   ├── osint/                  # Server-side recon lookups + OpenClaw dispatch
│   │   ├── fetchers/               # flights, geo, satellites, earth observation, infrastructure, trains, sigint, news
│   │   └── mesh/                   # InfoNet / Wormhole protocol stack (crypto, hashchain, router, personas, Dead Drop)
│   └── routers/                    # /api/osint, /api/entity, /api/scm-suppliers, /api/malware, /api/cyber-threats, ...
├── frontend/
│   ├── public/data/submarine-cables.json
│   └── src/
│       ├── app/page.tsx            # Main dashboard — state, polling, layout
│       └── components/             # MaplibreViewer, MeshChat, MeshTerminal, NewsFeed, panels, TopRightControls (VINCENT button)
└── privacy-core/                   # Rust crate — locked protocol contracts
```

</details>

---

<details>
<summary>Performance</summary>

The platform is optimized for massive real-time datasets: gzip-compressed API payloads (~92%), ETag caching so `304 Not Modified` responses skip redundant JSON parsing, viewport culling of off-screen features, imperative map updates that bypass React reconciliation for high-volume layers, MapLibre clustering, debounced viewport updates (300ms general, 2s on dense layers), 10s position interpolation between refreshes, `React.memo` on heavy components, and 5-decimal coordinate rounding to shrink JSON size.

</details>

---

<details>
<summary>Contributors</summary>

VincentOS builds on an OSINT platform developed in the open. These people shipped real code on the base platform:

| Who | What | PR |
|-----|------|----|
| [@Alienmajik](https://gitlab.com/Alienmajik) | Raspberry Pi 5 support — ARM64 packaging, headless deployment, Pi-class runtime tuning | — |
| [@wa1id](https://github.com/wa1id) | CCTV ingestion fix — threaded SQLite, persistent DB, startup hydration, cluster clickability | #92 |
| [@AlborzNazari](https://github.com/AlborzNazari) | Spain DGT + Madrid CCTV sources, STIX 2.1 threat intel export | #91 |
| [@adust09](https://github.com/adust09) | Power plants layer, East Asia intel coverage (JSDF bases, ICAO enrichment, Taiwan news) | #71, #72, #76, #77, #87 |
| [@Xpirix](https://github.com/Xpirix) | LocateBar style and interaction improvements | #78 |
| [@imqdcr](https://github.com/imqdcr) | Ship toggle split + stable MMSI/callsign entity IDs | — |
| [@csysp](https://github.com/csysp) | Dismissible threat alerts + stable entity IDs for GDELT and News | #48, #63 |
| [@suranyami](https://github.com/suranyami) | Parallel multi-arch Docker builds + runtime `BACKEND_URL` fix | #35, #44 |
| [@chr0n1x](https://github.com/chr0n1x) | Kubernetes / Helm chart architecture for HA deployments | — |

</details>

---

## Disclaimer

This tool is built entirely on publicly available, open-source intelligence (OSINT) data. No classified, restricted, or non-public data is used. Carrier positions are estimates based on public reporting. The military-themed UI is purely aesthetic.

## License

This project is for educational and personal research purposes. See individual API provider terms of service for data usage restrictions.

