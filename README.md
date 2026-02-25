# Henrik's Lab

A self-hosted personal dashboard and knowledge management system running on a Raspberry Pi. All services are containerised with Docker Compose and exposed securely to the internet via a Cloudflare Tunnel — no open ports required.

Live at **[home.rexthedog.space](https://home.rexthedog.space)**

---

## Architecture overview

```
Internet
  └─ Cloudflare Tunnel (cloudflared)
       └─ All traffic → localhost only
            │
            ├─ home.rexthedog.space        → Homepage (8080)
            ├─ notes.rexthedog.space       → Outline wiki (3000)
            ├─ brain.rexthedog.space       → Brain / AI ingestor (8085)
            ├─ recipes.rexthedog.space     → Receptbok (8084)
            ├─ vault.rexthedog.space       → Vaultwarden (8082)
            ├─ status.rexthedog.space      → Uptime Kuma (3001)
            ├─ portainer.rexthedog.space   → Portainer (9000)
            ├─ terminal.rexthedog.space    → Wetty / Web SSH (3002)
            ├─ files.rexthedog.space       → FileBrowser (8083)
            └─ ssh.rexthedog.space         → SSH (22)
```

No nginx or reverse proxy runs on the host. The Cloudflare Tunnel daemon handles TLS termination and routing entirely.

---

## Services

| Service | Image / Source | Port | Purpose |
|---|---|---|---|
| **Homepage** | `ghcr.io/gethomepage/homepage` | 8080 | Central dashboard |
| **Outline** | `outlinewiki/outline` | 3000 | Wiki & knowledge base |
| **Brain** | `./brain` (custom) | 8085 | AI content ingestor |
| **Receptbok** | `./recipes` (custom) | 8084 | Swedish recipe manager |
| **Vaultwarden** | `vaultwarden/server` | 8082 | Password manager (Bitwarden-compatible) |
| **Uptime Kuma** | `louislam/uptime-kuma` | 3001 | Service health monitoring |
| **Portainer** | `portainer/portainer-ce` | 9000 | Docker container management |
| **Wetty** | `wettyoss/wetty` | 3002 | SSH terminal in the browser |
| **FileBrowser** | `filebrowser/filebrowser` | 8083 | Web-based file manager |
| **PostgreSQL** | `postgres:16-alpine` | internal | Outline database |
| **Redis** | `redis:7-alpine` | internal | Outline session cache |
| **MinIO** | `minio/minio` | internal | S3-compatible file storage for Outline |

---

## Custom services

### Brain (`./brain`)

An AI-powered content ingestion pipeline. Drop in anything — a URL, a YouTube link, a PDF, an image, or raw text — and it extracts, distils, and organises it into your Outline wiki automatically.

**How it works:**

1. **Extract** — handles URLs (web scraping), YouTube (transcript via `yt-dlp`), PDFs (`pypdf`), images (Claude OCR), and plain text
2. **Chunk** — splits large documents into 150 KB sections with 3 KB overlap
3. **Summarise** — for multi-chunk documents, each section is summarised first
4. **Distil** — Claude Opus 4.6 produces structured JSON: title, topic, tier (A/B/C quality), TL;DR, key points, and clean markdown
5. **Publish** — two documents are created in Outline:
   - `📥 Inbox` — raw import for reference
   - `📚 Library` — cleaned, structured content filed under the correct topic

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard showing recent jobs |
| `POST` | `/ingest` | Submit content (text, URL, or file upload) |
| `GET` | `/job/{id}` | Live job progress page |
| `GET` | `/api/job/{id}` | Job status as JSON |

**Environment variables:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OUTLINE_URL` | Internal Outline URL (e.g. `http://outline:3000`) |
| `OUTLINE_TOKEN` | Outline API token (create under Settings → API) |

---

### Receptbok (`./recipes`)

A personal recipe database with AI-powered import. Paste a recipe URL or photograph a recipe card, and Claude extracts it into structured form ready to review and save.

The entire UI is in Swedish. Categories use Swedish cooking terminology (Frukost, Middag, Bakning, etc.) and units match Swedish kitchen standards (krm, tsk, msk, dl).

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Browse and search recipes |
| `GET/POST` | `/new` | Create recipe manually |
| `GET/POST` | `/edit/{id}` | Edit a recipe |
| `GET/POST` | `/ingest` | Import from URL or image via Claude |
| `GET/POST` | `/delete/{id}` | Delete a recipe |

**Environment variables:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |

---

## Authentication

**Outline** uses Cloudflare Access as an OIDC provider, so login is handled by Cloudflare Zero Trust. No separate user accounts needed — access is granted or denied at the Cloudflare level before a request ever reaches the server.

---

## Setup

### Prerequisites

- Raspberry Pi (or any Linux machine) with Docker and Docker Compose installed
- A domain with Cloudflare DNS
- An Anthropic API key
- A Cloudflare account with Zero Trust enabled (free tier works)

### 1. Clone the repo

```bash
git clone https://github.com/rexade/henrik-lab.git
cd henrik-lab
```

### 2. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in all values
nano .env
```

Generate the Outline secret keys:

```bash
openssl rand -hex 32   # run twice — once for SECRET_KEY, once for UTILS_SECRET
```

### 3. Set up Cloudflare Tunnel

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Authenticate and create a tunnel
cloudflared tunnel login
cloudflared tunnel create henrik-lab

# Copy and edit the tunnel config
mkdir -p ~/.cloudflared
cp cloudflare/config.yml.example ~/.cloudflared/config.yml
# Edit config.yml — replace YOUR_TUNNEL_ID and your domain

# Create DNS records (one per subdomain)
cloudflared tunnel route dns henrik-lab home.yourdomain.com
cloudflared tunnel route dns henrik-lab notes.yourdomain.com
# ... repeat for each subdomain

# Install as a system service
sudo cloudflared service install
sudo systemctl start cloudflared
```

### 4. Start everything

```bash
docker compose up -d
```

### 5. First-run Outline setup

After the stack is up, get your Outline API token:

1. Go to `https://notes.yourdomain.com`
2. Sign in via Cloudflare
3. Go to **Settings → API → Create token**
4. Copy the token into your `.env` as `OUTLINE_TOKEN`
5. Restart the brain service: `docker compose restart brain`

---

## Directory structure

```
henrik-lab/
├── docker-compose.yml          # Full stack definition (secrets via .env)
├── .env.example                # Template for secrets — copy to .env
├── .gitignore
│
├── brain/                      # AI content ingestor
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app + job queue
│   ├── pipeline.py             # Extraction → chunking → distillation → publish
│   ├── outline_client.py       # Outline REST API client
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS
│
├── recipes/                    # Swedish recipe manager
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app (CRUD + AI import)
│   ├── templates/
│   └── static/
│
├── homepage/
│   └── config/
│       ├── settings.yaml       # Dashboard theme and layout
│       ├── services.yaml       # Service links and monitoring
│       ├── widgets.yaml        # Widgets (clock, resources, search)
│       └── bookmarks.yaml      # Quick-access bookmarks
│
└── cloudflare/
    └── config.yml.example      # Cloudflare Tunnel config template
```

---

## Useful commands

```bash
# View all running containers
docker compose ps

# Follow logs for a specific service
docker compose logs -f brain

# Rebuild and restart a custom service after code changes
docker compose up -d --build brain
docker compose up -d --build recipes

# Stop everything
docker compose down

# Stop everything and remove volumes (destructive — loses all data)
docker compose down -v
```

---

## Tech stack

- **Runtime:** Docker Compose on Raspberry Pi (ARM64)
- **Networking:** Cloudflare Tunnel (zero open ports)
- **Auth:** Cloudflare Access (OIDC)
- **Custom services:** Python 3.12, FastAPI, Uvicorn
- **AI:** Anthropic Claude Opus 4.6 (multi-modal)
- **Database:** PostgreSQL 16
- **Cache:** Redis 7
- **Object storage:** MinIO (S3-compatible)
