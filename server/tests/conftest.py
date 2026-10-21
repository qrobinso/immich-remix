import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path):
    env = {"DATA_DIR": str(tmp_path), "IMMICH_URL": "http://immich.test", "IMMICH_API_KEY": "fake"}
    with TestClient(create_app(env=env)) as c:
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
