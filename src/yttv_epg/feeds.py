from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from xml.sax.saxutils import escape as xml_escape

from yttv_epg.branding import LOGO_PATH, PRODUCT_NAME, SOURCE_NAME
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import (
    Airing,
    GUIDE_ARTWORK_HEIGHT,
    GUIDE_ARTWORK_WIDTH,
    guide_artwork_url,
    is_poster_artwork,
)

ILLEGAL_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def lane_id(lane: int) -> str:
    return f"yttv-sports-{lane}"


def lane_name(lane: int) -> str:
    return f"YTTV Sports {lane}"


def logo_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{LOGO_PATH}"


def programme_icon(airing: Airing, base_url: str = "") -> str:
    if airing.artwork:
        return guide_artwork_url(airing.artwork) or airing.artwork
    return logo_url(base_url) if base_url else ""


def xmltv(assignments: list[LaneAssignment], lane_count: int, *, base_url: str = "") -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<tv generator-info-name="{_xml_attr(PRODUCT_NAME)}">',
    ]
    icon = logo_url(base_url) if base_url else ""
    for lane in range(1, lane_count + 1):
        cid = _xml_attr(lane_id(lane))
        lines.append(f'  <channel id="{cid}">')
        lines.append(f"    <display-name>{_xml_text(lane_name(lane))}</display-name>")
        if icon:
            lines.append(f'    <icon src="{_xml_attr(icon)}" />')
        lines.append("  </channel>")
    programmes = [
        row
        for row in assignments
        if 1 <= row.lane <= lane_count
        and row.airing.watch_id()
        and row.airing.end > row.airing.start
    ]
    programmes.sort(key=lambda row: (row.lane, row.airing.start, row.airing.title))
    for row in programmes:
        start = _xmltv_time(row.airing.start)
        stop = _xmltv_time(row.airing.end)
        cid = _xml_attr(lane_id(row.lane))
        lines.append(f'  <programme start="{start}" stop="{stop}" channel="{cid}">')
        lines.append(f"    <title>{_xml_text(row.airing.title)}</title>")
        if row.airing.station and row.airing.station != row.airing.title:
            lines.append(f"    <sub-title>{_xml_text(row.airing.station)}</sub-title>")
        desc = _programme_desc(row.airing)
        if desc:
            lines.append(f"    <desc>{_xml_text(desc)}</desc>")
        lines.append(f"    <category>{_xml_text(row.airing.sport or 'Sports')}</category>")
        if row.airing.channel:
            lines.append(f"    <category>{_xml_text(row.airing.channel)}</category>")
        if row.airing.deeplink:
            lines.append(f"    <url>{_xml_text(row.airing.deeplink)}</url>")
        icon_src = programme_icon(row.airing, base_url)
        if icon_src:
            if not row.airing.artwork or is_poster_artwork(row.airing.artwork):
                width, height = GUIDE_ARTWORK_WIDTH, GUIDE_ARTWORK_HEIGHT
            else:
                width = height = GUIDE_ARTWORK_HEIGHT
            lines.append(
                f'    <icon src="{_xml_attr(icon_src)}" width="{width}" height="{height}" />'
            )
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
    guide = f"{root}/xmltv.xml"
    lines = [f'#EXTM3U url-tvg="{guide}" x-tvg-url="{guide}"']
    for lane in range(1, lane_count + 1):
        number = start_channel + lane - 1
        url = (
            f"{root}/whatson/{lane}?format=json&include=deeplink"
            "&dynamic_url_json_key=deeplink_url"
        )
        lines.append(
            f'#EXTINF:-1 tvg-id="{lane_id(lane)}" tvg-chno="{number}" '
            f'tvg-name="{lane_name(lane)}" tvg-logo="{logo_url(root)}" '
            f'channel-id="{lane_id(lane)}" '
            f'group-title="YTTV Sports" '
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
                "tvg_id": lane_id(lane),
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
    payload = {
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
        "artwork": airing.artwork or LOGO_PATH,
    }
    return payload


def _programme_desc(airing: Airing) -> str:
    parts: list[str] = []
    for value in (airing.station, airing.sport, airing.channel):
        text = (value or "").strip()
        if text and text not in parts and text != airing.title:
            parts.append(text)
    return " · ".join(parts)


def _xmltv_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def _xml_clean(value: str) -> str:
    return ILLEGAL_XML_CHARS.sub("", (value or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " "))


def _xml_text(value: str) -> str:
    return xml_escape(_xml_clean(value))


def _xml_attr(value: str) -> str:
    return escape(_xml_clean(value), quote=True)
