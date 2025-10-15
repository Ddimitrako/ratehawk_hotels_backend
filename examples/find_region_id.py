import base64

import requests
import tarfile
import json
import io

# Use the same credentials as your other scripts
KEY_ID = "13784"
API_KEY = "72ff50e3-7d68-4f77-8969-6f5eaf2351d7"


# keyId is the API key ID
# apiKey is the API key access token
def retrieve_dump(key_id, api_key):
    encoded_credentials = base64.b64encode(f"{key_id}:{api_key}".encode("ascii")).decode("ascii")
    r = requests.post(
        url="https://api.worldota.net/api/b2b/v3/hotel/info/dump/",
        json={"inventory": "all", "language": "gr"},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded_credentials}"
        }
    )
    print(r.json()["data"]["url"])
    return r.json()["data"]["url"]


if __name__ == "__main__":
    url = retrieve_dump(KEY_ID, API_KEY)