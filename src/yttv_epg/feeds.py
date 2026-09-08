from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape

from yttv_epg.branding import PRODUCT_NAME, SOURCE_NAME
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing


def lane_id(lane: int) -> str:
    return f"yttv-sports-{lane}"


def lane_name(lane: int) -> str:
    return f"YTTV Sports {lane}"


def xmltv(assignments: list[LaneAssignment], lane_count: int) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<tv generator-info-name="{escape(PRODUCT_NAME)}">',
    ]
    for lane in range(1, lane_count + 1):
        cid = escape(lane_id(lane))
        lines.append(f'  <channel id="{cid}">')
        lines.append(f"    <display-name>{escape(lane_name(lane))}</display-name>")
        lines.append("  </channel>")
    for row in assignments:
        if not row.airing.watch_id():
            continue
        start = _xmltv_time(row.airing.start)
        stop = _xmltv_time(row.airing.end)
        cid = escape(lane_id(row.lane))
        lines.append(f'  <programme start="{start}" stop="{stop}" channel="{cid}">')
        lines.append(f"    <title>{escape(row.airing.title)}</title>")
        if row.airing.station and row.airing.station != row.airing.title:
            lines.append(f"    <sub-title>{escape(row.airing.station)}</sub-title>")
        lines.append(f"    <category>{escape(row.airing.sport or 'Sports')}</category>")
        if row.airing.channel:
            lines.append(f"    <category>{escape(row.airing.channel)}</category>")
        if row.airing.deeplink:
            lines.append(f"    <url>{escape(row.airing.deeplink)}</url>")
        lines.append("  </programme>")
    lines.append("</tv>")
    return "\n".join(lines) + "\n"


def m3u(
    *,
    base_url: str,
    lane_count: int,
    start_channel: int,
    package_name: str,
    alternate_package_name: str,
) -> str:
    root = base_url.rstrip("/")
    lines = ["#EXTM3U"]
    for lane in range(1, lane_count + 1):
        number = start_channel + lane - 1
        url = (
            f"{root}/whatson/{lane}?format=json&include=deeplink"
            "&dynamic_url_json_key=deeplink_url"
        )
        lines.append(
            f'#EXTINF:-1 tvg-id="{lane_id(lane)}" tvg-chno="{number}" '
            f'tvg-name="{lane_name(lane)}" channel-id="{lane_id(lane)}" '
            f'package-name="{package_name}" '
            f'alternate-package-name="{alternate_package_name}",'
            f"{lane_name(lane)}"
        )
        lines.append(url)
    return "\n".join(lines) + "\n"


def apituner_export(
    *,
    base_url: str,
    lane_count: int,
    start_channel: int,
    package_name: str,
    alternate_package_name: str,
) -> list[dict[str, str | int]]:
    root = base_url.rstrip("/")
    rows: list[dict[str, str | int]] = []
    for lane in range(1, lane_count + 1):
        rows.append(
            {
                "number": start_channel + lane - 1,
                "name": lane_name(lane),
                "provider_name": "youtube_tv",
                "package_name": package_name,
                "alternate_package_name": alternate_package_name,
                "url": (
                    f"{root}/whatson/{lane}?format=json&include=deeplink"
                    "&dynamic_url_json_key=deeplink_url"
                ),
                "action": "android.intent.action.VIEW",
                "source": SOURCE_NAME,
            }
        )
    return rows


def whatson_payload(lane: int, airing: Airing | None) -> dict:
    if airing is None:
        return {"ok": False, "lane": lane, "deeplink_url": None}
    if not airing.deeplink:
        return {
            "ok": False,
            "lane": lane,
            "deeplink_url": None,
            "title": airing.title,
            "station": airing.station,
            "sport": airing.sport,
        }
    return {
        "ok": True,
        "lane": lane,
        "deeplink_url": airing.deeplink,
        "url": airing.deeplink,
        "deeplink": airing.deeplink,
        "video_id": airing.watch_id() or airing.video_id,
        "title": airing.title,
        "station": airing.station,
        "sport": airing.sport,
        "start": airing.start.astimezone(timezone.utc).isoformat(),
        "end": airing.end.astimezone(timezone.utc).isoformat(),
    }


def _xmltv_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")
