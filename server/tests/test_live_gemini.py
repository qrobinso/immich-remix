import io

import httpx
import pytest
from PIL import Image

from app.providers.base import MediaType, ProviderConfig, RemixRequest
from app.providers.gemini import Gemini

pytestmark = pytest.mark.live


@pytest.fixture
async def gem(live_env):
    async with httpx.AsyncClient() as http:
        yield Gemini(ProviderConfig(api_key=live_env["GEMINI_API_KEY"], model=None, url=None, options={}), http)


async def test_live_list_models_has_default(gem):
    assert "gemini-3.1-flash-image" in {m.id for m in await gem.list_models()}


async def test_live_remix_small_image(gem):
    buf = io.BytesIO()
    Image.radial_gradient("L").resize((256, 256)).convert("RGB").save(buf, "JPEG")
    res = await gem.remix(RemixRequest(
        media_type=MediaType.IMAGE, data=buf.getvalue(), mime="image/jpeg", prompt="Turn this into a simple watercolor painting.",
        negative_prompt=None, strength=None, variations=1, seed=None, style_reference=None, options={}))
    assert len(res.outputs) == 1 and Image.open(io.BytesIO(res.outputs[0])).size[0] > 0
