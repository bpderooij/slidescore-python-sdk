"""
This test checks the ability to create a API client and the reachability of the host
"""

import sys
import os
from unittest.mock import MagicMock, patch

import slidescore

# Either set the environment variables, or hardcode your settings below

def test_client_creation():
    SLIDESCORE_API_KEY = os.getenv('SLIDESCORE_API_KEY') # eyb..
    SLIDESCORE_HOST = os.getenv('SLIDESCORE_HOST') # https://slidescore.com/

    # Make sure we got a HOST and KEY
    assert SLIDESCORE_HOST
    assert SLIDESCORE_API_KEY
    # Remove "/" suffix if needed
    SLIDESCORE_HOST = SLIDESCORE_HOST[:-1] if SLIDESCORE_HOST.endswith('/') else SLIDESCORE_HOST

    client = slidescore.APIClient(SLIDESCORE_HOST, SLIDESCORE_API_KEY)
    response = client.perform_request('Studies', None, method="GET")
    assert response.status_code == 200


def test_upload_ASAP_questions_map_joins_key_value():
    posted = {}

    def fake_post(url, verify=True, headers=None, data=None, **kwargs):
        posted.clear()
        posted.update(data or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"success": True}
        return r

    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.post", side_effect=fake_post):
        client.upload_ASAP(
            42,
            "user",
            {"#e6194b": "Test anno"},
            "Annotation",
            "<ASAP/>",
        )
    assert posted["questionsMap"] == "#e6194b;Test anno"


def test_get_image_server_url_builds_from_end_point():
    def fake_get(url, verify=True, headers=None, data=None, stream=True, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"urlPart": "dz", "cookiePart": "c=1"}
        return r

    client = slidescore.APIClient("https://host.example", "token")
    with patch("slidescore.slidescore.requests.get", side_effect=fake_get):
        tile_url, cookie = client.get_image_server_url(7)
    assert tile_url == "https://host.example/i/7/dz/_files"
    assert cookie == "c=1"


if __name__ == "__main__":
    sys.exit('This file is meant to be ran by PyTest')