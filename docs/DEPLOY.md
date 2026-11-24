# Deploying Hami

Hami runs as one Docker Compose stack: the API (with the capture browser), the certificate-transparency discovery
worker, and optionally PostgreSQL and Caddy. The same `docker-compose.yml` runs on a laptop and on a server; only the
profiles and `.env` change.

| Where | Command |
|---|---|
| Laptop, SQLite (default) | `docker compose up` |
| Laptop, PostgreSQL | `docker compose --profile postgres up` |
| Server, PostgreSQL + HTTPS | `docker compose --profile postgres --profile https up -d` |

Nothing in this guide has been deployed by the team yet. The steps are written for an **Azure for Students** VM in
the **UAE North** region (Dubai), but any Linux VM with Docker works the same way.

## 0. A public URL from a Windows PC (Cloudflare quick tunnel)

The fastest way to give judges a live HTTPS address. It needs no account, no domain and no open ports: the PC makes
an outbound connection to Cloudflare.

```powershell
# 1. Once: install cloudflared (official package)
winget install --id Cloudflare.cloudflared -e
# 2. Start Hami (port 8000; add $env:HAMI_PORT="8080" first if 8000 is taken)
docker compose up -d --build
# 3. Start the tunnel and keep this window open. It prints https://<random-words>.trycloudflare.com
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://localhost:8000
```

Open the printed address. It shows the public check page; `/review` still asks for the reviewer token.

- **A quick-tunnel address changes every time cloudflared restarts.** Keep it running, and stop the PC from sleeping. In PowerShell as administrator: `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`. Keep Docker Desktop set to start with Windows; the containers restart on their own (`restart: unless-stopped`).
- For a permanent address, use a named tunnel with your own domain (`cloudflared tunnel login`, `create`, `route dns`, `run`) or the VM setup below.
- Public scans are limited per IP and for the whole server (`RATE_SCANS_PER_IP_PER_MIN`, `RATE_SCANS_GLOBAL_PER_MIN`). Each scan runs in the sandboxed capture browser on this PC, which never signs in, submits forms or reaches private-network addresses.

## 1. Moving existing data to PostgreSQL (any machine)

If you already ran Hami on SQLite and want to keep the data:

```bash
docker compose --profile postgres run --rm api python -m app.db.transfer   # copy SQLite -> PostgreSQL, verify counts
docker compose --profile postgres up -d                                     # from now on the stack uses PostgreSQL
```

The transfer creates the schema, copies every table with its IDs, moves the ID sequences past the copied rows and
prints a table of row counts and highest IDs per table. It refuses to write into a database that already has data
(other than the seed indicators loaded on first start). Without Docker:
`python tasks.py migrate-to-postgres --to postgresql+psycopg://user:pw@host:5432/hami`.

Artifacts (sanitized HARs, screenshots) stay in the `hami-data` volume; the database stores only their
content-addressed keys and SHA-256 hashes. An S3-compatible store is the next `ArtifactStore` (docs/architecture.md).

## 2. Create the VM (Azure for Students, UAE North)

1. Sign in at portal.azure.com with the student subscription.
2. **Create a virtual machine**:
   - Region: **UAE North**.
   - Image: **Ubuntu Server 24.04 LTS** (x64).
   - Size: 2 vCPU / 4 GiB RAM or more (for example a B-series `Standard_B2s`). Chromium captures need the memory. If a size is not offered to the subscription in UAE North, pick the nearest B-series size.
   - Authentication: **SSH public key** (no password).
   - Inbound ports: **SSH (22), HTTP (80), HTTPS (443)**. Nothing else; port 8000 stays closed.
   - Disk: 32 GiB Standard SSD or more.
3. After creation, open the VM's **Public IP address → Configuration** and set a **DNS name label**, e.g. `hami-demo`.
   The VM is then reachable as `hami-demo.uaenorth.cloudapp.azure.com`. Caddy can get a certificate for that name.
   A custom domain works too: point an A record at the public IP.
4. Restrict SSH in the network security group to your own IP if you can.

Check the Azure pricing calculator for the VM size you choose. Stop (deallocate) the VM when it is not needed so it
does not use credit.

## 3. Install Docker on the VM

```bash
ssh azureuser@hami-demo.uaenorth.cloudapp.azure.com
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get -y install ca-certificates curl git unattended-upgrades
curl -fsSL https://get.docker.com | sudo sh          # Docker Engine + compose plugin (official script)
sudo usermod -aG docker $USER && exit                # log in again so the group applies
```

