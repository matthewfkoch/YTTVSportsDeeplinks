# YTTV Sports Deeplinks

YouTube TV sports guide with a watch link per game. Sign in once in the container browser, then use XMLTV / M3U / APITuner lanes.

This is not YouTube on TV (`youtube.com/tv`). It is not part of APITuner.

The Compose project, image, container, and volume are `yttvsportsdeeplinks` / `yttvsportsdeeplinks-data`. If you already had a login in `yttv-espn-plus-data`, copy that volume before the first start or you will sign in again.

## Sign in

Google blocks third-party YouTube TV OAuth, so the container runs Chromium on a virtual display (Xvfb). You sign in once in that window.

1. `docker compose up -d --build`
2. Open `http://<host>:8095`
3. In the login desktop, sign in to [tv.youtube.com](https://tv.youtube.com) with the Google account that owns YouTube TV (account picker and 2FA stay in Google)
4. The dashboard saves the session when it sees a YouTube TV login. The Chromium profile lives in the `yttvsportsdeeplinks-data` volume and is reused after restarts

The desktop is also at `http://<host>:7900`. Do not expose port 7900 to the internet; it is a full browser session.

Cookie paste remains available as a fallback. This service does not store your Google password.

## Run

```bash
cp .env.example .env
docker compose up -d --build
```

Set `PUBLIC_BASE_URL` if APITuner should always use a fixed host, for example `http://192.168.1.10:8095` or `http://yttvsportsdeeplinks:8095` on a shared Docker network. If you leave it as localhost, the dashboard, M3U, and export use the address you opened the page with.

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
| `/playlist.m3u` | Virtual lanes (`YTTV Sports 1` …) |
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
| `REFRESH_SECONDS` | How often to refresh ESPN labels and resolve missing watch links (default 60). If this is the only interval you set, full mines still use `FULL_MINE_SECONDS`. |
| `FULL_MINE_SECONDS` | How often to re-mine the YouTube TV guide (default 300). Manual Refresh always does a full mine. |
| `MINE_CONCURRENCY` | Max parallel InnerTube hub/resolve requests (default 4). Continuation pages stay serial. |
| `ENABLE_CHROME` | Run in-container Chromium (default `1`) |
| `NOVNC_PUBLIC_URL` | Override the login-desktop iframe URL |
| `ADMIN_USER` / `ADMIN_PASSWORD` | HTTP basic auth on the dashboard only |
| `TZ` | Time zone for the dashboard (default `America/New_York`) |
