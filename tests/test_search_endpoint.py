from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PAPI_AUTH_KEY", "1:test")

from fastapi.testclient import TestClient

from papi_sdk.models.hotel_info import HotelInfoResponse
from papi_sdk.models.search.region.b2b import B2BRegionResponse

from server.config import Settings
from server.main import create_app
from server.ratehawk import RatehawkService

from papi_sdk.tests.mocked_data.hotel_info import hotel_info_data
from papi_sdk.tests.mocked_data.search_hotels import b2b_hotels_response


class _DummySession:
    def post(self, url, json, timeout):  # pragma: no cover - autocomplete not used in this test
        raise NotImplementedError("Autocomplete is not mocked in this test")


class _FakeAPI:
    def __init__(self):
        self.session = _DummySession()

    def b2b_search_region(self, data, timeout):
        return B2BRegionResponse(**deepcopy(b2b_hotels_response))

    def get_hotel_info(self, data, timeout):
        return HotelInfoResponse(**deepcopy(hotel_info_data))


def test_search_endpoint_matches_mocked_payload(monkeypatch):
    fake_api = _FakeAPI()

    monkeypatch.setattr(
        RatehawkService,
        "_build_client",
        staticmethod(lambda settings: fake_api),
    )

    settings = Settings(papi_auth_key="1:test")
    app = create_app(settings)

    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Query the endpoint using the FastAPI test client
    client = TestClient(app)
    response = client.get(
        "/api/v1/hotels/search",
        params={
            "location_id": 438,
            "check_in": today.isoformat(),
            "check_out": tomorrow.isoformat(),
            "adults": 2,
            "page": 1,
            "page_size": 20,
        },
    )

    assert response.status_code == 200

    # Compare with the RatehawkService output for the same mocked data
    service: RatehawkService = app.state.ratehawk_service
    expected = service.search_hotels(
        location_id=438,
        check_in=today,
        check_out=tomorrow,
        adults=2,
        page=1,
        page_size=20,
    )

    assert response.json() == expected.dict(by_alias=True)
