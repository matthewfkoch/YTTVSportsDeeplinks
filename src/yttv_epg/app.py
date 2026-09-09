from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile
from starlette.middleware.base import BaseHTTPMiddleware

from yttv_epg.branding import EYEBROW, PRODUCT_NAME, for_ui
from yttv_epg.catalog import Catalog
from yttv_epg.chrome import ChromeError, available as chrome_available
from yttv_epg.chrome import chrome_signed_in, clear_browser_cookies, fetch_cookies
from yttv_epg.chrome import open_youtube_tv, prune_chrome_profile, prune_non_youtube_cookies, status as chrome_status
from yttv_epg.config import settings
from yttv_epg.display import format_refresh, group_events_for_ui, local_tz
from yttv_epg.espn_schedule import apply_espn_sports, fetch_espn_schedule
from yttv_epg.feeds import apituner_export, m3u, whatson_payload, xmltv
from yttv_epg.innertube import CLIENTS, InnerTubeClient, MineError, session_expired_message
from yttv_epg.lanes import LaneAssignment, pack_lanes, whatson
from yttv_epg.parse import Airing, merge_airings
from yttv_epg.session import CookieError, parse_cookie_text, require_youtube_tv_cookies
from yttv_epg.session_store import SavedSession, SessionStore
from yttv_epg.sports import (
    channel_counts,
    is_non_sports_station,
    is_sports_event,
    sport_counts,
    toggle_name,
    visible_events,
)

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


class State:
    def __init__(self) -> None:
        self.store = SessionStore(settings.data_dir, settings.secret)
        self.catalog = Catalog(settings.data_dir / "catalog.sqlite")
        self.http = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        self.innertube = InnerTubeClient(self.http)
        self.refresh_lock = asyncio.Lock()
        self.refreshing = False
        self.refresh_jobs = 0
        self.session: Optional[SavedSession] = self.store.load()
        self.espn_listings: list = []
        self.espn_fetched_at: Optional[datetime] = None
        self.lane_assignments: Optional[list[LaneAssignment]] = None
        self.last_full_mine_at: Optional[datetime] = None


state = State()


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.admin_locked:
            return await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/api/auth") or path.startswith("/api/status") or path.startswith("/api/refresh") or path.startswith("/api/filters"):
            auth = request.headers.get("authorization", "")
            expected = _basic_header(settings.admin_user, settings.admin_password)
            if auth != expected:
                return Response(
                    "Authentication required",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="YTTV Sports"'},
                )
        return await call_next(request)


