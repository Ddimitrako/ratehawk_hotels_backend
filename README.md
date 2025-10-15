# pAPI SDK

![main workflow](https://github.com/emergingtravel/papi-sdk-python/workflows/Main/badge.svg)
![pypi version](https://img.shields.io/pypi/v/papi-sdk.svg)
![pypi downloads](https://img.shields.io/pypi/dm/papi-sdk.svg)
![python versions](https://img.shields.io/pypi/pyversions/papi-sdk.svg)
![license](https://img.shields.io/github/license/emergingtravel/papi-sdk-python.svg)

pAPI SDK is a python SDK for [ETG APIv3](https://docs.emergingtravel.com/).
The abbreviation "pAPI" stands for "Partner API". 
To know more about the benefits of our API integration or to sign up please check our [website](https://www.ratehawk.com/lp/en/API).

## Requirements

- Python 3.8+
- requests
- pydantic

## Installation

```
pip install papi-sdk
```

## Quickstart

To start using ETG APIv3 you need a key, which you received after registration. 
A key is a combination of an `id` and `uuid`. These are passed into each request as a Basic Auth header after initialization.
`APIv3` supports all arguments provided by [requests](https://github.com/psf/requests), ex. `timeout`.

```python
from papi_sdk import APIv3


papi = APIv3(key='1000:022a2cf1-d279-02f3-9c3c-596aa09b827b', timeout=15)
```

Then you can use all available methods. Say you want to check an overview of the available methods (which is `api/b2b/v3/overview` endpoint), you do:

```python
overview = papi.overview(timeout=1)
```

Another example is downloading hotels dump with `api/b2b/v3/hotel/info/dump` endpoint:

```python
data = HotelInfoDumpRequest(language='ru')
dump = papi.get_hotel_info_dump(data=data)
print(dump.data.url)
```

Note: if you don't provide your headers and specifically your `User-Agent` in requests options then it will be automatically added, ex. `papi-sdk/v1.0.2 requests/2.25.1 (python/3.8)`

## FastAPI backend quickstart

This repository now also includes a FastAPI service (`server/`) that wraps the SDK and exposes
REST endpoints tailored for the [React booking frontend](https://github.com/Dev-Dz27/React-booking).

### 1. Install dependencies

```bash
poetry install
```

The project targets Python 3.8+. If you prefer `pip`, create a virtual environment and install
the dependencies from `pyproject.toml`.

### 2. Configure credentials

Create a `.env` file in the project root (never commit your real credentials):

```env
# Either provide the combined token…
PAPI_AUTH_KEY=12345:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# …or split id/secret if you prefer
# PAPI_KEY_ID=12345
# PAPI_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Optional tweaks
PAPI_DEFAULT_LANGUAGE=en
PAPI_DEFAULT_CURRENCY=EUR
FRONTEND_ORIGIN=http://localhost:3000
# PAPI_BASE_PATH=https://api-sandbox.worldota.net/
```

### 3. Run the development server

```bash
uvicorn server.main:app --reload
```

The automatic OpenAPI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Available endpoints

- `GET /api/v1/healthz` – health check for monitoring.
- `GET /api/v1/locations/autocomplete?q=athens` – RateHawk multicomplete wrapper.
- `GET /api/v1/hotels/search?location_id=…&check_in=…&check_out=…&adults=2` – hotel search with pagination and filters.
- `GET /api/v1/hotels/{hotel_id}` – detailed hotel description enriched with amenities.
- `GET /api/v1/hotels/{hotel_id}/photos` – image gallery for the selected hotel.

All responses are shaped for the React booking UI, for example search results look like:

```json
{
  "id": "hotel_slug",
  "name": "Hotel Example",
  "rating": 4.5,
  "stars": 4,
  "price": {"perNight": 120.0, "currency": "EUR"},
  "thumbnail": "https://…",
  "location": {"city": "Athens", "country": "GR"},
  "amenities": ["wifi", "ac"]
}
```

The FastAPI application enables the React frontend to render hotel lists, detail pages, and photo galleries using live data from the RateHawk pAPI.
