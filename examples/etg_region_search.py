#!/usr/bin/env python3
"""
ETG (Emerging Travel Group / RateHawk) - Find region_id via multicomplete and run Search by Region (SERP).

Usage examples:

  # Sandbox, search Athens, Greece, 2 adults for next weekend (defaults)
  python etg_region_search.py --sandbox --query "Athens" --country GR

  # Prod, specific dates & currency
  python etg_region_search.py --query "Thessaloniki" --country GR --checkin 2025-11-10 --checkout 2025-11-12 --currency EUR

  # Provide API credentials via env:
  set ETG_KEY_ID=YOUR_ID
  set ETG_API_KEY=YOUR_UUID
"""

import os
import sys
import json
import argparse
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_LANGUAGE = "en"
DEFAULT_CURRENCY = "EUR"
DEFAULT_ADULTS = 2


def dprint(*args, **kwargs):
    if os.environ.get("DEBUG"):
        print("[DEBUG]", *args, **kwargs)


def api_base(sandbox: bool) -> str:
    return "https://api-sandbox.worldota.net" if sandbox else "https://api.worldota.net"


def api_post(
    host: str,
    key_id: str,
    api_key: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = host.rstrip("/") + path
    dprint("POST", url, "payload=", payload)
    r = requests.post(url, auth=(key_id, api_key), json=payload or {}, timeout=timeout)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        text = r.text[:1000]
        raise SystemExit(f"HTTP {r.status_code} for {url} → {text}") from e
    try:
        data = r.json()
    except Exception:
        raise SystemExit(f"Non-JSON response from {url}: {r.text[:500]}")
    return data


def api_get(
    host: str,
    key_id: str,
    api_key: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = host.rstrip("/") + path
    dprint("GET", url, "params=", params)
    r = requests.get(url, auth=(key_id, api_key), params=params or {}, timeout=timeout)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        text = r.text[:1000]
        raise SystemExit(f"HTTP {r.status_code} for {url} → {text}") from e
    try:
        data = r.json()
    except Exception:
        raise SystemExit(f"Non-JSON response from {url}: {r.text[:500]}")
    return data


def overview(host: str, key_id: str, api_key: str) -> None:
    """Quick auth/health check."""
    resp = api_get(host, key_id, api_key, "/api/b2b/v3/overview/")
    if resp.get("error"):
        raise SystemExit(f"Overview error: {resp['error']}")
    print("✔ overview OK")


def date_or_default(checkin: Optional[str], checkout: Optional[str]) -> Tuple[str, str]:
    today = dt.date.today()
    # default: next weekend (Fri-Sun)
    days_ahead = (4 - today.weekday()) % 7  # 4 = Friday
    if days_ahead == 0:
        days_ahead = 7
    default_checkin = today + dt.timedelta(days=days_ahead)
    default_checkout = default_checkin + dt.timedelta(days=2)

    def parse(s: Optional[str]) -> Optional[dt.date]:
        if not s:
            return None
        return dt.datetime.strptime(s, "%Y-%m-%d").date()

    ci = parse(checkin) or default_checkin
    co = parse(checkout) or default_checkout
    if co <= ci:
        co = ci + dt.timedelta(days=1)
    return ci.isoformat(), co.isoformat()


def multicomplete(
    host: str,
    key_id: str,
    api_key: str,
    query: str,
    language: str = DEFAULT_LANGUAGE,
) -> List[Dict[str, Any]]:
    payload = {"query": query, "language": language}
    resp = api_post(host, key_id, api_key, "/api/b2b/v3/search/multicomplete/", payload)
    if resp.get("error"):
        raise SystemExit(f"multicomplete error: {resp['error']}")
    return resp.get("data", {}).get("regions", [])


def pick_region(
    regions: List[Dict[str, Any]],
    country_code: Optional[str],
    region_type: Optional[str],
) -> Optional[Dict[str, Any]]:
    # Normalize filters
    cc = country_code.upper() if country_code else None
    rt = region_type.lower() if region_type else None

    filtered = regions
    if cc:
        filtered = [r for r in filtered if r.get("country_code", "").upper() == cc]
    if rt:
        filtered = [r for r in filtered if r.get("type", "").lower() == rt]

    # Prefer exact name matches first, then first item
    if filtered:
        return filtered[0]
    return regions[0] if regions else None


def search_by_region(
    host: str,
    key_id: str,
    api_key: str,
    region_id: int,
    checkin: str,
    checkout: str,
    language: str,
    currency: str,
    adults: int,
    child_ages: Optional[List[int]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    guests: Dict[str, Any] = {"adults": adults}
    if child_ages:
        guests["children"] = [{"age": a} for a in child_ages]

    payload = {
        "region_id": region_id,
        "checkin": checkin,
        "checkout": checkout,
        "language": language,
        "currency": currency,
        "guests": [guests],
        # Optional knobs:
        # "sort": "popularity",
        # "page": 1,
        # "page_size": 20,
    }
    resp = api_post(host, key_id, api_key, "/api/b2b/v3/search/serp/region/", payload, timeout=timeout)
    return resp


def print_serp_summary(resp: Dict[str, Any], limit: int = 10) -> None:
    if resp.get("error"):
        print("❌ Search error:", resp["error"])
        return
    data = resp.get("data")
    if not data:
        print("⚠ Empty data payload. Full response:")
        print(json.dumps(resp, ensure_ascii=False, indent=2)[:2000])
        return

    total = data.get("total_hotels") or data.get("total")  # depending on schema
    hotels = data.get("hotels") or []
    print(f"✓ total_hotels: {total} | showing up to {min(limit, len(hotels))} items")
    for i, h in enumerate(hotels[:limit], 1):
        name = h.get("name") or h.get("hotel", {}).get("name")
        hid = h.get("id") or h.get("hotel", {}).get("id")
        price = None
        # Some schemas keep pricing under 'offers'/'min_price'; we attempt a few common places.
        if "min_price" in h:
            price = h.get("min_price")
        elif h.get("offers") and isinstance(h["offers"], list) and h["offers"]:
            price = h["offers"][0].get("payment_options", {}).get("payment_types", [{}])[0].get("show_amount")
        print(f"{i:02d}. {name} (id={hid})  price={price}")


def main():
    ap = argparse.ArgumentParser(description="ETG region_id lookup + Search by Region (SERP)")
    ap.add_argument("--sandbox", action="store_true", help="Use sandbox host (api-sandbox.worldota.net)")
    ap.add_argument("--query", required=True, help="Free text for multicomplete (e.g., 'Athens')")
    ap.add_argument("--country", help="Country code filter (e.g., GR)")
    ap.add_argument("--type", dest="region_type", help="Region type filter (e.g., City, Country, Neighborhood)")
    ap.add_argument("--language", default=DEFAULT_LANGUAGE, help="Language (default: en)")
    ap.add_argument("--currency", default=DEFAULT_CURRENCY, help="Currency (default: EUR)")
    ap.add_argument("--checkin", help="YYYY-MM-DD (default: next Friday)")
    ap.add_argument("--checkout", help="YYYY-MM-DD (default: next Sunday or +1 day)")
    ap.add_argument("--adults", type=int, default=DEFAULT_ADULTS, help="Number of adults (default: 2)")
    ap.add_argument("--child-age", action="append", type=int, help="Child age; repeat for multiple children")
    ap.add_argument("--limit", type=int, default=10, help="Max hotels to print (default: 10)")
    args = ap.parse_args()

    key_id = os.environ.get("ETG_KEY_ID") or os.environ.get("RH_KEY_ID") or "13784"
    api_key = os.environ.get("ETG_API_KEY") or os.environ.get("RH_API_KEY") or "72ff50e3-7d68-4f77-8969-6f5eaf2351d7"
    if not key_id or not api_key:
        print("Set your credentials via environment variables:")
        print("  set ETG_KEY_ID=YOUR_ID")
        print("  set ETG_API_KEY=YOUR_UUID")
        sys.exit(2)

    host = api_base(args.sandbox)

    # 0) sanity check
    print(f"Host: {host}")
    overview(host, key_id, api_key)

    # 1) find region candidates
    regions = multicomplete(host, key_id, api_key, args.query, args.language)
    if not regions:
        raise SystemExit(f"No regions found for query='{args.query}'")

    # 2) pick one
    picked = pick_region(regions, args.country, args.region_type)
    if not picked:
        raise SystemExit("No matching region after filters.")
    region_id = picked["id"]
    print(f"Chosen region: id={region_id} name='{picked.get('name')}' type={picked.get('type')} country={picked.get('country_code')}")

    # 3) dates
    checkin, checkout = date_or_default(args.checkin, args.checkout)
    print(f"Dates: {checkin} → {checkout} | language={args.language} | currency={args.currency}")

    # 4) run SERP
    resp = search_by_region(
        host=host,
        key_id=key_id,
        api_key=api_key,
        region_id=int(region_id),
        checkin=checkin,
        checkout=checkout,
        language=args.language,
        currency=args.currency,
        adults=args.adults,
        child_ages=args.child_age,
    )
    print_serp_summary(resp, limit=args.limit)


if __name__ == "__main__":
    main()
