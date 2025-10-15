import importlib.util
from pathlib import Path
import sys
import types

import pytest

if importlib.util.find_spec("pydantic") is None:  # pragma: no cover - environment guard
    pytest.skip("pydantic is not installed", allow_module_level=True)

requests_stub = types.ModuleType("requests")
requests_stub.RequestException = Exception
sys.modules.setdefault("requests", requests_stub)

fastapi_stub = types.ModuleType("fastapi")


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):  # pragma: no cover - test shim
        self.status_code = status_code
        self.detail = detail


fastapi_stub.HTTPException = _HTTPException
sys.modules.setdefault("fastapi", fastapi_stub)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.ratehawk import RatehawkService


def test_sanitize_hotel_info_payload_handles_null_collections():
    raw = {
        "data": {
            "room_groups": [
                {
                    "images": None,
                    "room_amenities": None,
                    "rg_ext": None,
                },
                "not-a-dict",
            ],
            "images": None,
            "amenity_groups": None,
        }
    }

    sanitized = RatehawkService._sanitize_hotel_info_payload(raw)

    room_groups = sanitized["data"]["room_groups"]
    assert room_groups[0]["images"] == []
    assert room_groups[0]["room_amenities"] == []
    assert room_groups[0]["rg_ext"] == {}
    assert sanitized["data"]["images"] == []
    assert sanitized["data"]["amenity_groups"] == []


def test_sanitize_hotel_info_payload_accepts_missing_data():
    raw = {"foo": "bar"}

    assert RatehawkService._sanitize_hotel_info_payload(raw) is raw
