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
  --pull always \
  --name yttvsportsdeeplinks \
  -p 8095:8095 \
  -p 7900:7900 \
  --shm-size=1gb \
  -v yttvsportsdeeplinks-data:/data \
  --restart unless-stopped \
  ghcr.io/matthewfkoch/yttvsportsdeeplinks:latest
```

`docker compose up -d` pulls `ghcr.io/matthewfkoch/yttvsportsdeeplinks:latest` before it starts. `docker run` needs `--pull always`, or an image already on disk is reused.

### Build locally

```bash
cp .env.example .env
docker compose up -d --build --pull never
```

Set `PUBLIC_BASE_URL` if APITuner should always use a fixed host, for example `http://192.168.1.10:8095` or `http://yttvsportsdeeplinks:8095` on a shared Docker network. If you leave it as localhost, the dashboard, M3U, and export use the address you opened the page with.

## Sign in

Use a **dedicated YouTube TV Google account** for this container. Do not sign in with the account you use for Gmail, Drive, Photos, or other personal Google services. Google still shows a normal account picker; this app cannot issue a YouTube-only token.

Google blocks third-party YouTube TV OAuth, so the container runs Chromium on a virtual display (Xvfb). You sign in once in that window.

1. Start the container (`docker compose pull && docker compose up -d` for a release image, or `docker compose up -d --build --pull never` for local source)
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
| `/xmltv.xml` | Sports guide (filtered). This is the Channels DVR XMLTV URL. Channel icons follow the lane broadcaster, with `/static/logo.png` as fallback. |
| `/playlist.m3u` | Virtual lanes (`YTTV Sports 1` …). `tvg-id` / `channel-id` match XMLTV channel ids; `url-tvg` points at `/xmltv.xml`. |
| `/whatson/{n}` | Current event deeplink (`https://tv.youtube.com/watch/...`) |
| `/api/export` | APITuner channel JSON |
| `/events` | Raw sports event list |

Lane URLs:

```
http://<yttvsportsdeeplinks>:8095/whatson/1?format=json&include=deeplink&dynamic_url_json_key=deeplink_url
```

Upcoming events often get a watch ID close to airtime. A virtual lane and its
XMLTV programme require both a watch link and a scheduled start. Date-only
listings appear as **Time TBD** in the dashboard until a matching schedule
supplies a start. When only the end is missing, the guide uses an estimated duration.
After upgrading, the app shows old catalog times as **Time TBD** and leaves those
programmes out of XMLTV until a full guide refresh succeeds.

### APITuner with Channels DVR

1. Download `http://<sports-host>:8095/api/export` and import that JSON on
   APITuner's **Channels** page. Use a sports app address that APITuner can
   reach. Set `PUBLIC_BASE_URL` before exporting if the dashboard address
   differs from the address APITuner should use.
2. In Channels DVR, add a **Custom Channels** source using **MPEG-TS** and this
   M3U URL from APITuner. If you renamed the provider, use its URL-encoded name.

   ```text
   http://<apituner-host>:6592/channels.m3u?provider=youtube_tv
   ```

3. In the same source, set **XMLTV Guide Data** to
   `http://<sports-host>:8095/xmltv.xml`. The playlist's `tvg-id` values
   (`yttv-sports-1`, `yttv-sports-2`, and so on) match the guide's channel
   IDs. Leave Gracenote station IDs blank for these virtual lanes.
4. Refresh the sports guide, then refresh the source and XMLTV guide in Channels.

