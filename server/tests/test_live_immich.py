import pytest

from app.immich import Immich, SearchQuery

pytestmark = pytest.mark.live


@pytest.fixture
async def im(live_env):
    i = Immich(live_env["IMMICH_URL"], live_env["IMMICH_API_KEY"])
    yield i
    await i.aclose()


async def test_version(im):
    assert (await im.version())[0] >= 3


async def test_beach_search_returns_items(im):
    assert (await im.search(SearchQuery(query="beach"))).items


async def test_video_only(im):
    items = (await im.search(SearchQuery(type="video", size=20))).items
    assert items and {c.type for c in items} == {"video"}


async def test_people(im):
    assert len(await im.people(1)) >= 1


async def test_places_cap(im):
    assert len(await im.places("a")) <= 50
