"""Wrapper around the pAPI SDK that exposes simplified hotel data."""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from fastapi import HTTPException

from papi_sdk.models.hotel_info import HotelInfoData, HotelInfoRequest
from papi_sdk.models.search.base_request import GuestsGroup
from papi_sdk.models.search.region.b2b import B2BRegionRequest

from .config import Settings
from .schemas import HotelDetails, HotelSummary, Location, LocationSuggestion, PaginatedHotels, PhotoCollection, Price


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
            residency=residency or self.settings.default_residency,
            guests=[guests_group],
        )

        response = self.api.b2b_search_region(data=request, timeout=self.settings.request_timeout)
        if response.error:
            raise RatehawkClientError(str(response.error))
        if not response.data:
            return PaginatedHotels(items=[], page=page, page_size=page_size, total=0)

        hotels = response.data.hotels or []
        filtered: List[HotelSummary] = []
        for hotel in hotels:
            price_info = self._select_price(hotel.rates)
            info = self._hotel_info(hotel_id=hotel.id, language=language)
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
            filtered.append(summary)

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = filtered[start:end]
        return PaginatedHotels(items=paginated_items, page=page, page_size=page_size, total=total)

    def hotel_details(self, hotel_id: str, language: Optional[str] = None) -> HotelDetails:
        info = self._hotel_info(hotel_id, language)
        if not info:
            raise RatehawkClientError(f"Hotel {hotel_id} not found")

        summary = self._build_hotel_summary(hotel_id, info, PriceInfo(None, None, None), [])

        return HotelDetails(
            **summary.dict(),
            description=self._build_description(info),
            check_in=info.check_in_time.isoformat() if info.check_in_time else None,
            check_out=info.check_out_time.isoformat() if info.check_out_time else None,
            email=info.email,
            phone=info.phone,
            postal_code=info.postal_code,
            photos=info.images or [],
        )

    def hotel_photos(self, hotel_id: str, language: Optional[str] = None) -> PhotoCollection:
        info = self._hotel_info(hotel_id, language)
        if not info:
            raise RatehawkClientError(f"Hotel {hotel_id} not found")
        return PhotoCollection(hotelId=hotel_id, photos=info.images or [])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _hotel_info(self, hotel_id: str, language: Optional[str]) -> Optional[HotelInfoData]:
        lang = language or self.settings.default_language
        cache_key = (hotel_id, lang)
        if cache_key in self._info_cache:
            return self._info_cache[cache_key]

        request = HotelInfoRequest(id=hotel_id, language=lang)
        response = self.api.get_hotel_info(data=request, timeout=self.settings.request_timeout)
        if response.error:
            raise RatehawkClientError(str(response.error))
        if not response.data:
            return None
        self._info_cache[cache_key] = response.data
        return response.data

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

        thumbnail = info.images[0] if info.images else None
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