Limit Docker's log size (`/etc/docker/daemon.json`), then `sudo systemctl restart docker`:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
```

## 4. Configure and start Hami

```bash
git clone https://github.com/<team>/hami.git && cd hami
cp .env.example .env
```

Edit `.env`:

```bash
HAMI_REVIEWER_TOKEN=<long random value>      # python3 -c "import secrets; print(secrets.token_urlsafe(32))"
POSTGRES_PASSWORD=<another long random value>
HAMI_DOMAIN=hami-demo.uaenorth.cloudapp.azure.com
DATABASE_URL=                                # leave empty: the postgres profile sets it
```

Set `POSTGRES_PASSWORD` **before the first start**: PostgreSQL stores it when its volume is created. Use URL-safe
characters (the `token_urlsafe` output above is fine), because it becomes part of the connection URL.

Start everything:

```bash
docker compose --profile postgres --profile https up -d --build
docker compose ps                            # api healthy, discovery, postgres healthy, caddy running
curl https://hami-demo.uaenorth.cloudapp.azure.com/health
```

On the first start, Caddy obtains a Let's Encrypt certificate (ports 80 and 443 must be open), the API seeds the
committed model and the team's seed indicators, and applies the migrations. The API container listens only on the
Docker network and on `127.0.0.1:8000`, so everything public goes through Caddy.

Then:
- Reviewer console: `https://<domain>/review` (token from `.env`).
- Chrome extension: **Options → Server URL** → `https://<domain>`. To make it the default for everyone, set `DEFAULT_API_BASE` in `clients/shared/src/config.ts` and rebuild (`python tasks.py extension`).

## 5. Updating

```bash
cd hami
git pull
docker compose --profile postgres --profile https up -d --build
```

Migrations run automatically on start. New model versions shipped in the image are added to the volume. The
current model only changes through the promotion rule after a training run (console → Training) or a recorded
manual override: `docker compose exec api python -m ml.promote <version> --reason "..." --reviewer <name>`. Seed indicators are loaded idempotently, so a new `data/seed/indicators.json` adds only new cases.

## 6. Backups

Database (daily, keep 14 days):

```bash
mkdir -p ~/backups
docker compose exec -T postgres pg_dump -U hami -Fc hami > ~/backups/hami-$(date +%F).dump
find ~/backups -name 'hami-*.dump' -mtime +14 -delete
```

Artifacts and models (the `hami-data` volume; the prefix is the project folder name, `hami` here):

```bash
docker run --rm -v hami_hami-data:/data:ro -v ~/backups:/b alpine tar czf /b/hami-data-$(date +%F).tgz -C / data
```

Put both in `crontab -e`, e.g. `30 2 * * * cd ~/hami && <commands above>`. Copy backups off the VM (for example
`az storage blob upload` to a private storage account, or `scp`). An Azure disk snapshot of the VM is a useful extra.

Restore:

```bash
docker compose --profile postgres up -d postgres
docker compose exec -T postgres pg_restore -U hami -d hami --clean --if-exists < ~/backups/hami-YYYY-MM-DD.dump
docker run --rm -v hami_hami-data:/data -v ~/backups:/b alpine sh -c "cd / && tar xzf /b/hami-data-YYYY-MM-DD.tgz"
docker compose --profile postgres --profile https up -d
```

## 7. Logs and health

```bash
docker compose logs -f api            # API, captures, scoring
docker compose logs -f discovery      # certificate-transparency matches and safe captures
docker compose logs -f caddy          # HTTPS, certificate renewals, access log
docker compose ps                     # health status
curl -s https://<domain>/health       # {"status":"ok","model_version":...,"scans":...}
```

Scan durations and capture errors are also visible per case in the reviewer console.

## 8. Security checklist

- SSH key only. Inbound ports 22/80/443 only, with SSH limited to known IPs where possible. `unattended-upgrades` on.
- Long random `HAMI_REVIEWER_TOKEN` and `POSTGRES_PASSWORD`. `.env` is never committed.
- PostgreSQL is not published on any port. The API is reachable only through Caddy.
- The capture browser runs inside the container as a non-root user. It never signs in, submits forms, pays, downloads or follows discovered links. The discovery worker is rate-limited (`DISCOVERY_*` in `.env`).
- Rate limits per device and IP are on by default (`RATE_*` in `.env`). Uvicorn trusts `X-Forwarded-For` from Caddy for these.
- Back up before every update. Test a restore at least once.
