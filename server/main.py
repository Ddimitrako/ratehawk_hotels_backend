"""FastAPI application exposing the RateHawk hotel search API."""
from datetime import date
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .ratehawk import RatehawkClientError, RatehawkService, handle_service_error
from .schemas import (
    HealthResponse,
    HotelDetails,
    LocationSuggestion,
    PaginatedHotels,
    PhotoCollection,
)


def create_app(settings: Settings) -> FastAPI:
    service = RatehawkService(settings)

    app = FastAPI(title="RateHawk Hotels API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def get_service() -> RatehawkService:
        return service

    @app.get("/api/v1/healthz", response_model=HealthResponse)
    async def healthcheck() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/api/v1/locations/autocomplete",
        response_model=List[LocationSuggestion],
        summary="Autocomplete locations by free text",
    )
    async def autocomplete(
        q: str = Query(..., min_length=2, description="Free text query"),
        language: Optional[str] = Query(None, description="Language code"),
        service: RatehawkService = Depends(get_service),
    ) -> List[LocationSuggestion]:
        try:
            return await run_in_threadpool(service.autocomplete, q, language)
        except RatehawkClientError as exc:  # pragma: no cover - defensive
            raise handle_service_error(exc)

    @app.get(
        "/api/v1/hotels/search",
        response_model=PaginatedHotels,
        summary="Search hotels for a given region",
    )
    async def search_hotels(
        location_id: int = Query(..., description="Region identifier returned by autocomplete"),
        check_in: date = Query(..., alias="check_in"),
        check_out: date = Query(..., alias="check_out"),
        adults: int = Query(2, ge=1),
        children: Optional[List[int]] = Query(None),
        currency: Optional[str] = Query(None),
        language: Optional[str] = Query(None),
        residency: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, alias="page_size"),
        min_price: Optional[float] = Query(None, ge=0),
        max_price: Optional[float] = Query(None, ge=0),
        stars: Optional[List[int]] = Query(None),
        amenities: Optional[List[str]] = Query(None),
        service: RatehawkService = Depends(get_service),
    ) -> PaginatedHotels:
        if check_out <= check_in:
            raise HTTPException(status_code=400, detail="check_out must be after check_in")

        try:
            return await run_in_threadpool(
                service.search_hotels,
                location_id=location_id,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                children=children,
                currency=currency,
                language=language,
                residency=residency,
                page=page,
                page_size=page_size,
                min_price=min_price,
                max_price=max_price,
                star_filter=stars,
                amenity_filter=amenities,
            )
        except RatehawkClientError as exc:  # pragma: no cover - defensive
            raise handle_service_error(exc)

    @app.get(
        "/api/v1/hotels/{hotel_id}",
        response_model=HotelDetails,
        summary="Hotel details",
    )
    async def hotel_details(
        hotel_id: str,
        language: Optional[str] = Query(None),
        service: RatehawkService = Depends(get_service),
    ) -> HotelDetails:
        try:
            return await run_in_threadpool(service.hotel_details, hotel_id, language)
        except RatehawkClientError as exc:  # pragma: no cover - defensive
            raise handle_service_error(exc)

    @app.get(
        "/api/v1/hotels/{hotel_id}/photos",
        response_model=PhotoCollection,
        summary="Hotel photos",
    )
    async def hotel_photos(
        hotel_id: str,
        language: Optional[str] = Query(None),
        service: RatehawkService = Depends(get_service),
    ) -> PhotoCollection:
        try:
            return await run_in_threadpool(service.hotel_photos, hotel_id, language)
        except RatehawkClientError as exc:  # pragma: no cover - defensive
            raise handle_service_error(exc)

    return app


settings = get_settings()
app = create_app(settings)
