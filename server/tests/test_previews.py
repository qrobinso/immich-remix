import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.previews import estimate_preview_cost, generate_preview, write_preview
from app.providers.base import ContentRefused, HealthResult, ProviderError
from app.styles import BUILTIN_DIR, Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_previews  # noqa: E402


def png(w=800, h=600, noisy=False) -> bytes:
    # "noisy" = photo-like texture: random pixels at 1/16 scale, upsampled (white noise would not be a realistic photo)
    im = Image.frombytes("RGB", (w // 16, h // 16), os.urandom(w // 16 * (h // 16) * 3)).resize((w, h), Image.BICUBIC) if noisy else Image.new("RGB", (w, h), "red")
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


class Fake:
    id, name, can_generate = "gemini", "Fake", True
    price_per_output = {"image": 0.067}

    def __init__(self, err=None):
        self.prompts, self.err = [], err

    async def generate(self, prompt):
        self.prompts.append(prompt)
        if self.err:
            raise self.err
        return png()


def use(client, fake, ok=True):
    client.app.state.providers = SimpleNamespace(get=lambda id: fake, health={fake.id: HealthResult(ok=ok)})


def test_write_preview_sizes(tmp_path):
    write_preview(png(2000, 1500, noisy=True), tmp_path, "x")
    card, full = Image.open(tmp_path / "x.card.webp"), Image.open(tmp_path / "x.full.webp")
    assert card.size == (600, 600) and full.size == (1600, 1200) and card.format == "WEBP"
    assert (tmp_path / "x.card.webp").stat().st_size < 150_000
    write_preview(png(400, 300), tmp_path, "s")
    assert Image.open(tmp_path / "s.full.webp").size == (400, 300)  # never upscaled
    assert not list(tmp_path.glob("*.tmp"))


def test_user_preview_overrides_builtin(client, tmp_path):
    sid = "anime"
    write_preview(png(), tmp_path / "styles" / "previews", sid)
    assert client.get(f"/api/styles/{sid}/preview?kind=card").headers["content-type"] == "image/webp"
    r = client.get(f"/api/styles/{sid}/preview?kind=full")
    assert r.headers["cache-control"] == "max-age=86400" and Image.open(io.BytesIO(r.content)).size == (800, 600)
    styles = [s for c in client.get("/api/styles").json()["categories"] for s in c["styles"]]
    assert next(s for s in styles if s["id"] == sid)["preview_url"] == f"/api/styles/{sid}/preview?kind=card"
    assert client.get(f"/api/styles/{sid}/preview?kind=big").status_code == 422


def test_missing_preview_is_404_and_url_null(client):
    assert client.get("/api/styles/nope/preview").status_code == 404
    sid = "anime"
    if not (BUILTIN_DIR / "previews" / f"{sid}.card.webp").exists():
        assert client.get(f"/api/styles/{sid}/preview").status_code == 404
        styles = [s for c in client.get("/api/styles").json()["categories"] for s in c["styles"]]
        assert next(s for s in styles if s["id"] == sid)["preview_url"] is None


def test_upload_preview(client, tmp_path):
    r = client.post("/api/styles/anime/preview", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 200 and r.json() == {"preview_url": "/api/styles/anime/preview?kind=card"}
    assert (tmp_path / "styles" / "previews" / "anime.card.webp").is_file()
    assert client.post("/api/styles/anime/preview", files={"file": ("a.png", b"not an image", "image/png")}).status_code == 422
    assert client.post("/api/styles/nope/preview", files={"file": ("a.png", png(), "image/png")}).status_code == 404
    big = b"x" * (10 * 1024 * 1024 + 1)
    assert client.post("/api/styles/anime/preview", files={"file": ("a.png", big, "image/png")}).status_code == 413


def test_generate_uses_preview_prompt(client, tmp_path):
    fake = Fake()
    use(client, fake)
    s = client.app.state.styles.get("anime")
    client.app.state.styles.save_user(s.model_copy(update={"preview_prompt": "PREVIEW SCENE"}))
    r = client.post("/api/styles/anime/preview", json={"generate": True, "provider_id": "gemini"})
    assert r.status_code == 200 and fake.prompts == ["PREVIEW SCENE"]
    assert (tmp_path / "styles" / "previews" / "anime.full.webp").is_file()
    assert client.post("/api/styles/anime/preview", json={"estimate": True, "provider_id": "gemini"}).json() == {"cost_usd": 0.067}
    assert len(fake.prompts) == 1  # estimate makes no call


@pytest.mark.asyncio
async def test_generate_falls_back_to_prompt():
    s = Style(id="z", name="Z", category="scenes", media_types={"image"}, prompt="P")
    f = Fake()
    assert await generate_preview(s, f) and f.prompts == ["P"]
    assert estimate_preview_cost(f) == 0.067 and estimate_preview_cost(SimpleNamespace(price_per_output=None)) is None


def test_generate_hidden_when_no_generator(client):
    f = Fake()
    f.can_generate = False
    use(client, f)
    assert client.post("/api/styles/anime/preview", json={"generate": True, "provider_id": "gemini"}).status_code == 409
    f.can_generate = True
    use(client, f, ok=False)
    assert client.post("/api/styles/anime/preview", json={"generate": True, "provider_id": "gemini"}).status_code == 409
    assert client.post("/api/styles/anime/preview", json={"generate": True}).status_code == 409  # no default provider set


@pytest.mark.parametrize("err,code", [(ProviderError("boom"), 502), (ContentRefused("no"), 422)])
def test_generate_failures(client, err, code):
    use(client, Fake(err))
    r = client.post("/api/styles/anime/preview", json={"generate": True, "provider_id": "gemini"})
    assert r.status_code == code and r.json()["detail"]["error_code"] == err.code


def test_build_script_only_and_skip_existing(tmp_path):
    f = Fake()
    assert build_previews.main(["--only", "anime,film_noir"], provider=f, out_dir=tmp_path) == 0
    assert len(f.prompts) == 2 and (tmp_path / "anime.card.webp").is_file()
    assert build_previews.main(["--only", "anime"], provider=f, out_dir=tmp_path) == 0
    assert len(f.prompts) == 2  # skipped
    build_previews.main(["--only", "anime", "--force"], provider=f, out_dir=tmp_path)
    assert len(f.prompts) == 3
    assert build_previews.main(["--only", "anime", "--force"], provider=Fake(ProviderError("x")), out_dir=tmp_path) == 1
