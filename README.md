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

- Python 3.12+
- requests
- pydantic



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
data = HotelInfoDumpRequest(language='en')
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
# Optional rate limiting and caching
# PAPI_INFO_BUDGET=25                      # Max Hotel Info calls per search
# PAPI_HOTEL_CACHE_PATH=./.cache/hotel_info.sqlite  # Persistent Hotel Info cache
```

### 3. Run the development server

```bash
cd ./backend-ratehawk/
uvicorn server.main:app --reload --port 9000
```

Alternatively, if you prefer the FastAPI CLI:

```bash
fastapi run --app server.main:app
```

The automatic OpenAPI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Run with Docker Compose

If you would rather avoid installing Python locally, the repository includes a Docker setup. For local dev you can keep `--reload` and a bind mount; for production we run without reload and use a named cache volume (bound to port 9000):

```bash
cp .env.example .env  # make sure your credentials are filled in
docker compose up --build
```

The service will be available at [http://localhost:9000](http://localhost:9000). The compose file now starts uvicorn without `--reload` and no source bind mount; it mounts a named volume at `/app/.cache` to persist the hotel cache across container restarts.

If you keep a large RateHawk dump (e.g., ~3 GB) to prewarm the cache, do **not** commit it or the `.cache/` folder.
Store the dump outside git (e.g., `/data/ratehawk/partner_feed_dump.json.zst`) and prewarm via Compose:

```bash
# set PAPI_HOTEL_CACHE_PATH in .env (e.g., .cache/hotel_info.sqlite)
docker compose run --rm \
  -v /data/ratehawk/partner_feed_dump.json.zst:/data/partner_feed_dump.json.zst:ro \
  api python tools/import_dump_to_cache.py /data/partner_feed_dump.json.zst \
      --language en \
      --cache .cache/hotel_info.sqlite
```

After prewarm, you can start normally with `docker compose up`. For dev, feel free to temporarily add `--reload` and a bind mount to the service; for production, keep the current settings (no reload, no source bind).

On startup the container will attempt to pre-warm the Hotel Info cache if `PAPI_HOTEL_CACHE_PATH` is set
and the file is missing. It will call the dump endpoint using your credentials and import it.
To use sandbox, set `PAPI_BASE_PATH=https://api-sandbox.worldota.net/`.

### Available endpoints

- `GET /api/v1/healthz` – health check for monitoring.
- `GET /api/v1/locations/autocomplete?q=athens` – RateHawk multicomplete wrapper.
- `GET /api/v1/hotels/search?location_id=…&check_in=YYYY-MM-DD&check_out=YYYY-MM-DD&adults=2` – hotel search with pagination and filters (dates must be in ISO format, e.g. `2024-06-01`).
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

### Caching Hotel Info (recommended)

To avoid hitting per‑minute limits and speed up search results, the backend can persist Hotel Info payloads locally and reuse them across requests:

- Set `PAPI_HOTEL_CACHE_PATH` to a writable SQLite file (e.g. `./.cache/hotel_info.sqlite`).
- Optionally tune `PAPI_INFO_BUDGET` to cap Hotel Info requests per search.

With the cache enabled, search results hydrate from cached content first and only call the upstream API for missing hotels.

### Pre-warm cache from dump

You can import the ETG hotel dump into the local cache to avoid hitting limits on first runs:

- Install dependency: `pip install zstandard`
- Download a dump (or use an existing `.zst` file) following ETG’s documentation.
- Run the importer:

```bash
python tools/import_dump_to_cache.py partner_feed_en.json.zst --language en --cache ./.cache/hotel_info.sqlite
```

Use `--limit N` to import only the first N hotels for testing.

Alternatively, fetch the dump via API and import in one step:

```bash
python tools/fetch_and_import_dump.py --language en --cache ./.cache/hotel_info.sqlite --out ./partner_feed_en.json.zst
```

#### Uploading a local dump to a remote VM (manual)

If you already have a `partner_feed_dump.json.zst` file on your local machine and need to use it on a remote VM:

**Option A – `scp` (CLI)**

```bash
scp /path/to/partner_feed_dump.json.zst root@<SERVER_IP>:/home/ratehawk_hotels_backend/data/
```

Ensure the directory exists on the VM:

```bash
ssh root@<SERVER_IP>
mkdir -p /home/ratehawk_hotels_backend/data
```

**Option B – WinSCP (Windows GUI)**

1. Open WinSCP  
2. Connect as `root@<SERVER_IP>`  
3. Go to `/home/ratehawk_hotels_backend/data/`  
4. Drag & drop the `partner_feed_dump.json.zst` file  

**Option C – `rsync` (for large files)**

```bash
rsync -avP /path/to/partner_feed_dump.json.zst   root@<SERVER_IP>:/home/ratehawk_hotels_backend/data/
```

#### Importing the uploaded dump into the cache (remote VM)

Once the dump is on the VM:

```bash
ssh root@<SERVER_IP>
cd /home/ratehawk_hotels_backend

docker compose run --rm   -v $(pwd)/data:/data   api python tools/import_dump_to_cache.py /data/partner_feed_dump.json.zst       --language en       --cache .cache/hotel_info.sqlite

docker compose up -d
```

Verify the cache file exists and is non-trivial:

```bash
docker compose exec api ls -lh .cache
docker compose exec api du -h .cache
```

#### Troubleshooting: DNS / `api.worldota.net` resolution

If the backend fails to fetch the dump automatically with an error like:

```text
Failed to resolve 'api.worldota.net' ([Errno -3] Temporary failure in name resolution)
```

you likely need to configure DNS for Docker.

On the VM:

```bash
sudo nano /etc/docker/daemon.json
```


Then restart Docker and your stack:

```bash
sudo systemctl restart docker
docker compose down
docker compose up -d
```

After that, the built-in script should work again:

```bash
docker compose run --rm api python tools/fetch_and_import_dump.py     --language en     --cache .cache/hotel_info.sqlite     --out /tmp/partner_feed_dump.json.zst
```

### Cache stats endpoint

You can monitor cache usage via:

- `GET /api/v1/cache/stats` → `{ enabled, path, count, lastUpdated, infoBudget }`
