# Henrik's Lab

A self-hosted personal dashboard running on a Raspberry Pi. All services are containerised with Docker Compose and exposed securely via a Cloudflare Tunnel — no open ports required.

<img width="2412" height="1092" alt="image" src="https://github.com/user-attachments/assets/754b6ae8-a11d-4b39-9787-ad7ed94c2844" />

Live at **[home.rexthedog.space](https://home.rexthedog.space)**

---

## Architecture

```
Internet
  └─ Cloudflare Tunnel (cloudflared)
       └─ All traffic → localhost only
            │
            ├─ home.rexthedog.space    → Homepage     (8080)
            ├─ notes.rexthedog.space   → Outline wiki (3000)
            ├─ brain.rexthedog.space   → Brain        (8085)
            ├─ recipes.rexthedog.space → Receptbok    (8084)
            ├─ kanban.rexthedog.space  → Kanban       (8086)
            ├─ anime.rexthedog.space   → Anime        (8087)
            ├─ status.rexthedog.space  → Uptime Kuma  (3001)
            ├─ files.rexthedog.space   → FileBrowser  (8083)
            └─ ssh.rexthedog.space     → SSH browser  (22)
```

No reverse proxy on the host. Cloudflare Tunnel handles TLS termination and routing entirely.

---

## Services

| Service | Image / Source | Port | Purpose |
|---|---|---|---|
| **Homepage** | `ghcr.io/gethomepage/homepage` | 8080 | Central dashboard |
| **Outline** | `outlinewiki/outline` | 3000 | Wiki & knowledge base |
| **Brain** | `./brain` (custom) | 8085 | AI content ingestor → Outline |
| **Receptbok** | `./recipes` (custom) | 8084 | Swedish recipe manager with AI import |
| **Kanban** | `./kanban` (custom) | 8086 | Personal task board |
| **Anime** | `./anime` (custom) | 8087 | Anime watchlist tracker (AniList) |
| **Uptime Kuma** | `louislam/uptime-kuma` | 3001 | Service health monitoring |
| **FileBrowser** | `./filebrowser` (custom) | 8083 | Web-based file manager |
| **PostgreSQL** | `postgres:16-alpine` | internal | Outline database |
| **Redis** | `redis:7-alpine` | internal | Outline session cache |
| **MinIO** | `minio/minio` | internal | S3-compatible file storage for Outline |

---

## Custom services

### Brain (`./brain`)

Paste a URL, YouTube link, PDF, image, or raw text — Brain extracts, distils, and files it into your Outline wiki automatically.

**Pipeline:**

1. **Extract** — URLs (scraping), YouTube (transcript via `yt-dlp`), PDFs (`pypdf`), images (Claude vision), plain text
2. **Chunk** — splits large content into 150 KB sections with 3 KB overlap
3. **Summarise** — each chunk is summarised individually for long documents
4. **Distil** — Claude Opus 4.6 produces structured JSON: title, topic, tier (A/B/C), TL;DR, key points, clean markdown
5. **Publish** — two documents created in Outline:
   - `📥 Inbox` — raw import for reference
   - `📚 Library` — clean structured note, filed under the correct topic collection

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard with recent jobs |
| `POST` | `/ingest` | Submit a URL, text, or file |
| `GET` | `/job/{id}` | Live job progress page |
| `GET` | `/api/job/{id}` | Job status as JSON |

**Environment variables:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OUTLINE_URL` | Internal Outline URL (`http://outline:3000`) |
| `OUTLINE_TOKEN` | Outline API token (Settings → API → Create token) |

---

### Receptbok (`./recipes`)

Recipe database with AI-powered import. Paste a URL or photograph a recipe card and Claude extracts it into structured form.

The UI is in Swedish. Categories and units follow Swedish kitchen conventions (krm, tsk, msk, dl, etc.).

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Browse and search recipes |
| `GET/POST` | `/new` | Create a recipe manually |
| `GET/POST` | `/edit/{id}` | Edit a recipe |
| `GET/POST` | `/ingest` | Import from URL or image via Claude |
| `GET/POST` | `/delete/{id}` | Delete a recipe |

**Environment variables:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |

---

### Kanban (`./kanban`)

Minimal personal task board. Four fixed columns: **Backlog → Next → Doing → Done**. Cards have a title and optional description. Data stored in SQLite.

No environment variables required.

---

### Anime (`./anime`)

Watchlist tracker backed by the [AniList](https://anilist.co) public GraphQL API. Search for shows, follow them, and see which episodes are airing. Follows stored locally in JSON.

No environment variables required.

---

## Authentication

Outline uses Cloudflare Access as an OIDC provider. Login is handled by Cloudflare Zero Trust — no separate user accounts needed.

---

## Setup

### Prerequisites

- Raspberry Pi (or any Linux box) with Docker and Docker Compose
- A domain on Cloudflare DNS
- An Anthropic API key
- A Cloudflare account with Zero Trust enabled (free tier works)

### 1. Clone

```bash
git clone https://github.com/rexade/henrik-lab.git
cd henrik-lab
```

### 2. Configure secrets

```bash
cp outline/.env.example outline/.env
# Fill in all values
nano outline/.env
```

Generate the Outline secret keys:

```bash
openssl rand -hex 32   # run twice: once for SECRET_KEY, once for UTILS_SECRET
```

### 3. Set up Cloudflare Tunnel

```bash
# Install cloudflared (ARM64)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Authenticate and create a tunnel
cloudflared tunnel login
cloudflared tunnel create henrik-lab

# Configure the tunnel — edit with your tunnel ID and domain
mkdir -p ~/.cloudflared
nano ~/.cloudflared/config.yml

# Add a DNS record for each subdomain
cloudflared tunnel route dns henrik-lab home.yourdomain.com
cloudflared tunnel route dns henrik-lab notes.yourdomain.com
cloudflared tunnel route dns henrik-lab brain.yourdomain.com
# ... repeat for each service

# Run as a system service
sudo cloudflared service install
sudo systemctl start cloudflared
```

### 4. Start the stack

```bash
cd outline
docker compose up -d
```

### 5. First-run: get the Outline API token

Brain needs an Outline API token to publish notes:

1. Go to `https://notes.yourdomain.com` and sign in
2. **Settings → API → Create token**
3. Add it to `outline/.env` as `OUTLINE_TOKEN`
4. `docker compose restart brain`

---

## Repo structure

```
henrik-lab/
├── outline/
│   ├── docker-compose.yml      # Full stack (secrets loaded from .env)
│   ├── .env.example            # Secret template — copy to .env
│   └── homepage/config/        # Homepage dashboard config (YAML)
│
├── brain/                      # AI content ingestor
│   ├── main.py                 # FastAPI app + async job queue
│   ├── pipeline.py             # Extract → chunk → summarise → distil → publish
│   └── outline_client.py       # Outline REST API client
│
├── recipes/                    # Swedish recipe manager
│   └── main.py                 # FastAPI CRUD + AI import
│
├── kanban/                     # Task board
│   └── main.py                 # FastAPI + SQLite
│
├── anime/                      # Anime tracker
│   └── main.py                 # FastAPI + AniList GraphQL
│
└── filebrowser/                # FileBrowser with nginx proxy
    ├── Dockerfile
    └── nginx.conf
```

---

## Useful commands

```bash
# Run from the outline/ directory

# View running containers
docker compose ps

# Stream logs for a service
docker compose logs -f brain

# Rebuild a custom service after code changes
docker compose up -d --build brain

# Restart a service
docker compose restart recipes
```

---

## Tech stack

- **Runtime:** Docker Compose on Raspberry Pi (ARM64)
- **Networking:** Cloudflare Tunnel (zero open ports)
- **Auth:** Cloudflare Access (OIDC) for Outline
- **Custom services:** Python 3.12 · FastAPI · Uvicorn · Jinja2
- **AI:** Anthropic Claude Opus 4.6 (multi-modal)
- **Database:** PostgreSQL 16 · SQLite (kanban, anime)
- **Cache:** Redis 7
- **Object storage:** MinIO (S3-compatible)
