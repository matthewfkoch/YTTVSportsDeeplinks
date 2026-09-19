# YTTV Sports Deeplinks

YouTube TV sports guide with a watch link per game. Sign in once in the container browser, then use XMLTV / M3U / APITuner lanes.

This is an unofficial, self-hosted tool. It is not affiliated with YouTube, Google, ESPN, or APITuner, and it is not YouTube on TV (`youtube.com/tv`). Google can change or block the in-container session at any time.

Keep this on your LAN. The dashboard, XMLTV, M3U, and watch-link resolver listen on port 8095. Port 7900 is an unauthenticated login desktop (noVNC); do not publish it to the internet.

The Compose project, image, container, and volume are `yttvsportsdeeplinks` / `yttvsportsdeeplinks-data`. If you already had a login in `yttv-espn-plus-data`, copy that volume before the first start or you will sign in again.

## Run

### From GitHub Container Registry (releases)

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

Or without Compose:

```bash
docker run -d \
  --name yttvsportsdeeplinks \
  -p 8095:8095 \
  -p 7900:7900 \
  --shm-size=1gb \
  -v yttvsportsdeeplinks-data:/data \
  --restart unless-stopped \
  ghcr.io/matthewfkoch/yttvsportsdeeplinks:latest
```

`docker compose up -d` pulls `ghcr.io/matthewfkoch/yttvsportsdeeplinks:latest` by default.

### Build locally

```bash
cp .env.example .env
docker compose up -d --build
```

Set `PUBLIC_BASE_URL` if APITuner should always use a fixed host, for example `http://192.168.1.10:8095` or `http://yttvsportsdeeplinks:8095` on a shared Docker network. If you leave it as localhost, the dashboard, M3U, and export use the address you opened the page with.

## Sign in

Use a **dedicated YouTube TV Google account** for this container. Do not sign in with the account you use for Gmail, Drive, Photos, or other personal Google services. Google still shows a normal account picker; this app cannot issue a YouTube-only token.

Google blocks third-party YouTube TV OAuth, so the container runs Chromium on a virtual display (Xvfb). You sign in once in that window.

1. Start the container (`docker compose up -d` for a release image, or `--build` for local source)
2. Open `http://<host>:8095`
3. In the login desktop, sign in to [tv.youtube.com](https://tv.youtube.com) with that dedicated YouTube TV account (account picker and 2FA stay in Google)
4. The dashboard saves the session when it sees a YouTube TV login. The Chromium profile lives in the `yttvsportsdeeplinks-data` volume and is reused after restarts

The desktop is also at `http://<host>:7900`. Do not expose port 7900 to the internet.

The encrypted app session keeps only YouTube cookies. Chromium keeps the Google cookies needed to stay signed in, but browser Google sign-in and device-bound sessions are disabled so Chromium does not take over or delete that login. A dedicated YouTube TV account is still strongly recommended.

Cookie paste remains available as a fallback. This service does not store your Google password.

To keep an existing YouTube TV login when renaming from `yttv-espn-plus`:

```bash
docker volume create yttvsportsdeeplinks-data
docker run --rm -v yttv-epg_yttv-espn-plus-data:/from -v yttvsportsdeeplinks-data:/to alpine cp -a /from/. /to/
```

If `docker volume ls` shows a different old name, use that as `/from`.

## Feeds

| URL | Use |
| --- | --- |
| `/xmltv.xml` | Sports guide (filtered). This is the Channels DVR XMLTV URL. Channel icons use `/static/logo.png`. |
| `/playlist.m3u` | Virtual lanes (`YTTV Sports 1` …). `tvg-id` / `channel-id` match XMLTV channel ids; `url-tvg` points at `/xmltv.xml`. |
| `/whatson/{n}` | Current event deeplink (`https://tv.youtube.com/watch/...`) |
| `/api/export` | APITuner channel JSON |
| `/events` | Raw sports event list |

Lane URLs:

```
http://<yttvsportsdeeplinks>:8095/whatson/1?format=json&include=deeplink&dynamic_url_json_key=deeplink_url
```

Upcoming events often have no watch ID until they are close to air. Those stay out of the EPG, lanes, and XMLTV until a `tv.youtube.com/watch/…` link exists.

## Optional env

| Variable | Purpose |
| --- | --- |
| `YTTV_EPG_SECRET` | Encrypts the session file. If unset, a key is created in the volume. |
| `PUBLIC_BASE_URL` | Host written into M3U / APITuner export. Loopback defaults follow the request host. |
| `LANE_COUNT` | Virtual channels (default 128). Raise this if overlapping events are dropped. |
| `START_CHANNEL` | First export number (default 9100) |
| `HIDDEN_SPORTS` | Comma-separated sports to hide on first run (`Volleyball,Field Hockey`) |
| `HIDDEN_CHANNELS` | Comma-separated channel families to hide on first run (`ESPN+,NBC Sports Extra`) |
| `MAX_HUBS` | How many sports network hubs to mine (default 16) |
| `EPG_PAGES` / `HUB_PAGES` | How far to paginate the linear grid and hub schedules |
| `REFRESH_SECONDS` | How often to refresh ESPN labels and resolve missing watch links (default 60). Compose passes this into the container. |
| `FULL_MINE_SECONDS` | How often to re-mine the YouTube TV guide (default 300). Manual Refresh always does a full mine. |
| `MINE_CONCURRENCY` | Max parallel InnerTube hub/resolve requests (default 4). Continuation pages stay serial. |
| `ENABLE_CHROME` | Run in-container Chromium (default `1`) |
| `NOVNC_PUBLIC_URL` | Override the login-desktop iframe URL |
| `ADMIN_USER` / `ADMIN_PASSWORD` | HTTP basic auth on the dashboard only |
| `TZ` | Time zone for the dashboard (default `America/New_York`) |

## Releases

Pushes and pull requests run `.github/workflows/ci.yml` (syntax check, pytest, Docker build). Tagged releases (`v*`) trigger `.github/workflows/release.yml`, which:

1. Runs the same tests, then publishes a multi-arch image (`linux/amd64` + `linux/arm64`) to GitHub Container Registry: `ghcr.io/matthewfkoch/yttvsportsdeeplinks:<version>` and `:latest`
2. Creates a GitHub Release with pull instructions

If the package is still private (the default when the repo started private), open **Packages → yttvsportsdeeplinks → Package settings**, link it to this repo, and set visibility to **Public** so `docker pull` works without a GitHub login.

To cut a release, bump `src/yttv_epg/__init__.py` and `pyproject.toml`, then:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

A manual run of the Release workflow (no tag) publishes `:dev` only. Do not retag a version that already shipped.

## License

Apache License 2.0. See [LICENSE](LICENSE).
