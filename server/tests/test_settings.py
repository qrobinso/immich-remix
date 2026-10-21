import json

import pytest

from app.config import Env
from app.db import DEFAULTS, ReadOnlySetting, Settings, connect


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path)
    yield c
    c.close()


@pytest.fixture
def settings_with_env(conn, tmp_path):
    def make(extra=None):
        env = Env.model_validate({"IMMICH_URL": "http://i", "IMMICH_API_KEY": "k", **(extra or {})})
        return Settings(conn, env, tmp_path)

    return make


@pytest.fixture
def settings(settings_with_env):
    return settings_with_env()


def test_defaults(settings):
    assert settings.get("photo.max_px") == 2048 and settings.get("save.album") == "Remixes"
    assert settings.source("photo.max_px") == "default"
    assert settings.get("providers.gemini.enabled") is False
    with pytest.raises(KeyError):
        settings.get("nope.nothing")
    assert settings.get("providers.gemini.extra_tuning") is None


def test_env_wins_and_is_readonly(settings_with_env):
    s = settings_with_env({"GEMINI_API_KEY": "k1"})
    assert s.get("providers.gemini.api_key") == "k1" and s.source("providers.gemini.api_key") == "env"
    assert s.get("providers.gemini.enabled") is True
    with pytest.raises(ReadOnlySetting):
        s.set("providers.gemini.api_key", "k2")


def test_secret_encrypted_at_rest(settings, conn, tmp_path):
    settings.set("providers.openai.api_key", "sk-secret")
    raw = conn.execute("select value from settings where key='providers.openai.api_key'").fetchone()[0]
    assert "sk-secret" not in raw and settings.get("providers.openai.api_key") == "sk-secret"
    assert settings.source("providers.openai.api_key") == "db"
    assert (tmp_path / "secret.key").stat().st_mode & 0o777 == 0o600


def test_public_masks_secrets(settings):
    settings.set("providers.openai.api_key", "sk-secret")
    pub = settings.public()
    assert "sk-secret" not in json.dumps(pub)
    assert pub["providers.openai.api_key"] == {"set": True, "source": "db"}
    assert pub["providers.luma.api_key"] == {"set": False, "source": "default"}


def test_plain_value_roundtrip_and_schema(settings, conn):
    settings.set("photo.max_px", 1024)
    assert settings.get("photo.max_px") == 1024 and settings.source("photo.max_px") == "db"
    with pytest.raises(KeyError):
        settings.set("bogus", 1)
    cols = {r[1] for r in conn.execute("pragma table_info(results)")}
    assert {"save_step", "save_error"} <= cols and "preview_video_path" not in cols
    assert conn.execute("pragma journal_mode").fetchone()[0] == "wal"
    assert "photo.max_px" in DEFAULTS
