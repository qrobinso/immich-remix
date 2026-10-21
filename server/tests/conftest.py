import os
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


IMMICH = "http://immich.test"


@pytest.fixture(autouse=True)
def immich_mock(request):
    """No unit test touches the network: every Immich call must be mocked on this router."""
    if request.node.get_closest_marker("live"):
        yield None
        return
    with respx.mock(base_url=IMMICH, assert_all_called=False) as m:
        m.get("/api/server/version").mock(
            return_value=httpx.Response(200, json={"major": 3, "minor": 3, "patch": 1, "prerelease": None})
        )
        m.get("/api/users/me").mock(return_value=httpx.Response(200, json={"id": "u1", "name": "Quinn"}))
        yield m


@pytest.fixture
def make_client(tmp_path):
    def make(**extra):
        env = {"DATA_DIR": str(tmp_path), "IMMICH_URL": IMMICH, "IMMICH_API_KEY": "fake", **extra}
        return TestClient(create_app(env=env))

    return make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


@pytest.fixture
def live_env():
    if os.environ.get("RUN_LIVE") != "1":
        pytest.skip("set RUN_LIVE=1")
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and not k.lstrip().startswith("#"):
            out[k.strip()] = v.strip().strip("'\"")
    return out
