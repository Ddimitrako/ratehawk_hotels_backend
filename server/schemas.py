"""Pydantic schemas returned by the FastAPI endpoints."""
from typing import List, Optional

from pydantic import BaseModel, Field


class LocationSuggestion(BaseModel):
    """Autocomplete suggestion for a city/region."""

    id: int = Field(..., description="Internal RateHawk region identifier")
    name: str
    type: Optional[str] = Field(None, description="Region type returned by RateHawk")
    country: Optional[str] = Field(None, description="Country name if provided")
    country_code: Optional[str] = Field(None, description="ISO country code")


class Price(BaseModel):
    per_night: Optional[float] = Field(
        None,
        alias="perNight",
        description="Average price per night (converted to float).",
    )
    currency: Optional[str] = None
    total: Optional[float] = Field(None, description="Total stay cost (if available)")

    class Config:
        allow_population_by_field_name = True


class Location(BaseModel):
    city: Optional[str] = None
    country: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class HotelSummary(BaseModel):
    id: str
    name: str
    rating: Optional[float] = Field(None, description="Guest rating mapped from RateHawk quality score")
    stars: Optional[int] = None
    price: Price
    thumbnail: Optional[str] = None
    location: Location
    amenities: List[str]


class HotelDetails(HotelSummary):
    description: Optional[str] = None
    check_in: Optional[str] = Field(None, alias="checkIn")
    check_out: Optional[str] = Field(None, alias="checkOut")
    email: Optional[str] = None
    phone: Optional[str] = None
    postal_code: Optional[str] = Field(None, alias="postalCode")
    photos: List[str] = []

    class Config:
        allow_population_by_field_name = True


class PaginatedHotels(BaseModel):
    items: List[HotelSummary]
    page: int
    page_size: int = Field(..., alias="pageSize")
    total: int

    class Config:
        allow_population_by_field_name = True


class PhotoCollection(BaseModel):
    hotel_id: str = Field(..., alias="hotelId")
    photos: List[str]

    class Config:
        allow_population_by_field_name = True


class HealthResponse(BaseModel):
    status: str