APITuner looks up the current game at tune time and supplies the video stream
to Channels. This app's `/playlist.m3u` contains JSON resolver URLs for tuners.
See the [APITuner setup guide](https://github.com/matthewfkoch/APITuner#configure-channels)
for Android TV and encoder setup.

### Change the lane count

In the dashboard's **Guide** card, set **Lane count** and click **Save**.
Raise the count if overlapping events are being dropped, or lower it to reduce
the number of virtual channels. Saving immediately rebuilds lane assignments and
updates the feeds. Retained lanes keep their IDs and channel numbers.

If you use APITuner, download the updated channel export. When increasing the
count, import only the new lane entries to avoid duplicating existing channels.
When decreasing it, remove the retired sports lanes from APITuner. Then refresh
the Channels DVR source and its XMLTV guide.

The dashboard accepts 1–750 lanes, with higher values available if your existing
configuration already allows them. The saved count persists in the data volume
and takes precedence over `LANE_COUNT`.

## Optional env

| Variable | Purpose |
| --- | --- |
| `YTTV_EPG_SECRET` | Encrypts the session file. If unset, a key is created in the volume. |
| `PUBLIC_BASE_URL` | Host written into M3U / APITuner export. Loopback defaults follow the request host. |
| `LANE_COUNT` | Default virtual channel count (128) until you save a count in the dashboard. |
| `START_CHANNEL` | First export number (default 9100) |
| `XMLTV_INCLUDE_SUBTITLE` | Include the network name as a programme subtitle (default `false`). The network remains in the description. |
| `STATION_LOGOS_FILE` | Optional station-to-logo JSON file inside the container (default `/data/station-logos.json`). Restart after changes. |
| `HIDDEN_SPORTS` | Comma-separated sports to hide on first run (`Volleyball,Field Hockey`) |
| `HIDE_SPANISH` | Initial default for the saved Hide Spanish broadcasts preference (default `false`). Afterwards use the dashboard checkbox. |
| `HIDDEN_CHANNELS` | Comma-separated channel families to hide on first run (`ESPN+,NBC Sports Extra`) |
| `MAX_HUBS` | How many sports network hubs to mine (default 16) |
| `EPG_PAGES` / `HUB_PAGES` | How far to paginate the linear grid and hub schedules |
| `REFRESH_SECONDS` | How often to refresh ESPN labels and resolve missing watch links (default 60). Compose passes this into the container. |
| `FULL_MINE_SECONDS` | How often to re-mine the YouTube TV guide (default 300). Manual Refresh always does a full mine. |
| `CHROME_KEEPALIVE_SECONDS` | How often to reload YouTube TV to renew the browser session (default 14400 / 4 hours). |
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

## Channels DVR guide metadata

All programmes include Sports metadata. By default, Live and New require
separate programme-specific evidence and expire at the scheduled end.
Confirmed repeats include previously-shown metadata and remain playable.
Channels must refresh its guide to receive updated flags.

Network names are omitted from XMLTV subtitles by default so clients such as Android
can display the game title. Set `XMLTV_INCLUDE_SUBTITLE=true` to restore network
subtitles. The network is always included in the programme description.

M3U `tvg-logo` and XMLTV channel icons use the current event's broadcaster, or the
next watchable event's broadcaster during a gap. Logo priority is: user override,
the selected event's station metadata when it matches the resolved broadcaster,
a persisted logo for that broadcaster, a bundled broadcaster fallback, then the generic project logo. Event thumbnails remain separate. Refresh both the
M3U source and XMLTV guide in Channels after updating; cached logos may not change
immediately. An empty lane uses the generic logo.

Optional overrides are a JSON object of station names to HTTP(S) image URLs:

```json
{
  "ESPN": "https://your-image-host.example/espn.png",
  "NFL Network": "https://your-image-host.example/nfl-network.png"
}
```

Save this as `station-logos.json` and copy it into the persistent data volume:

```sh
docker cp station-logos.json yttvsportsdeeplinks:/data/station-logos.json
docker compose restart
```

Station matching ignores case and extra whitespace; ESPN/ESPN2 and FS1/FS2 remain
separate. A missing file uses automatic logos. Malformed files or invalid entries
log a warning and fall back to automatic logos for the affected stations. URLs must
be reachable by Channels DVR. Changing `STATION_LOGOS_FILE` in `.env` requires
`docker compose up -d` to recreate the container with the new setting.

## Spanish broadcast filtering and logo coverage

Use **Hide Spanish broadcasts** in the Sports section to exclude Spanish-language
listings from tuner lanes and XMLTV. It is off by default and saved in the data
volume. `HIDE_SPANISH` supplies the initial default only; subsequent changes should
use the dashboard. The `/api/filters` GET response includes `hide_spanish`; POST a
JSON boolean such as `{"hide_spanish": true}` to change it.

The filter recognizes explicit audio-language metadata, labels such as “En Español”
and “Spanish-language,” and these station identities: ESPN Deportes, TUDN,
Telemundo, Universo, Univision, UniMás, beIN SPORTS en Español, and ViX Premium
Deportes lanes. Unknown-language broadcasts remain included. Accents, team names,
and a game's country do not determine language. English and Spanish versions are
kept separate during duplicate matching, so hiding Spanish can retain the English
version. Existing unlabeled listings may need a full guide refresh to obtain
language metadata before they can be classified.

Discovered broadcaster logos are stored independently of event rows and survive
schedule refreshes. Local PNG fallbacks cover ESPN, ESPN2, ESPNU, ESPNEWS, ESPN+,
SEC Network, SEC+, ACC Network, ACC Extra, FS1, FS2, CBS Sports Network, and NFL
Network. ESPN Unlimited, ESPN Plus, and ES resolve to ESPN+; explicit ESPN+ channel metadata
also takes precedence over a broad ESPN station label. Logos belonging to that
broad ESPN label are skipped in this case. Game titles alone do not establish a
broadcaster. When the EPG and a game card describe the same stream and start time,
an explicit ESPN+ label takes precedence over a broad ESPN label. The optional
ESPN schedule enrichment also corrects broad ESPN labels when its exact title and
start time (within five minutes) match and all matching listings identify ESPN+.
Conflicting or missing broadcaster evidence leaves the original label intact.
Exact aliases are mapped explicitly; other stations still use discovered
logos or the generic fallback. Original asset URLs are recorded in
`src/yttv_epg/static/station-logos/sources.json`. These broadcaster marks retain
their original ownership.

After updating, refresh this app's guide and then the YTTV Sports M3U source and
XMLTV lineup in Channels DVR. Language preference changes rebuild app lanes
immediately; Channels still needs a source refresh to import the revised guide.

## Reliability and broadcast-status details

The dashboard's **Mark on-air programmes Live** switch defaults off. When enabled,
the dashboard and XMLTV label unknown-status programmes Live during their
scheduled airing window.
Explicit repeats and negative Live evidence still win; unidentified replays can
receive Live. New is unchanged. The preference persists in the catalog and takes
effect on the next guide request; refresh the Channels DVR guide to import it.
`XMLTV_LIVE_ON_AIR=false` seeds the preference only when no saved value exists.
The `/events` source-status fields are not changed by this output preference.

To investigate a specific game without changing classification, run inside the
signed-in service environment:

```sh
python -m yttv_epg.detail_probe --video-id WATCH_ID > game-details.json
# Or use a known game detail page:
python -m yttv_epg.detail_probe --browse-id BROWSE_ID > game-details.json
```

The diagnostic reads saved session cookies and fetches metadata only, without
starting playback or changing the catalog. It outputs selected programme fields,
capture time, and source paths, excluding credentials and tracking tokens. If the
saved cookies have expired, refresh the session in the dashboard first. Capture a
known live game and a replay near the same time for comparison. The captured ACC
replay fixture demonstrates why `SPORTS_EVENT` and a LIVE badge alone are not
confirmation. Event dates and detail-page badges remain diagnostic only.

Background evidence collection is enabled by `DETAIL_EVIDENCE=true`. A separate
worker checks every 30 seconds, defers to guide refreshes, and collects at most
two due airings per pass from current and next-24-hour events across all channels.
It uses the existing authenticated request path. Known detail IDs are tried first;
missing IDs or unmatched pages fall back to the watch-metadata lookup. Each
capture attempt has a 10-second timeout (at most two attempts per airing).

The separate `broadcast-evidence.sqlite` cache survives restarts. Current airings
refresh after five minutes; upcoming airings after an hour or when they start,
whichever comes first. Failures retry after five minutes and retain the last good
capture, marked stale. Cache keys include the programme, station, IDs, and full
broadcast interval so a rolling channel watch ID cannot transfer evidence to a
different airing. Successful observations are also saved as history. Both cache
and history retain at most 1,000 records for seven days, pruned during collection
and inspection.

Inspect `/api/broadcast-evidence` for cached facts, matching results, date gaps,
badge observations, timestamps, staleness, and error categories. Add
`?history=true&include_capture=true` for the sanitized historical captures;
`limit` (1–100) and `offset` paginate results. This endpoint uses dashboard admin
authentication when configured and disables HTTP caching. `last_cycle` reports
worker progress; top-level `error` reports worker failures, while record errors
describe individual fetch failures. Setting `DETAIL_EVIDENCE=false` stops new
collection without erasing existing evidence.

Channel matching ignores recognized detail-page language prefixes (`ES`, `EN`)
and trailing TV ratings separated by `•`. Other channel text is preserved.
Unmatched records include up to five closest candidates with source paths and
the fields that did not match; show titles are not treated as episode titles.
Explicit description openings such as “Replays of” or “Replay:” produce an
`explicit_replay_description` signal, with the matched phrase, description, and
source path in `description_evidence`. Mentions of instant replay during coverage
do not produce this signal. These observations do not exclude programmes.

Only exact normalized title, canonical station, start/end times, and compatible
watch IDs associate a detail card with a broadcast. Header dates are used only
for a matching event title and `SPORTS_EVENT` type. Missing or conflicting matches
stay unmatched. **All results are observations: no automatic replay exclusions,
Live/New changes, or recording decisions use this evidence.** A same-day event
date is not Live confirmation; an older date remains a diagnostic signal pending
validation of overnight events, multi-day events, and same-day replays.

The dashboard waits for filter-save acknowledgement before accepting background
status responses or reloading. Failed saves restore the server-confirmed setting
and display an error. Dashboard/status/filter responses are not cached, and the
script URL changes when its content changes.

`/events` includes nullable `broadcast_live`, `first_run`, and `is_repeat` fields.
YouTube TV's LIVE badge describes a stream and can appear on a replay, so its
broadcast status remains unknown. Explicit NEW and REPEAT, REPLAY, or RERUN
badges supply programme evidence.

With Docker Compose, an optional Gracenote grid file at
`/data/gracenote-grid.json` can supply Live, New, repeat, and tape-delay flags.
Set `GRACENOTE_GRID_FILE` to use another path inside the container. The match
requires the station, title, start, and end to agree. Explicit repeat flags clear
both Live and New. Tape-delay flags clear Live.

Session files are saved atomically with restricted permissions. If a session is
unreadable, the dashboard stays available with a recovery warning. Check the secret
or sign in again. Before replacement, the encrypted original is saved as a
restricted `session-recovery-*.enc` file in the data directory. These files contain
sensitive encrypted session data and should remain in the persistent data volume.

Watch-link resolution preserves playback parameters, ignores ended/invalid
listings, and prioritizes active games followed by nearest upcoming games within
the existing lookup window and limit.

## Individual channel filters

Channel chips independently control each discovered channel, including ESPN,
ESPN2, ESPNU, ESPNEWS, ESPN+, FS1, FS2, FOX, ABC, NBC, NBC Sports, CBS, and CBS
Sports. Local affiliates and numbered extra feeds also remain separate, except ViX feeds
which share one **ViX** filter with a combined event count. Their original station
names and logos remain available in the guide. Any previously excluded ViX feed
becomes a ViX group exclusion; selecting ViX includes all of its feeds again. Equivalent
aliases such as FS1 / FOX SPORTS 1 share a chip. Filter counts, dashboard rows,
tuner lanes, and XMLTV use the same channel identity.

On the first startup after upgrading, saved network-family exclusions expand to
known constituent channels and matching stations in the saved guide. This migration
runs once; later selections are independent. Newly discovered affiliates or numbered
feeds not present during migration are included until individually excluded.
New installations and `HIDDEN_CHANNELS` defaults use individual identities.
The `/api/filters` interface is unchanged, with individual channel names in its
channel lists. Refresh the Channels DVR M3U source and XMLTV after updating.

Spanish description evidence distinguishes explicit repeats (`Repetición del
partido`, `Reemisión:`), highlights (`Compacto de la fecha`, `Los momentos más
destacados del partido`), and dated match descriptions (`Disputado el …`). Each
signal retains its source phrase and renderer path. A dated description alone
is not classified as a replay, and mentions of instant replay or live
`retransmisión` are not treated as repeat evidence. When a described match date
precedes its scheduled airing, the record adds `historical_match_description`
with the parsed date. Automatic exclusions remain disabled.
