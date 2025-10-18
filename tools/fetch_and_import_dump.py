#!/usr/bin/env python3
"""
Fetch the ETG hotel dump URL via API and import into the local cache.

This wraps two actions:
 1) Calls /api/b2b/v3/hotel/info/dump/ with Basic Auth using credentials from env
 2) Streams the .zst dump to disk and imports it into the cache

Usage:
  python tools/fetch_and_import_dump.py --language en --cache ./.cache/hotel_info.sqlite --out ./partner_feed_en.json.zst
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from server.config import Settings
from tools.import_dump_to_cache import main as import_main  # reuse importer CLI


def fetch_dump_url(base: str, key_id: str, api_key: str, language: str, inventory: str) -> str:
    url = base.rstrip("/") + "/api/b2b/v3/hotel/info/dump/"
    payload = {"inventory": inventory, "language": language}
    r = requests.post(url, auth=(key_id, api_key), json=payload, timeout=60)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        msg = r.text[:1000]
        raise SystemExit(f"HTTP {r.status_code} for dump endpoint: {msg}") from e
    data = r.json()
    if data.get("error"):
        raise SystemExit(f"dump endpoint error: {data['error']}")
    dump_url = data.get("data", {}).get("url")
    if not dump_url:
        raise SystemExit("No URL in dump response")
    return dump_url


def download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB
                if chunk:
                    f.write(chunk)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Fetch ETG hotel dump and import into local cache")
    ap.add_argument("--language", default=os.environ.get("PAPI_DEFAULT_LANGUAGE") or "en")
    ap.add_argument("--inventory", default="all", choices=["all", "partner"], help="Dump inventory scope (default: all)")
    ap.add_argument("--out", dest="out_path", default="partner_feed_dump.json.zst", help="Where to save the downloaded dump")
    ap.add_argument("--cache", dest="cache_path", help="SQLite cache path (default from env PAPI_HOTEL_CACHE_PATH)")
    ap.add_argument("--sandbox", action="store_true", help="Use sandbox host")
    ap.add_argument("--limit", type=int, help="Import only first N hotels")
    args = ap.parse_args()

    settings = Settings()
    key_id, api_key = settings.auth_tuple()
    host = (settings.base_path or "https://api.worldota.net/").rstrip("/")
    if args.sandbox:
        host = "https://api-sandbox.worldota.net"

    print(f"Fetching dump URL from {host} for language={args.language}…")
    dump_url = fetch_dump_url(host, key_id, api_key, args.language, args.inventory)
    print(f"Dump URL: {dump_url}")

    out_path = Path(args.out_path)
    print(f"Downloading to {out_path}… (this may take a while)")
    download(dump_url, out_path)
    print("Download complete. Importing into cache…")

    # Chain to the importer
    sys.argv = [
        "import_dump_to_cache.py",
        str(out_path),
        "--language",
        args.language,
    ] + (["--cache", args.cache_path] if args.cache_path else []) + (["--limit", str(args.limit)] if args.limit else [])
    import_main()


if __name__ == "__main__":
    main()
