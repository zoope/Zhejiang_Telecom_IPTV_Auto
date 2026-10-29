#!/usr/bin/env python3
"""Generate a personalized multicast + unicast catch-up M3U playlist."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

PLAYSEEK_TEMPLATE = "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"


def read_text(source: str) -> str:
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"User-Agent": "zhejiang-iptv-m3u-updater/1.0"})
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    return Path(source).read_text(encoding="utf-8-sig")


def clean_base(value: str) -> str:
    value = value.strip()
    # Scheme-only bases such as rtp:// are valid prefixes for relative M3U
    # sources and must not be collapsed to the invalid rtp:/ form.
    if value.endswith("://"):
        return value
    return value.rstrip("/") + "/"


def clean_stream_address(value: str, stream_base: str, fcc_address: str = "", fcc_type: str = "") -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        parts = urlsplit(value)
        stream = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    else:
        value = value.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        stream = stream_base + value
    if fcc_address:
        stream += ("&" if "?" in stream else "?") + "fcc=" + fcc_address
        if fcc_type:
            stream += "&fcc-type=" + fcc_type
    return stream


def clean_logo(value: str, logo_base: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return value
    return logo_base + value.lstrip("/")


def normalize_channel_name(value: str) -> str:
    return re.sub(r"(高清|标清|4K)$", "", value.strip())


def load_rows(csv_text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(csv_text.splitlines()))
    if not rows:
        raise ValueError("upstream CSV is empty")
    return rows


def build_unicast_index(rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    by_igmp: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        igmp = row.get("ChannelURL_igmp", "").strip()
        name = normalize_channel_name(row.get("ChannelName", ""))
        if igmp:
            by_igmp[igmp].append(row)
        if name:
            by_name[name].append(row)
    return by_igmp, by_name


def choose_unicast(multicast_row: dict[str, str], by_igmp: dict[str, list[dict[str, str]]], by_name: dict[str, list[dict[str, str]]]) -> dict[str, str] | None:
    candidates = by_igmp.get(multicast_row.get("播放地址", "").strip(), [])
    if not candidates:
        candidates = by_name.get(normalize_channel_name(multicast_row.get("频道名称", "")), [])
    if not candidates:
        return None
    resolution = multicast_row.get("分辨率", "").strip()
    same_resolution = [row for row in candidates if row.get("Resolution", "").strip() == resolution]
    return (same_resolution or candidates)[0]


def build_catchup_source(
    unicast_row: dict[str, str] | None,
    host_override: str = "",
    channel_name: str = "",
    catchup_override_channels: set[str] | None = None,
    catchup_exclude_channels: set[str] | None = None,
    allow_missing_timeshift: bool = False,
) -> str:
    if not unicast_row:
        return ""
    rtsp = unicast_row.get("ChannelURL_rtsp", "").strip()
    if not rtsp:
        return ""
    # Keep existing catch-up entries controlled by the upstream TimeShift
    # flag.  Some channels have a usable RTSP replay resource even though the
    # report leaves TimeShift empty or zero; the config can opt those entries
    # in without changing the already-published URLs for flagged channels.
    replay_flag = unicast_row.get("TimeShift", "").strip() == "1"
    replay_override = normalize_channel_name(channel_name) in (catchup_override_channels or set())
    if normalize_channel_name(channel_name) in (catchup_exclude_channels or set()):
        return ""
    if not replay_flag and not replay_override and not allow_missing_timeshift:
        return ""
    parts = urlsplit(rtsp)
    netloc = parts.netloc
    if host_override:
        port = f":{parts.port}" if parts.port else ""
        netloc = host_override + port
    # Existing replay URLs are known to work as published. Newly added
    # entries are the channels whose RTSP resource exists but whose TimeShift
    # flag is empty; those resources use the TVOD namespace. Jilin remains an
    # explicit override even if its upstream metadata changes.
    use_tvod = (not replay_flag and allow_missing_timeshift) or replay_override
    if use_tvod:
        replay_path = parts.path.replace("/PLTV/", "/TVOD/", 1)
    else:
        replay_path = parts.path
    base = urlunsplit((parts.scheme, netloc, replay_path, "", ""))
    return f"{base}?playseek={PLAYSEEK_TEMPLATE}"


def generate(config: dict[str, str], csv_source: str | None = None, unicast_source: str | None = None) -> str:
    multicast_source = csv_source or config["source_csv"]
    unicast_source = unicast_source or config.get("unicast_csv", "")
    multicast_rows = load_rows(read_text(multicast_source))
    unicast_rows = load_rows(read_text(unicast_source)) if unicast_source else []
    by_igmp, by_name = build_unicast_index(unicast_rows)

    stream_base = clean_base(config["stream_base_url"])
    logo_base = clean_base(config["logo_base_url"])
    epg_url = config["epg_url"].strip()
    fcc_address = config.get("fcc_address", "").strip()
    fcc_type = config.get("fcc_type", "").strip()
    unicast_rtsp_host_override = config.get("unicast_rtsp_host_override", "").strip()
    allow_missing_timeshift = bool(config.get("catchup_from_rtsp_without_timeshift", False))
    catchup_override_channels = {
        normalize_channel_name(value)
        for value in config.get("catchup_override_channels", [])
        if str(value).strip()
    }
    catchup_exclude_channels = {
        normalize_channel_name(value)
        for value in config.get("catchup_exclude_channels", [])
        if str(value).strip()
    }
    output: list[str] = [f'#EXTM3U x-tvg-url="{epg_url}"']

    for row in multicast_rows:
        channel = row.get("频道名称", "").strip()
        if not channel:
            continue
        tvg_id = (row.get("tvg-id") or channel).strip()
        tvg_name = (row.get("tvg-name") or channel).strip()
        category = row.get("频道分类", "").strip()
        logo = clean_logo(row.get("Logo链接", ""), logo_base)
        stream = clean_stream_address(row.get("播放地址", ""), stream_base, fcc_address, fcc_type)
        if not stream:
            continue
        catchup_source = build_catchup_source(
            choose_unicast(row, by_igmp, by_name),
            unicast_rtsp_host_override,
            channel,
            catchup_override_channels,
            catchup_exclude_channels,
            allow_missing_timeshift,
        )
        catchup_attrs = f' catchup="default" catchup-source="{catchup_source}"' if catchup_source else ""
        output.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" '
            f'tvg-logo="{logo}" group-title="{category}"{catchup_attrs},{channel}'
        )
        output.append(stream)

    return "\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--csv", help="optional local multicast CSV path")
    parser.add_argument("--unicast-csv", help="optional local unicast CSV path")
    parser.add_argument("--output", help="override output path")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_path = Path(args.output or config.get("output", "Zhejiang_Telecom_IPTV.m3u"))
    content = generate(config, args.csv, args.unicast_csv)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    entries = content.count("#EXTINF")
    catchups = sum(1 for line in content.splitlines() if 'catchup-source="rtsp://' in line)
    print(f"wrote {output_path}: {entries} channels, {catchups} unicast catch-up sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
