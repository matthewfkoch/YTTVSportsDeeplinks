from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from yttv_epg.config import settings
from yttv_epg.parse import (
    Airing,
    discover_browse_tabs,
    discover_event_hubs,
    discover_sports_chips,
    keep_hub_tab,
    merge_airings,
    parse_browse,
)
from yttv_epg.session import innertube_headers
from yttv_epg.session_store import SavedSession

BROWSE_IDS = ("FEunplugged_epg", "FEunplugged_home", "FEunplugged_main")
ESPN_HUB_FALLBACK = "UCakwQ1jKQnYJcUMghvnp-Yw"

CLIENTS = (
    {
        "name": "WEB_UNPLUGGED",
        "version": "1.20260831.00.00",
        "id": "41",
        "host": "https://tv.youtube.com",
        "path": "/youtubei/v1/browse",
        "query": "alt=json",
        "ua": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        ),
        "origin": "https://tv.youtube.com",
    },
    {
        "name": "TVHTML5_UNPLUGGED",
        "version": "6.36",
        "id": "65",
        "host": "https://tv.youtube.com",
        "path": "/youtubei/v1/browse",
        "query": "alt=json",
        "ua": (
            "Mozilla/5.0 (ChromiumStyle; Linux) Cobalt/Version "
            "com.google.android.youtube.tvunplugged/6.36"
        ),
        "origin": "https://tv.youtube.com",
    },
)


class MineError(RuntimeError):
    pass


def session_expired_message(text: str | None) -> bool:
    lowered = (text or "").lower()
    return "session expired" in lowered or "http 401" in lowered or "http 403" in lowered


def _session_expired(exc: Exception) -> bool:
    return session_expired_message(str(exc))


@dataclass
class MineResult:
    airings: list
    client: str
    browse_id: str
    raw: dict[str, Any]


class InnerTubeClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self.visitor_data = ""
        self._visitor_lock = asyncio.Lock()
        self._visitor_frozen = False
        self._sema: Optional[asyncio.Semaphore] = None
        self._sema_loop: Optional[asyncio.AbstractEventLoop] = None

    def _http_sema(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        n = max(1, int(settings.mine_concurrency))
        if self._sema is None or self._sema_loop is not loop:
            self._sema = asyncio.Semaphore(n)
            self._sema_loop = loop
        return self._sema

    async def _set_visitor(self, visitor: str) -> None:
        async with self._visitor_lock:
            if self._visitor_frozen and self.visitor_data:
                return
            self.visitor_data = visitor

    async def _freeze_visitor(self, frozen: bool) -> None:
        async with self._visitor_lock:
            self._visitor_frozen = frozen

    async def probe(self, session: SavedSession) -> str:
        errors: list[str] = []
        for client in CLIENTS:
            try:
                await self._browse(session, client, body={"browseId": "FEunplugged_epg"})
            except MineError as exc:
                errors.append(str(exc))
                continue
            return str(client["name"])
        raise MineError(errors[-1] if errors else "YTTV rejected this session.")

    async def mine(self, session: SavedSession, fallback_minutes: int = 180) -> MineResult:
        errors: list[str] = []
        try:
            for client in CLIENTS:
                result = await self._mine_client(session, client, fallback_minutes, errors)
                if result is not None:
                    return result
            raise MineError(
                errors[0] if errors else "No InnerTube browse response contained watch links."
            )
        finally:
            await self._freeze_visitor(False)

    async def _mine_client(
        self,
        session: SavedSession,
        client: dict[str, str],
        fallback_minutes: int,
        errors: list[str],
    ) -> Optional[MineResult]:
        payloads: list[tuple[str, dict[str, Any]]] = []
        await self._freeze_visitor(False)
        try:
            epg = await self._browse_all(
                session, client, "FEunplugged_epg", max_pages=settings.epg_pages
            )
        except MineError as exc:
            errors.append(str(exc))
            if _session_expired(exc):
                return None
            return await self._mine_fallbacks(session, client, fallback_minutes, errors)
        payloads.append(("FEunplugged_epg", epg))
        await self._freeze_visitor(True)
        hubs = discover_event_hubs(epg) or [ESPN_HUB_FALLBACK]
        hub_results = await asyncio.gather(
            *[self._mine_hub(session, client, hub_id) for hub_id in hubs[: settings.max_hubs]],
            return_exceptions=True,
        )
        if _abort_if_expired(hub_results, errors):
            return None
        for item in hub_results:
            if isinstance(item, Exception):
                errors.append(str(item))
                continue
            payloads.extend(item)
        seen_browses = {browse_id.split(":")[0] for browse_id, _ in payloads}
        chip_jobs: list[tuple[str, str, Any]] = []
        for chip in discover_sports_chips(epg):
            browse_id = str(chip.get("browse_id") or "")
            if not browse_id or browse_id in seen_browses or browse_id.startswith("UC"):
                continue
            seen_browses.add(browse_id)
            chip_jobs.append((browse_id, str(chip.get("title") or "sports"), chip))
        chip_results = await asyncio.gather(
            *[
                self._browse_all(
                    session,
                    client,
                    browse_id,
                    max_pages=settings.hub_pages,
                    params=str(chip.get("params") or "") or None,
                )
                for browse_id, _title, chip in chip_jobs
            ],
            return_exceptions=True,
        )
        if _abort_if_expired(chip_results, errors):
            return None
        for (browse_id, title, _chip), extra in zip(chip_jobs, chip_results):
            if isinstance(extra, Exception):
                errors.append(str(extra))
                continue
            payloads.append((f"{browse_id}:{title}", extra))
        airings = merge_airings(
            airing
            for browse_id, payload in payloads
            for airing in parse_browse(
                payload,
                fallback_minutes=fallback_minutes,
                source=f"{client['name']}:{browse_id}",
            )
        )
        try:
            airings = await self.resolve_soon(session, client, airings)
        except MineError as exc:
            errors.append(str(exc))
            if _session_expired(exc):
                return None
            raise
        if airings:
            seen_ids: list[str] = []
            for browse_id, _ in payloads:
                base = browse_id.split(":")[0]
                if base not in seen_ids:
                    seen_ids.append(base)
            return MineResult(
                airings=airings,
                client=str(client["name"]),
                browse_id="+".join(seen_ids),
                raw=payloads[-1][1],
            )
        errors.append(f"{client['name']} FEunplugged_epg returned no watch links")
        return await self._mine_fallbacks(session, client, fallback_minutes, errors)

    async def _mine_hub(
        self,
        session: SavedSession,
        client: dict[str, str],
        hub_id: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        first = await self._browse_all(
            session, client, hub_id, max_pages=settings.hub_pages
        )
        payloads: list[tuple[str, dict[str, Any]]] = [(hub_id, first)]
        seen: set[tuple[str, str, str]] = {(hub_id, "", "")}
        tab_jobs: list[tuple[str, Any]] = []
        for tab in discover_browse_tabs(first):
            browse_id = str(tab.get("browse_id") or hub_id)
            params = str(tab.get("params") or "")
            continuation = str(tab.get("continuation") or "")
            title = str(tab.get("title") or "")
            if not keep_hub_tab(title):
                continue
            key = (browse_id, params, continuation)
            if key in seen:
                continue
            if tab.get("selected") and not params and not continuation:
                continue
            seen.add(key)
            label = f"{browse_id}:{title}" if title else browse_id
            if continuation and not params:
                tab_jobs.append(
                    (
                        label,
                        self._browse_all(
                            session,
                            client,
                            browse_id,
                            max_pages=settings.hub_pages,
                            continuation=continuation,
                        ),
                    )
                )
            else:
                tab_jobs.append(
                    (
                        label,
                        self._browse_all(
                            session,
                            client,
                            browse_id,
                            max_pages=settings.hub_pages,
                            params=params or None,
                        ),
                    )
                )
        tab_results = await asyncio.gather(*(job for _label, job in tab_jobs), return_exceptions=True)
        expired = next((item for item in tab_results if isinstance(item, Exception) and _session_expired(item)), None)
        if expired is not None:
            raise expired if isinstance(expired, MineError) else MineError(str(expired))
        for (label, _job), extra in zip(tab_jobs, tab_results):
            if isinstance(extra, Exception):
                continue
            payloads.append((label, extra))
        return payloads

    async def _mine_fallbacks(
        self,
        session: SavedSession,
        client: dict[str, str],
        fallback_minutes: int,
        errors: list[str],
    ) -> Optional[MineResult]:
        for browse_id in BROWSE_IDS[1:]:
            try:
                payload = await self._browse_all(session, client, browse_id)
            except MineError as exc:
                errors.append(str(exc))
                continue
            airings = parse_browse(
                payload,
                fallback_minutes=fallback_minutes,
                source=f"{client['name']}:{browse_id}",
            )
            if airings:
                return MineResult(
                    airings=airings,
                    client=str(client["name"]),
                    browse_id=browse_id,
                    raw=payload,
                )
            errors.append(f"{client['name']} {browse_id} returned no watch links")
        return None

    async def _browse_all(
        self,
        session: SavedSession,
        client: dict[str, str],
        browse_id: str,
        max_pages: int = 12,
        params: Optional[str] = None,
        continuation: Optional[str] = None,
    ) -> dict[str, Any]:
        if continuation:
            first = await self._browse(session, client, body={"continuation": continuation})
        else:
            body: dict[str, Any] = {"browseId": browse_id}
            if params:
                body["params"] = params
            first = await self._browse(session, client, body=body)
        merged: dict[str, Any] = dict(first)
        pages = [first]
        continuation = _continuation(first)
        seen = 0
        while continuation and seen < max_pages:
            seen += 1
            page = await self._browse(session, client, body={"continuation": continuation})
            pages.append(page)
            continuation = _continuation(page)
        merged["_yttv_epg_pages"] = pages
        return merged

    async def resolve_soon(
        self,
        session: SavedSession,
        client: dict[str, str],
        airings: list,
        *,
        within_hours: int = 36,
        limit: int = 80,
    ) -> list:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=within_hours)
        pending: list[Airing] = []
        for item in airings:
            if not isinstance(item, Airing):
                continue
            if item.watch_id() or not item.entity_id:
                continue
            if not item.live and item.start > cutoff:
                continue
            if len(pending) >= limit:
                continue
            pending.append(item)
        if not pending:
            return [item for item in airings if isinstance(item, Airing)]
        resolved = await asyncio.gather(
            *[self.resolve_watch(session, client, item) for item in pending],
            return_exceptions=True,
        )
        expired = next((item for item in resolved if isinstance(item, Exception) and _session_expired(item)), None)
        if expired is not None:
            raise expired if isinstance(expired, MineError) else MineError(str(expired))
        by_id = {
            id(src): (item if isinstance(item, Airing) else src)
            for src, item in zip(pending, resolved)
        }
        out: list[Airing] = []
        for item in airings:
            if not isinstance(item, Airing):
                continue
            out.append(by_id.get(id(item), item))
        return out

    async def resolve_watch(
        self,
        session: SavedSession,
        client: dict[str, str],
        airing: Airing,
    ) -> Airing:
        if airing.watch_id():
            return airing
        entity = airing.entity_id
        if not entity:
            return airing
        try:
            payload = await self._browse(session, client, body={"browseId": entity})
        except MineError as exc:
            if _session_expired(exc):
                raise
            return airing
        for found in parse_browse(payload, source=airing.source):
            watch = found.watch_id()
            if not watch:
                continue
            return replace(
                airing,
                video_id=watch,
                title=airing.title or found.title,
                deeplink=f"https://tv.youtube.com/watch/{watch}",
                sport=airing.sport or found.sport,
                channel=airing.channel or found.channel,
            )
        return airing

    async def _browse(
        self,
        session: SavedSession,
        client: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "context": {
                "client": {
                    "clientName": client["name"],
                    "clientVersion": client["version"],
                    "hl": "en",
                    "gl": "US",
                    "utcOffsetMinutes": -240,
                    "timeZone": "America/New_York",
                    "platform": "DESKTOP",
                    "unpluggedAppInfo": {"filterModeType": "1"},
                }
            },
            **body,
        }
        if self.visitor_data:
            payload["context"]["client"]["visitorData"] = self.visitor_data
        url = client["host"] + client["path"]
        if client.get("query"):
            url += "?" + client["query"]
        headers = innertube_headers(session.cookies, client)
        if self.visitor_data:
            headers["X-Goog-Visitor-Id"] = self.visitor_data
        async with self._http_sema():
            response = await self.http.post(url, json=payload, headers=headers, timeout=45)
        if response.status_code in {401, 403}:
            raise MineError("YTTV session expired. Sign in again on tv.youtube.com.")
        if response.status_code >= 400:
            raise MineError(_http_error(client["name"], url, response))
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise MineError(f"{client['name']} returned non-JSON") from exc
        if not isinstance(data, dict):
            raise MineError(f"{client['name']} returned an unexpected payload")
        visitor = (
            data.get("responseContext", {}).get("visitorData")
            if isinstance(data.get("responseContext"), dict)
            else None
        )
        if isinstance(visitor, str) and visitor:
            await self._set_visitor(visitor)
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("status") or "InnerTube error"
            raise MineError(str(message))
        return data


def _abort_if_expired(results: list[Any], errors: list[str]) -> bool:
    for item in results:
        if isinstance(item, Exception) and _session_expired(item):
            errors.append(str(item))
            return True
    return False


def _http_error(name: str, url: str, response: httpx.Response) -> str:
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("status") or "")
    except Exception:
        detail = ""
    suffix = f": {detail}" if detail else ""
    return f"{name} {url} returned HTTP {response.status_code}{suffix}"


def _continuation(payload: dict[str, Any]) -> Optional[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if found:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        token = node.get("continuation") or node.get("nextContinuationData")
        if isinstance(token, str) and len(token) > 20:
            found.append(token)
            return
        nested = node.get("continuationEndpoint")
        if isinstance(nested, dict):
            command = nested.get("continuationCommand") or nested
            if isinstance(command, dict) and isinstance(command.get("token"), str):
                found.append(str(command["token"]))
                return
        for value in node.values():
            walk(value)

    walk(payload)
    return found[0] if found else None