def _basic_header(user: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _ensure_session() -> SavedSession:
    session = state.session or state.store.load()
    if session is None:
        raise HTTPException(status_code=401, detail="Not signed in to YTTV")
    state.session = session
    return session


def _with_espn_sports(events: Optional[list[Airing]] = None) -> list[Airing]:
    rows = events if events is not None else state.catalog.events(kind="event")
    return apply_espn_sports(merge_airings(rows), state.espn_listings)


def _watchable_events(events: Optional[list[Airing]] = None) -> list[Airing]:
    return [
        item
        for item in _with_espn_sports(events)
        if item.watch_id()
        and not is_non_sports_station(item.station)
        and is_sports_event(item.station, item.title, item.sport)
    ]


def _visible_events(
    events: Optional[list[Airing]] = None,
    hidden_sports: Optional[list[str]] = None,
    hidden_channels: Optional[list[str]] = None,
) -> list[Airing]:
    rows = _with_espn_sports(events)
    sports = hidden_sports if hidden_sports is not None else state.catalog.hidden_sports()
    channels = hidden_channels if hidden_channels is not None else state.catalog.hidden_channels()
    return visible_events(rows, sports, channels, require_watch_link=True)


def _meta_int(meta: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(meta.get(key) or default)
    except (TypeError, ValueError):
        return default


def _set_lane_cache(assignments: list[LaneAssignment]) -> list[LaneAssignment]:
    state.lane_assignments = [row for row in assignments if row.airing.watch_id()]
    return state.lane_assignments


def _store_lanes(
    assignments: list[LaneAssignment],
    *,
    visible_count: int,
    watchable_count: int,
) -> None:
    dropped = max(0, visible_count - len(assignments))
    state.catalog.replace_lanes(
        assignments,
        visible_count=visible_count,
        watchable_count=watchable_count,
        dropped=dropped,
    )
    _set_lane_cache(assignments)


def _labeled_assignments() -> list[LaneAssignment]:
    if state.lane_assignments is None:
        _set_lane_cache(state.catalog.assignments())
    return state.lane_assignments or []


async def _refresh_espn_listings(force: bool = False) -> bool:
    if not settings.espn_schedule:
        return False
    now = datetime.now(timezone.utc)
    if (
        not force
        and state.espn_listings
        and state.espn_fetched_at
        and now - state.espn_fetched_at < timedelta(seconds=120)
    ):
        return False
    try:
        listings = await fetch_espn_schedule(state.http)
    except (httpx.HTTPError, ValueError, TypeError):
        return False
    if listings:
        state.espn_listings = listings
        state.espn_fetched_at = now
        events = apply_espn_sports(state.catalog.events(), listings)
        if events:
            state.catalog.update_sports(events)
            visible = _visible_events(events)
            _store_lanes(
                pack_lanes(visible, settings.lane_count),
                visible_count=len(visible),
                watchable_count=len(_watchable_events(events)),
            )
        return True
    return False


def _novnc_url(request: Request) -> str:
    if settings.novnc_public_url:
        return settings.novnc_public_url
    host = request.url.hostname or "127.0.0.1"
    return (
        f"{request.url.scheme}://{host}:{settings.novnc_port}"
        "/vnc.html?autoconnect=true&resize=scale&reconnect=true"
    )


def _loopback_host(host: str) -> bool:
    label = (host or "").lower().strip("[]")
    return label in {"127.0.0.1", "localhost", "::1", "0.0.0.0"} or label.endswith(".localhost")


def _session_view(meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    meta = meta if meta is not None else state.catalog.meta()
    last_error = for_ui(meta.get("last_error")) or ""
    signed_in = state.store.signed_in
    return {
        "signed_in": signed_in,
        "session_expired": bool(signed_in and session_expired_message(last_error)),
        "last_error": last_error or None,
    }


async def _clear_expired_chrome() -> None:
    if not settings.enable_chrome:
        return
    try:
        if await chrome_available(state.http, settings.cdp_url):
            await clear_browser_cookies(state.http, settings.cdp_url)
    except (ChromeError, httpx.HTTPError, RuntimeError):
        return


async def _mark_refresh_failure(exc: Exception) -> None:
    state.catalog.set_error(str(exc))
    if isinstance(exc, MineError) and session_expired_message(str(exc)):
        await _clear_expired_chrome()


def _public_base_url(request: Request) -> str:
    configured = (settings.public_base_url or "").rstrip("/")
    configured_host = urlparse(configured).hostname if configured else ""
    if configured and not _loopback_host(configured_host or ""):
        return configured
    incoming = str(request.base_url).rstrip("/")
    incoming_host = request.url.hostname or ""
    if incoming and not _loopback_host(incoming_host):
        return incoming
    return configured or incoming or "http://127.0.0.1:8095"


async def _sync_session_from_chrome() -> bool:
    if not settings.enable_chrome:
        return False
    try:
        cookies = await fetch_cookies(state.http, settings.cdp_url)
        if not chrome_signed_in(cookies):
            return False
        cookies = await prune_non_youtube_cookies(state.http, settings.cdp_url, cookies)
        cookies = require_youtube_tv_cookies(cookies)
    except (ChromeError, CookieError, httpx.HTTPError):
        return False
    state.session = SavedSession(kind="cookies", cookies=cookies)
    state.store.save(state.session)
    return True


async def _activate_cookies(cookies: list[dict[str, str]]) -> dict[str, Any]:
    cookies = require_youtube_tv_cookies(cookies)
    session = SavedSession(kind="cookies", cookies=cookies)
    try:
        client_name = await state.innertube.probe(session)
    except MineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    state.session = session
    state.store.save(session)
    try:
        result = await refresh_catalog()
    except Exception as exc:
        return {"ok": True, "client": client_name, "warning": str(exc)}
    result["ok"] = True
    return result


async def _cookie_text_from_request(request: Request) -> str:
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if isinstance(body, dict):
            return str(body.get("cookies") or body.get("text") or "")
        raise HTTPException(status_code=400, detail="Expected a JSON object with a cookies field")
    if content_type.startswith("multipart/form-data") or content_type.startswith(
        "application/x-www-form-urlencoded"
    ):
        form = await request.form()
        upload = form.get("file")
        if isinstance(upload, UploadFile):
            data = await upload.read()
            if data:
                return data.decode("utf-8", errors="replace")
        return str(form.get("cookies") or form.get("text") or "")
    return (await request.body()).decode("utf-8", errors="replace")


async def refresh_catalog() -> dict[str, Any]:
    state.refresh_jobs += 1
    state.refreshing = True
    try:
        async with state.refresh_lock:
            await _sync_session_from_chrome()
            await _refresh_espn_listings()
            session = _ensure_session()
            try:
                mined = await state.innertube.mine(session, settings.fallback_duration_min)
            except (MineError, httpx.HTTPError) as exc:
                await _mark_refresh_failure(exc)
                raise
            events = apply_espn_sports(
                merge_airings(item for item in mined.airings if item.kind == "event"),
                state.espn_listings,
            )
            visible = _visible_events(events)
            watchable = _watchable_events(events)
            assignments = pack_lanes(visible, settings.lane_count)
            linear_ignored = len(mined.airings) - len(events)
            state.catalog.replace(
                events,
                assignments,
                client=mined.client,
                browse_id=mined.browse_id,
                linear_ignored=linear_ignored,
                dropped=max(0, len(visible) - len(assignments)),
                visible_count=len(visible),
                watchable_count=len(watchable),
            )
            _set_lane_cache(assignments)
            state.last_full_mine_at = datetime.now(timezone.utc)
            if settings.allow_debug:
                state.catalog.save_debug(settings.data_dir, "last_browse.json", mined.raw)
            return {
                "ok": True,
                "events": len(visible),
                "all_events": len(events),
                "hidden": len(events) - len(visible),
                "linear": linear_ignored,
                "lanes_used": len({row.lane for row in assignments}),
                "dropped": max(0, len(visible) - len(assignments)),
                "client": mined.client,
                "browse_id": mined.browse_id,
            }
    finally:
        state.refresh_jobs = max(0, state.refresh_jobs - 1)
        state.refreshing = state.refresh_jobs > 0


def _unresolved_soon(events: list[Airing], *, within_hours: int = 36, limit: int = 80) -> list[Airing]:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=within_hours)
    pending: list[Airing] = []
    for item in events:
        if item.watch_id() or not item.entity_id:
            continue
        if not item.live and item.start > cutoff:
            continue
        pending.append(item)
        if len(pending) >= limit:
            break
    return pending


async def refresh_watch_ids() -> dict[str, Any]:
    state.refresh_jobs += 1
    state.refreshing = True
    try:
        async with state.refresh_lock:
            await _sync_session_from_chrome()
            espn_changed = await _refresh_espn_listings()
            session = _ensure_session()
            candidates = _unresolved_soon(state.catalog.events(kind="event"))
            pairs: list[tuple[Airing, Airing]] = []
            if candidates:
                try:
                    resolved = await state.innertube.resolve_soon(session, dict(CLIENTS[0]), candidates)
                except (MineError, httpx.HTTPError) as exc:
                    await _mark_refresh_failure(exc)
                    raise
                for previous, updated in zip(candidates, resolved):
                    if not isinstance(updated, Airing):
                        continue
                    if updated.watch_id() and updated.watch_id() != previous.watch_id():
                        pairs.append((previous, updated))
            if pairs:
                state.catalog.replace_resolved(pairs)
            if pairs or espn_changed:
                visible = _visible_events()
                _store_lanes(
                    pack_lanes(visible, settings.lane_count),
                    visible_count=len(visible),
                    watchable_count=len(_watchable_events()),
                )
                state.catalog.touch_refresh()
            return {
                "ok": True,
                "resolved": len(pairs),
                "changed": bool(pairs or espn_changed),
            }
    finally:
        state.refresh_jobs = max(0, state.refresh_jobs - 1)
        state.refreshing = state.refresh_jobs > 0


async def refresh_loop() -> None:
    delay = 30
    while True:
        if state.store.signed_in:
            try:
                now = datetime.now(timezone.utc)
                due = (
                    state.last_full_mine_at is None
                    or (now - state.last_full_mine_at).total_seconds() >= max(settings.full_mine_seconds, 30)
                )
                if due:
                    prune_chrome_profile(settings.chrome_profile_dir)
                    await refresh_catalog()
                else:
                    await refresh_watch_ids()
                delay = max(settings.refresh_seconds, 30)
            except Exception:
                delay = 60
        elif settings.enable_chrome:
            await _sync_session_from_chrome()
            delay = 30
        else:
            delay = max(settings.refresh_seconds, 30)
        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    prune_chrome_profile(settings.chrome_profile_dir, cap_cache=True)
    state.catalog.ensure_hidden_sports(settings.hidden_sports_list)
    state.catalog.ensure_hidden_channels(settings.hidden_channels_list)
    visible = _visible_events()
    _store_lanes(
        pack_lanes(visible, settings.lane_count),
        visible_count=len(visible),
        watchable_count=len(_watchable_events()),
    )
    if state.http.is_closed:
        state.http = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        state.innertube = InnerTubeClient(state.http)
    try:
        await asyncio.wait_for(_sync_session_from_chrome(), timeout=8)
    except Exception:
        pass
    task = asyncio.create_task(refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        await state.http.aclose()


app = FastAPI(title=PRODUCT_NAME, lifespan=lifespan)
app.add_middleware(AdminAuthMiddleware)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/health")
async def health() -> dict[str, Any]:
    meta = state.catalog.meta()
    auth = _session_view(meta)
    return {
        "ok": True,
        "signed_in": auth["signed_in"],
        "session_expired": auth["session_expired"],
        "chrome": settings.enable_chrome,
        "last_refresh": meta.get("last_refresh"),
        "last_error": auth["last_error"],
        "refreshing": state.refreshing,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    meta = state.catalog.meta()
    auth = _session_view(meta)
    all_events = state.catalog.events(kind="event")
    hidden = state.catalog.hidden_sports()
    hidden_channels = state.catalog.hidden_channels()
    visible = _visible_events(all_events, hidden, hidden_channels)
    linked = _watchable_events(all_events)
    zone = local_tz()
    shown = linked[:2000]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "signed_in": auth["signed_in"],
            "session_expired": auth["session_expired"],
            "last_refresh": format_refresh(meta.get("last_refresh") or "", tz=zone),
            "last_refresh_at": meta.get("last_refresh") or "",
            "last_error": auth["last_error"] or "",
            "client": meta.get("last_client") or "",
            "browse_id": meta.get("last_browse_id") or "",
            "event_count": len(visible),
            "all_event_count": len(linked),
            "shown_count": len(shown),
            "linear_count": int(meta.get("linear_ignored") or 0),
            "event_groups": group_events_for_ui(linked, tz=zone, limit=2000),
            "sports": sport_counts(linked),
            "channels": channel_counts(linked),
            "hidden_sports": hidden,
            "hidden_channels": hidden_channels,
            "lane_count": settings.lane_count,
            "lanes_used": int(meta.get("lanes_used") or 0),
            "dropped_events": int(meta.get("dropped_events") or 0),
            "public_base_url": _public_base_url(request),
            "product_name": PRODUCT_NAME,
            "eyebrow": EYEBROW,
            "chrome_enabled": settings.enable_chrome,
            "novnc_url": _novnc_url(request),
            "time_zone": str(zone),
            "refreshing": state.refreshing,
        },
    )


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    meta = state.catalog.meta()
    auth = _session_view(meta)
    return {
        "signed_in": auth["signed_in"],
        "session_expired": auth["session_expired"],
        "last_refresh": meta.get("last_refresh"),
        "last_error": auth["last_error"],
        "refreshing": state.refreshing,
        "client": meta.get("last_client") or None,
        "browse_id": meta.get("last_browse_id") or None,
        "events": _meta_int(meta, "visible_count"),
        "all_events": _meta_int(meta, "watchable_count"),
        "linear": int(meta.get("linear_ignored") or 0),
        "lanes_used": int(meta.get("lanes_used") or 0),
        "dropped": int(meta.get("dropped_events") or 0),
    }


@app.post("/api/auth/cookies")
async def auth_cookies(request: Request) -> dict[str, Any]:
    raw = await _cookie_text_from_request(request)
    try:
        cookies = parse_cookie_text(raw)
    except CookieError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await _activate_cookies(cookies)
    except CookieError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/auth/chrome/status")
async def auth_chrome_status() -> dict[str, Any]:
    if not settings.enable_chrome:
        return {"available": False, "signed_in": False, "url": None}
    try:
        return await chrome_status(state.http, settings.cdp_url)
    except ChromeError as exc:
        return {"available": False, "signed_in": False, "url": None, "error": str(exc)}


@app.post("/api/auth/chrome/open")
async def auth_chrome_open() -> dict[str, Any]:
    if not settings.enable_chrome:
        raise HTTPException(status_code=503, detail="In-container Chromium is disabled.")
    try:
        return await open_youtube_tv(state.http, settings.cdp_url)
    except ChromeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/auth/chrome/capture")
async def auth_chrome_capture() -> dict[str, Any]:
    if not settings.enable_chrome:
        raise HTTPException(status_code=503, detail="In-container Chromium is disabled.")
    try:
        cookies = await fetch_cookies(state.http, settings.cdp_url)
        cookies = await prune_non_youtube_cookies(state.http, settings.cdp_url, cookies)
        return await _activate_cookies(cookies)
    except CookieError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChromeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/auth/logout")
async def auth_logout() -> dict[str, bool]:
    if settings.enable_chrome:
        try:
            if await chrome_available(state.http, settings.cdp_url):
                await clear_browser_cookies(state.http, settings.cdp_url)
        except (ChromeError, httpx.HTTPError, RuntimeError):
            pass
    state.session = None
    state.store.clear()
    state.catalog.clear_error()
    return {"ok": True}


@app.get("/api/filters")
async def get_filters() -> dict[str, Any]:
    events = _watchable_events()
    hidden = state.catalog.hidden_sports()
    hidden_channels = state.catalog.hidden_channels()
    return {
        "sports": sport_counts(events),
        "channels": channel_counts(events),
        "hidden": hidden,
        "hidden_channels": hidden_channels,
    }


@app.post("/api/filters")
async def set_filters(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    hidden = state.catalog.hidden_sports()
    hidden_channels = state.catalog.hidden_channels()
    if "hidden" in body and isinstance(body["hidden"], list):
        hidden = [str(item) for item in body["hidden"] if str(item).strip()]
    if "hidden_channels" in body and isinstance(body["hidden_channels"], list):
        hidden_channels = [str(item) for item in body["hidden_channels"] if str(item).strip()]
    toggle = str(body.get("toggle") or "").strip()
    if toggle:
        hidden = toggle_name(hidden, toggle)
    toggle_channel = str(body.get("toggle_channel") or "").strip()
    if toggle_channel:
        hidden_channels = toggle_name(hidden_channels, toggle_channel)
    state.catalog.set_hidden_sports(hidden)
    state.catalog.set_hidden_channels(hidden_channels)
    visible = _visible_events(None, hidden, hidden_channels)
    watchable = _watchable_events()
    _store_lanes(
        pack_lanes(visible, settings.lane_count),
        visible_count=len(visible),
        watchable_count=len(watchable),
    )
    return {
        "ok": True,
        "hidden": state.catalog.hidden_sports(),
        "hidden_channels": state.catalog.hidden_channels(),
        "events": len(visible),
        "all_events": len(watchable),
    }


@app.post("/api/refresh")
async def api_refresh() -> dict[str, Any]:
    try:
        return await refresh_catalog()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/events")
async def list_events(kind: str = Query("event")) -> dict[str, Any]:
    if kind not in {"event", "linear", "all"}:
        raise HTTPException(status_code=400, detail="kind must be event, linear, or all")
    rows = state.catalog.events(None if kind == "all" else kind)
    if kind != "linear":
        rows = [
            item
            for item in _with_espn_sports(rows)
            if item.kind == "linear"
            or (
                item.watch_id()
                and not is_non_sports_station(item.station)
                and is_sports_event(item.station, item.title, item.sport)
            )
        ]
    return {"count": len(rows), "events": [item.to_dict() for item in rows]}


@app.get("/linear")
async def list_linear() -> dict[str, Any]:
    rows = state.catalog.events(kind="linear")
    return {
        "count": len(rows),
        "channels": [
            {"name": item.station or item.title, "video_id": item.video_id, "deeplink": item.deeplink}
            for item in rows
        ],
    }


@app.get("/whatson/{lane}")
async def whatson_lane(
    lane: int,
    format: str = Query("json"),
    include: str = Query(""),
):
    _ = include
    if lane < 1 or lane > settings.lane_count:
        raise HTTPException(status_code=404, detail="Unknown lane")
    airing = whatson(_labeled_assignments(), lane, datetime.now(timezone.utc))
    if airing and not airing.watch_id() and state.session:
        try:
            airing = await state.innertube.resolve_watch(state.session, dict(CLIENTS[0]), airing)
        except MineError:
            pass
    payload = whatson_payload(lane, airing)
    if format in {"text", "txt"}:
        if not payload.get("ok"):
            return PlainTextResponse("", status_code=404)
        return PlainTextResponse(str(payload["deeplink_url"]))
    return JSONResponse(payload)


@app.get("/xmltv.xml")
@app.get("/epg.xml")
async def xmltv_feed(request: Request) -> Response:
    body = xmltv(
        _labeled_assignments(),
        settings.lane_count,
        base_url=_public_base_url(request),
    )
    return Response(content=body, media_type="application/xml")


@app.get("/playlist.m3u")
async def playlist(request: Request) -> PlainTextResponse:
    body = m3u(
        base_url=_public_base_url(request),
        lane_count=settings.lane_count,
        start_channel=settings.start_channel,
        package_name=settings.package_name,
        alternate_package_name=settings.alternate_package_name,
    )
    return PlainTextResponse(body, media_type="application/x-mpegurl")


@app.get("/api/export")
async def export_channels(request: Request) -> list[dict[str, str | int]]:
    return apituner_export(
        base_url=_public_base_url(request),
        lane_count=settings.lane_count,
        start_channel=settings.start_channel,
        package_name=settings.package_name,
        alternate_package_name=settings.alternate_package_name,
    )
