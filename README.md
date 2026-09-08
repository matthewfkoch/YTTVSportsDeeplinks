# YTTV Sports Deeplinks

YouTube TV sports guide with a watch link per game. Sign in once in the container browser, then use XMLTV / M3U / APITuner lanes.

This is not YouTube on TV (`youtube.com/tv`). It is not part of APITuner.

The Compose service and volume stay `yttv-espn-plus` so an existing login is reused.

## Sign in

Google blocks third-party YouTube TV OAuth, so the container runs Chromium on a virtual display (Xvfb). You sign in once in that window.

1. `docker compose up -d --build`
2. Open `http://<host>:8095`
3. In the login desktop, sign in to [tv.youtube.com](https://tv.youtube.com) with the Google account that owns YouTube TV (account picker and 2FA stay in Google)
4. The dashboard saves the session when it sees a YouTube TV login. The Chromium profile lives in the `yttv-espn-plus-data` volume and is reused after restarts

The desktop is also at `http://<host>:7900`. Do not expose port 7900 to the internet; it is a full browser session.

Cookie paste remains available as a fallback. This service does not store your Google password.

## Run

```bash
cd ~/Documents/GitHub/yttv-epg
cp .env.example .env
docker compose up -d --build
```

Set `PUBLIC_BASE_URL` if APITuner should always use a fixed host, for example `http://192.168.1.10:8095` or `http://yttv-espn-plus:8095` on a shared Docker network. If you leave it as localhost, the dashboard, M3U, and export use the address you opened the page with.

## Feeds

| URL | Use |
| --- | --- |
| `/xmltv.xml` | Sports guide (filtered). This is the Channels DVR XMLTV URL. |
| `/playlist.m3u` | Virtual lanes (`YTTV Sports 1` …) |
| `/whatson/{n}` | Current event deeplink (`https://tv.youtube.com/watch/...`) |
| `/api/export` | APITuner channel JSON |
| `/events` | Raw sports event list |

Lane URLs:

```
http://<yttv-espn-plus>:8095/whatson/1?format=json&include=deeplink&dynamic_url_json_key=deeplink_url
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
| `REFRESH_SECONDS` | How often to re-mine the guide and refresh Chromium cookies |
| `ENABLE_CHROME` | Run in-container Chromium (default `1`) |
| `NOVNC_PUBLIC_URL` | Override the login-desktop iframe URL |
| `ADMIN_USER` / `ADMIN_PASSWORD` | HTTP basic auth on the dashboard only |
| `TZ` | Time zone for the dashboard (default `America/New_York`) |
