#!/usr/bin/env python3
"""
Import ETG hotel dump (.zst JSONL) into the local Hotel Info cache.

Usage examples:

  # Basic: import English dump into default cache path from env
  python tools/import_dump_to_cache.py partner_feed_en.json.zst --language en

  # Custom cache file and limit records (for testing)
  python tools/import_dump_to_cache.py partner_feed_en.json.zst --cache ./.cache/hotel_info.sqlite --language en --limit 5000

Notes:
 - Expects each line in the dump to be a single hotel object (JSON).
 - Fills required fields with safe defaults when missing.
 - Validates against HotelInfoResponse schema; invalid entries are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from server.hotel_cache import HotelInfoStore
from server.ratehawk import RatehawkService
from server.config import Settings
from server.dump_utils import iter_dump_lines, to_hotel_info_payload
from papi_sdk.models.hotel_info import HotelInfoResponse
from pydantic import ValidationError


def main():
    ap = argparse.ArgumentParser(description="Import hotel dump into local Hotel Info cache")
    ap.add_argument("dump", help="Path to .zst or JSONL dump file")
    ap.add_argument("--cache", dest="cache_path", help="SQLite cache path (default from env PAPI_HOTEL_CACHE_PATH)")
    ap.add_argument("--language", default=os.environ.get("PAPI_DEFAULT_LANGUAGE") or "en", help="Language code for cache key")
    ap.add_argument("--limit", type=int, help="Max hotels to import")
    args = ap.parse_args()

    settings = Settings()
    cache_path = args.cache_path or settings.hotel_cache_path or "./.cache/hotel_info.sqlite"
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)

    store = HotelInfoStore(cache_path)
    count = 0

    for line in iter_dump_lines(Path(args.dump)):
        try:
            h = json.loads(line)
        except Exception:
            continue
        payload = to_hotel_info_payload(h)
        # sanitize and validate
        payload = RatehawkService._sanitize_hotel_info_payload(payload)  # type: ignore[attr-defined]
        try:
            parsed = HotelInfoResponse(**payload)
        except ValidationError:
            # Skip entries that still can't be parsed
            continue
        hotel_id = parsed.data.id if parsed.data else None
        if not hotel_id:
            continue
        store.set(hotel_id, args.language, payload)
        count += 1
        if count % 1000 == 0:
            print(f"Imported {count} hotels…")
        if args.limit and count >= args.limit:
            break

    print(f"Done. Imported {count} hotels into {cache_path}")


if __name__ == "__main__":
    main()
