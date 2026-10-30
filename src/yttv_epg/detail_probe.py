"""Read-only game-detail diagnostics; deliberately does not classify broadcasts."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

import httpx

from yttv_epg.config import settings
from yttv_epg.crypto import decrypt
from yttv_epg.innertube import CLIENTS, InnerTubeClient, MineError
from yttv_epg.session_store import SavedSession


RENDERERS = {
    "unpluggedContentDetailsHeaderRenderer",
    "unpluggedContentDetailsAboutFieldsRenderer",
    "unpluggedCompactVideoRenderer",
    "unpluggedCompactVideoVersionRenderer",
    "unpluggedGameCardRenderer",
    "unpluggedVideoMetadataRenderer",
}
FIELDS = {
    "title", "contentType", "primaryText", "secondaryText", "description",
    "attributes", "badge", "badges", "startTimeSeconds", "endTimeSeconds",
    "startTime", "endTime", "navigationEndpoint",
}
NESTED_FIELDS = {
    "runs", "text", "simpleText", "label", "type",
    "unpluggedTextBadgeRenderer", "browseEndpoint", "browseId",
    "watchEndpoint", "videoId",
}


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_value(item) for key, item in value.items() if key in NESTED_FIELDS}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def summarize_details(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain observed programme fields, excluding account data and tracking tokens."""
    records = []

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                location = f"{path}/{key}"
                if key in RENDERERS and isinstance(item, dict):
                    records.append({
                        "path": location,
                        "renderer": key,
                        "fields": {name: _safe_value(field) for name, field in item.items() if name in FIELDS},
                    })
                walk(item, location)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}/{index}")

    walk(payload)
    return records


def detail_id_from_watch(payload: dict[str, Any]) -> str:
    # Only the watched programme's metadata is evidence. Recommendations and
    # stationNavigationEndpoint can point to unrelated games or network hubs.
    candidates = set()
    for record in summarize_details(payload):
        if record["renderer"] != "unpluggedVideoMetadataRenderer":
            continue
        endpoint = record["fields"].get("navigationEndpoint", {}).get("browseEndpoint", {})
        if endpoint.get("browseId"):
            candidates.add(endpoint["browseId"])
    if len(candidates) != 1:
        raise ValueError("Watch metadata did not identify one unambiguous game detail page")
    return candidates.pop()


async def capture_details(client: InnerTubeClient, session: SavedSession, *,
                          browse_id: str | None = None, video_id: str | None = None) -> dict[str, Any]:
    if bool(browse_id) == bool(video_id):
        raise ValueError("Provide exactly one browse ID or video ID")
    watch_metadata = []
    if video_id:
        payload = await client._browse(session, {**CLIENTS[0], "path": "/youtubei/v1/next"},
                                       body={"videoId": video_id})
        browse_id = detail_id_from_watch(payload)
        watch_metadata = [record for record in summarize_details(payload)
                          if record["renderer"] == "unpluggedVideoMetadataRenderer"]
    payload = await client._browse(session, CLIENTS[0], body={"browseId": browse_id})
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "browse_id": browse_id,
        "video_id": video_id,
        "watch_metadata": watch_metadata,
        "details": summarize_details(payload),
    }


def _load_session() -> SavedSession:
    # Read only: do not create a secret, rewrite a session, or import app state.
    secret = settings.secret.strip() or (settings.data_dir / ".secret").read_text().strip()
    data = json.loads(decrypt(secret, (settings.data_dir / "session.enc").read_bytes()))
    session = SavedSession.from_dict(data)
    if session is None or not session.cookies:
        raise ValueError("No saved session cookies; capture a session in the dashboard first")
    # This explicit diagnostic uses the saved cookie snapshot, never browser
    # navigation, playback, watch-history writes, or automatic session renewal.
    return SavedSession(kind="cookies", cookies=session.cookies)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--browse-id", help="YouTube TV game detail browse ID")
    group.add_argument("--video-id", help="Watch ID; resolves its game detail page first")
    args = parser.parse_args()
    identifier = args.browse_id or args.video_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
        parser.error("Expected an ID, not a URL")

    async def run() -> dict[str, Any]:
        session = _load_session()
        async with httpx.AsyncClient(timeout=45) as http:
            return await capture_details(InnerTubeClient(http), session,
                                         browse_id=args.browse_id, video_id=args.video_id)

    try:
        result = asyncio.run(run())
    except (OSError, ValueError, MineError, httpx.HTTPError):
        # Avoid echoing provider error bodies or authentication details.
        print("Capture failed. Check the ID, connectivity, and saved session; refresh the session in the dashboard if needed.", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
