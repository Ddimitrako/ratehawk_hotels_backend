"""Wrapper around the pAPI SDK that exposes simplified hotel data."""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
import logging
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from fastapi import HTTPException

from pydantic import ValidationError

from papi_sdk.endpoints.endpoints import Endpoint
from papi_sdk.models.hotel_info import HotelInfoData, HotelInfoRequest, HotelInfoResponse
from papi_sdk.models.search.base_request import GuestsGroup
from papi_sdk.models.search.region.b2b import B2BRegionRequest, B2BRegionResponse
from papi_sdk.models.search.hotelpage.b2b import B2BHotelPageRequest

from .config import Settings
from .hotel_cache import HotelInfoStore
from .schemas import (
    HotelDetails,
    HotelSummary,
    Location,
    LocationSuggestion,
    PaginatedHotels,
    PhotoCollection,
    Price,
    HotelOffers,
    OfferRoom,
    OfferOption,
    OfferPrice,
)


class RatehawkClientError(Exception):
    """Raised when the RateHawk API returns an unexpected error."""


@dataclass
class PriceInfo:
    total: Optional[Decimal]
    per_night: Optional[Decimal]
    currency: Optional[str]


class RatehawkService:
    """High level helper to interact with RateHawk pAPI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._info_cache: Dict[Tuple[str, str], HotelInfoData] = {}
        self.base_path = self._configure_base_path(settings.base_path)
        self.api = self._build_client(settings)
        self.session = self.api.session
        # Avoid hitting RateHawk per-minute limits for hotel info
        self._max_info_calls_per_search: int = settings.info_budget
        # Optional persistent cache for hotel info responses
        self._store: Optional[HotelInfoStore] = None
        if settings.hotel_cache_path:
            try:
                self._store = HotelInfoStore(settings.hotel_cache_path)
            except Exception as exc:  # pragma: no cover - defensive
                logging.getLogger(__name__).warning(
                    "Failed to init HotelInfoStore at %s: %s", settings.hotel_cache_path, exc
                )

    @staticmethod
    def _configure_base_path(base_path: Optional[str]) -> str:
        """Ensure the SDK endpoints use a custom base path when provided."""

        if base_path:
            normalized = base_path if base_path.endswith("/") else base_path + "/"
            os.environ["BASE_PATH"] = normalized
            # Reload endpoints + api modules so Enum values pick new BASE_PATH
            import papi_sdk.endpoints.endpoints as endpoints_module
            import papi_sdk.api_v3 as api_v3_module

            importlib.reload(endpoints_module)
            importlib.reload(api_v3_module)
            return normalized

        return os.environ.get("BASE_PATH", "https://api.worldota.net/")

    @staticmethod
    def _build_client(settings: Settings):
        from papi_sdk.api_v3 import APIv3

        return APIv3(key=settings.auth_header())

    # ------------------------------------------------------------------
    # Location lookup
    # ------------------------------------------------------------------
    def autocomplete(self, query: str, language: Optional[str] = None) -> List[LocationSuggestion]:
        if not query:
            return []

        payload = {"query": query, "language": language or self.settings.default_language}
        endpoint = self.base_path.rstrip("/") + "/api/b2b/v3/search/multicomplete/"
        try:
            response = self.session.post(endpoint, json=payload, timeout=self.settings.request_timeout)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise RatehawkClientError(f"Autocomplete request failed: {exc}") from exc

        data = response.json()
        if data.get("error"):
            raise RatehawkClientError(str(data["error"]))

        regions = data.get("data", {}).get("regions", [])
        suggestions: List[LocationSuggestion] = []
        for item in regions:
            suggestions.append(
                LocationSuggestion(
                    id=item.get("id"),
                    name=item.get("name") or item.get("full_name") or "",
                    type=item.get("type"),
                    country=item.get("country"),
                    country_code=item.get("country_code"),
                )
            )
        return suggestions

    # ------------------------------------------------------------------
    # Hotel search helpers
    # ------------------------------------------------------------------
    def search_hotels(
        self,
        *,
        location_id: int,
        check_in: date,
        check_out: date,
        adults: int,
        children: Optional[Sequence[int]] = None,
        currency: Optional[str] = None,
        language: Optional[str] = None,
        residency: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        star_filter: Optional[Iterable[int]] = None,
        amenity_filter: Optional[Iterable[str]] = None,
    ) -> PaginatedHotels:
        guests_group = GuestsGroup(
            adults=adults,
            children=list(children) if children else None,
        )

        request = B2BRegionRequest(
            region_id=location_id,
            checkin=check_in,
            checkout=check_out,
            currency=currency or self.settings.default_currency,
            language=language or self.settings.default_language,
            # Ensure residency is always provided; some upstreams require it
            residency=(residency or self.settings.default_residency or "US"),
            guests=[guests_group],
        )
        # Use low-level call to support page/page_size which SDK model doesn't include
        # Ensure dates are ISO strings for JSON serialization
        payload = request.dict(exclude_none=True)
        # Some upstreams expect offset/limit instead of page/page_size. Compute both for compatibility.
        offset = max(0, (page - 1) * page_size)
        payload.update({
            "checkin": check_in.isoformat(),
            "checkout": check_out.isoformat(),
            # Prefer offset/limit; leave page/page_size out to avoid ambiguity
            "offset": offset,
            "limit": page_size,
            "sort": "popularity",
        })
        raw = self.api._post_request(  # type: ignore[attr-defined]
            Endpoint.SEARCH_REGION.value,
            json=payload,
            timeout=self.settings.request_timeout,
        )
        response = B2BRegionResponse(**raw)
        if response.error:
            raise RatehawkClientError(str(response.error))
        if not response.data:
            return PaginatedHotels(items=[], page=page, page_size=page_size, total=0)

        hotels = response.data.hotels or []
        filtered: List[HotelSummary] = []
        # Increase budget for deeper pages to allow skipping enough accepted hotels, but cap to avoid overload
        info_budget = max(self._max_info_calls_per_search, (page + 1) * page_size)
        info_budget = min(info_budget, 500)
        # Manual paging guard in case upstream ignores offset/limit
        to_skip = max(0, (page - 1) * page_size)
        needed = page_size
        log = logging.getLogger(__name__)
        processed_all = True

        accepted_so_far = 0
        for hotel in hotels:
            # Short-circuit before making another hotel_info call if we've
            # already gathered enough accepted items for this page.
            if accepted_so_far >= (to_skip + needed) or len(filtered) >= needed:
                processed_all = False
                break
            # First, compute price info and apply price-only filters to avoid unnecessary info calls
            price_info = self._select_price(hotel.rates)
            if min_price is not None or max_price is not None:
                per_night = float(price_info.per_night) if price_info.per_night is not None else None
                if min_price is not None and (per_night is None or per_night < min_price):
                    continue
                if max_price is not None and (per_night is None or per_night > max_price):
                    continue

            if info_budget <= 0:
                # We've reached our per-request budget to avoid endpoint_exceeded_limit
                processed_all = False
                break

            try:
                info = self._hotel_info(hotel_id=hotel.id, language=language)
            except RatehawkClientError as exc:
                log.warning("hotel_info failed for id=%s: %s", hotel.id, exc)
                # If we've exceeded the upstream limit, stop early to return partial results faster
                if "endpoint_exceeded_limit" in str(exc):
                    processed_all = False
                    break
                continue
            finally:
                info_budget -= 1

            if not info:
                continue

            summary = self._build_hotel_summary(hotel.id, info, price_info, hotel.rates)

            if not self._passes_filters(
                summary,
                price_info,
                min_price=min_price,
                max_price=max_price,
                star_filter=star_filter,
                amenity_filter=amenity_filter,
            ):
                continue
            # Count accepted
            accepted_so_far += 1
            # Skip items that belong to previous pages
            if accepted_so_far <= to_skip:
                continue
            # Collect for this page
            filtered.append(summary)
            if len(filtered) >= needed:
                processed_all = False
                break

        # Prefer upstream total to keep correct pagination across pages
        total = getattr(response.data, "total_hotels", None) or len(hotels)
        # Upstream already returns the requested page; no additional slicing needed
        paginated_items = filtered
        return PaginatedHotels(items=paginated_items, page=page, page_size=page_size, total=total)

    def hotel_details(self, hotel_id: str, language: Optional[str] = None) -> HotelDetails:
        info = self._hotel_info(hotel_id, language)
        if not info:
            raise RatehawkClientError(f"Hotel {hotel_id} not found")

        summary = self._build_hotel_summary(hotel_id, info, PriceInfo(None, None, None), [])
        photos = self._normalize_images(getattr(info, "images", None))

        return HotelDetails(
            **summary.dict(),
            description=self._build_description(info),
            check_in=info.check_in_time.isoformat() if info.check_in_time else None,
            check_out=info.check_out_time.isoformat() if info.check_out_time else None,
            email=info.email,
            phone=info.phone,
            postal_code=info.postal_code,
            photos=photos,
        )

    def hotel_photos(self, hotel_id: str, language: Optional[str] = None) -> PhotoCollection:
        info = self._hotel_info(hotel_id, language)
        if not info:
            raise RatehawkClientError(f"Hotel {hotel_id} not found")
        photos = self._normalize_images(getattr(info, "images", None))
        return PhotoCollection(hotelId=hotel_id, photos=photos)

    def hotel_offers(
        self,
        *,
        hotel_id: str,
        check_in: date,
        check_out: date,
        adults: int,
        children: Optional[Sequence[int]] = None,
        currency: Optional[str] = None,
        language: Optional[str] = None,
        residency: Optional[str] = None,
    ) -> HotelOffers:
        guests_group = GuestsGroup(
            adults=adults,
            children=list(children) if children else None,
        )
        request = B2BHotelPageRequest(
            id=hotel_id,
            checkin=check_in,
            checkout=check_out,
            currency=currency or self.settings.default_currency,
            language=language or self.settings.default_language,
            residency=(residency or self.settings.default_residency or "US"),
            guests=[guests_group],
        )

        resp = self.api.b2b_search_hotel_page(data=request, timeout=self.settings.request_timeout)
        if resp.error:
            raise RatehawkClientError(str(resp.error))
        hotels = (resp.data.hotels if resp.data else []) or []
        if not hotels:
            return HotelOffers(hotelId=hotel_id, rooms=[])

        rooms_map: Dict[str, OfferRoom] = {}
        for rate in hotels[0].rates:
            room_name = getattr(rate, "room_name", None) or "Room"
            capacity = getattr(rate.rg_ext, "capacity", None) if getattr(rate, "rg_ext", None) else None
            amenities = getattr(rate, "amenities_data", None) or []
            price_info = self._select_price([rate])
            try:
                daily_prices = [float(p) for p in (rate.daily_prices or [])]
            except Exception:
                daily_prices = []

            refundable_until = None
            payment_type = None
            try:
                if rate.payment_options and rate.payment_options.payment_types:
                    pt = rate.payment_options.payment_types[0]
                    payment_type = pt.type
                    pen = pt.cancellation_penalties
                    if pen and pen.free_cancellation_before:
                        refundable_until = pen.free_cancellation_before
            except Exception:
                pass

            option = OfferOption(
                meal=getattr(rate, "meal", None),
                dailyPrices=daily_prices,  # type: ignore[arg-type]
                price=OfferPrice(
                    perNight=float(price_info.per_night) if price_info.per_night is not None else None,
                    total=float(price_info.total) if price_info.total is not None else None,
                    currency=price_info.currency,
                ),
                refundableUntil=refundable_until,  # type: ignore[arg-type]
                paymentType=payment_type,  # type: ignore[arg-type]
            )

            if room_name not in rooms_map:
                rooms_map[room_name] = OfferRoom(
                    name=room_name,
                    capacity=capacity,
                    amenities=amenities,
                    options=[option],
                )
            else:
                rooms_map[room_name].options.append(option)

        return HotelOffers(hotelId=hotel_id, rooms=list(rooms_map.values()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _hotel_info(self, hotel_id: str, language: Optional[str]) -> Optional[HotelInfoData]:
        lang = language or self.settings.default_language
        cache_key = (hotel_id, lang)
        if cache_key in self._info_cache:
            return self._info_cache[cache_key]

        # Try persistent cache first (if configured)
        if self._store:
            cached = self._store.get(hotel_id, lang)
            if cached:
                try:
                    # cached is expected to be a full HotelInfoResponse payload
                    response = HotelInfoResponse(**cached)
                    if response.data:
                        self._info_cache[cache_key] = response.data
                        return response.data
                except ValidationError:
                    # Try to sanitize and parse again
                    sanitized = self._sanitize_hotel_info_payload(cached)
                    try:
                        response = HotelInfoResponse(**sanitized)
                        if response.data:
                            self._info_cache[cache_key] = response.data
                            return response.data
                    except ValidationError:
                        # ignore corrupt cache entries
                        pass

        request = HotelInfoRequest(id=hotel_id, language=lang)
        try:
            response = self.api.get_hotel_info(data=request, timeout=self.settings.request_timeout)
        except ValidationError:
            raw = self.api._post_request(  # type: ignore[attr-defined]
                Endpoint.HOTEL_INFO.value,
                json=request.dict(exclude_none=True),
                timeout=self.settings.request_timeout,
            )
            sanitized = self._sanitize_hotel_info_payload(raw)
            try:
                response = HotelInfoResponse(**sanitized)
            except ValidationError as exc:
                # If still not parseable, surface a controlled error upstream
                raise RatehawkClientError(f"hotel_info payload invalid for {hotel_id}: {exc}") from exc
        # Persist successful responses (sanitize first to be safe)
        if self._store:
            try:
                payload = response.dict()
                payload = self._sanitize_hotel_info_payload(payload)
                self._store.set(hotel_id, lang, payload)
            except Exception:  # pragma: no cover - best-effort persistence
                pass
        if response.error:
            raise RatehawkClientError(str(response.error))
        if not response.data:
            return None
        self._info_cache[cache_key] = response.data
        return response.data

    @staticmethod
    def _sanitize_hotel_info_payload(raw: dict) -> dict:
        """Replace null collections with empty structures so Pydantic can parse."""

        data = raw.get("data")
        if not isinstance(data, dict):
            return raw

        room_groups = data.get("room_groups")
        if room_groups is None:
            data["room_groups"] = []
        elif isinstance(room_groups, list):
            for group in room_groups:
                if not isinstance(group, dict):
                    continue
                if group.get("images") is None:
                    group["images"] = []
                if group.get("room_amenities") is None:
                    group["room_amenities"] = []
                if group.get("rg_ext") is None:
                    group["rg_ext"] = {}

        if data.get("images") is None:
            data["images"] = []

        amenity_groups = data.get("amenity_groups")
        if amenity_groups is None:
            data["amenity_groups"] = []

        # Some hotels may return serp_filters as null; ensure it's a list
        if data.get("serp_filters") is None:
            data["serp_filters"] = []

        return raw

    @staticmethod
    def _select_price(rates) -> PriceInfo:
        best_amount: Optional[Decimal] = None
        best_currency: Optional[str] = None
        best_rate = None

        for rate in rates:
            for payment in rate.payment_options.payment_types:
                amount = payment.show_amount or payment.amount
                currency = payment.show_currency_code or payment.currency_code
                if amount is None:
                    continue
                if best_amount is None or amount < best_amount:
                    best_amount = amount
                    best_currency = currency
                    best_rate = rate

        if not best_amount:
            return PriceInfo(total=None, per_night=None, currency=best_currency)

        nights = len(best_rate.daily_prices) if best_rate and best_rate.daily_prices else None
        if nights:
            per_night = best_amount / Decimal(nights)
        else:
            per_night = best_amount

        return PriceInfo(total=best_amount, per_night=per_night, currency=best_currency)

    def _build_hotel_summary(
        self,
        hotel_id: str,
        info: HotelInfoData,
        price_info: PriceInfo,
        rates,
    ) -> HotelSummary:
        quality = None
        if rates:
            qualities = [
                r.rg_ext.quality
                for r in rates
                if getattr(r, "rg_ext", None) and r.rg_ext.quality is not None
            ]
            if qualities:
                quality = sum(qualities) / len(qualities)

        rating = round(float(quality) / 2, 1) if quality is not None else None
        amenities = sorted({amenity for group in info.amenity_groups for amenity in group.amenities})
        location = Location(
            city=info.region.name,
            country=info.region.country_code,
            address=info.address,
            latitude=info.latitude,
            longitude=info.longitude,
        )

        price = Price(
            per_night=float(price_info.per_night) if price_info.per_night is not None else None,
            currency=price_info.currency,
            total=float(price_info.total) if price_info.total is not None else None,
        )

        _images = self._normalize_images(getattr(info, "images", None))
        thumbnail = _images[0] if _images else None
        return HotelSummary(
            id=hotel_id,
            name=info.name,
            rating=rating,
            stars=info.star_rating,
            price=price,
            thumbnail=thumbnail,
            location=location,
            amenities=amenities,
        )

    @staticmethod
    def _normalize_images(images) -> list:
        out = []
        try:
            for p in (images or []):
                url = None
                if isinstance(p, str):
                    url = p
                elif isinstance(p, dict):
                    for key in ("url", "orig", "original", "large", "full", "thumb", "href"):
                        v = p.get(key)
                        if isinstance(v, str):
                            url = v
                            break
                if not url:
                    continue
                if url.startswith("//"):
                    url = "https:" + url
                # Replace templated size placeholders commonly returned by cdn.worldota.net
                if "cdn.worldota.net" in url:
                    for placeholder in ("%7Bsize%7D", "{size}", "%s"):
                        if placeholder in url:
                            url = url.replace(placeholder, "1024x768")
                if url.startswith("http://") or url.startswith("https://"):
                    out.append(url)
        except Exception:
            # best-effort normalization
            pass
        return out

    @staticmethod
    def _passes_filters(
        hotel: HotelSummary,
        price_info: PriceInfo,
        *,
        min_price: Optional[float],
        max_price: Optional[float],
        star_filter: Optional[Iterable[int]],
        amenity_filter: Optional[Iterable[str]],
    ) -> bool:
        per_night = float(price_info.per_night) if price_info.per_night is not None else None
        if min_price is not None and (per_night is None or per_night < min_price):
            return False
        if max_price is not None and (per_night is None or per_night > max_price):
            return False

        if star_filter is not None:
            allowed = set(int(s) for s in star_filter)
            if hotel.stars is None or hotel.stars not in allowed:
                return False

        if amenity_filter:
            amenities_lower = {amenity.lower() for amenity in hotel.amenities}
            required = {a.lower() for a in amenity_filter}
            if not required.issubset(amenities_lower):
                return False

        return True

    @staticmethod
    def _build_description(info: HotelInfoData) -> Optional[str]:
        paragraphs = []
        for item in info.description_struct:
            paragraphs.extend(item.paragraphs)
        return "\n\n".join(paragraphs) if paragraphs else None


def handle_service_error(exc: RatehawkClientError) -> HTTPException:
    """Convert Ratehawk client errors to HTTP responses."""

    return HTTPException(status_code=502, detail=str(exc))



