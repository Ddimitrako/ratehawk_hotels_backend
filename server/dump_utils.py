from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

try:
    from zstandard import ZstdDecompressor  # type: ignore
    HAS_ZSTD = True
except Exception:  # pragma: no cover
    HAS_ZSTD = False


def iter_dump_lines(path: Path) -> Iterator[str]:
    """Yield JSON lines from a .zst or plain JSONL dump file."""
    if path.suffix == ".zst":
        if not HAS_ZSTD:
            raise SystemExit("Install 'zstandard' package to read .zst dumps: pip install zstandard")
        dctx = ZstdDecompressor()
        with open(path, "rb") as fh:
            with dctx.stream_reader(fh) as reader:
                prev = ""
                while True:
                    chunk = reader.read(2 ** 24)
                    if not chunk:
                        break
                    raw = chunk.decode("utf-8")
                    lines = raw.split("\n")
                    for i, line in enumerate(lines[:-1]):
                        if i == 0:
                            line = prev + line
                        if not line.strip():
                            continue
                        yield line
                    prev = lines[-1]
    else:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                yield line


def to_hotel_info_payload(h: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a dump hotel record to a HotelInfoResponse-like payload dict."""
    region = h.get("region") or {}
    amenity_groups: List[Dict[str, Any]] = h.get("amenity_groups") or []
    if isinstance(amenity_groups, dict):  # normalize if wrong shape
        amenity_groups = [amenity_groups]

    def _rooms():
        groups = h.get("room_groups") or []
        if not isinstance(groups, list):
            return []
        out = []
        for g in groups:
            if not isinstance(g, dict):
                continue
            out.append(
                {
                    "images": g.get("images") or [],
                    "name": g.get("name") or "",
                    "room_amenities": g.get("room_amenities") or [],
                    "room_group_id": g.get("room_group_id"),
                    "rg_ext": g.get("rg_ext") or {},
                }
            )
        return out

    payload = {
        "status": "ok",
        "error": None,
        "debug": None,
        "data": {
            "address": h.get("address") or "",
            "amenity_groups": [
                {
                    "amenities": ag.get("amenities") or [],
                    "group_name": ag.get("group_name"),
                }
                for ag in amenity_groups
                if isinstance(ag, dict)
            ],
            "check_in_time": h.get("check_in_time") or "15:00:00",
            "check_out_time": h.get("check_out_time") or "11:00:00",
            "description_struct": h.get("description_struct") or [],
            "email": h.get("email"),
            "id": h.get("id") or h.get("slug") or str(h.get("hid") or ""),
            "images": h.get("images") or [],
            "kind": h.get("kind") or "hotel",
            "latitude": float(h.get("latitude") or 0.0),
            "longitude": float(h.get("longitude") or 0.0),
            "name": h.get("name") or "",
            "metapolicy_struct": h.get("metapolicy_struct")
            or {
                "internet": [],
                "add_fee": [],
                "check_in_check_out": None,
                "children": [],
                "children_meal": [],
                "cradle": None,
                "deposit": [],
                "extra_bed": [],
                "meal": [],
                "no_show": None,
                "parking": [],
                "pets": [],
                "shuttle": [],
                "visa": None,
            },
            "phone": h.get("phone"),
            "policy_struct": h.get("policy_struct") or [],
            "postal_code": h.get("postal_code"),
            "region": {
                "country_code": region.get("country_code") or h.get("country_code") or "",
                "iata": region.get("iata"),
                "id": int(region.get("id") or 0),
                "name": region.get("name") or h.get("city") or "",
                "type": region.get("type") or "City",
            },
            "room_groups": _rooms(),
            "star_rating": int(h.get("star_rating") or 0),
            "serp_filters": h.get("serp_filters") or [],
            "is_closed": bool(h.get("is_closed") or False),
        },
    }
    return payload

