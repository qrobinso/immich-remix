import pytest
from pydantic import ValidationError

from app.main import create_app


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_missing_required_env_fails():
    with pytest.raises(ValidationError):
        create_app(env={"DATA_DIR": "/tmp/x"})
