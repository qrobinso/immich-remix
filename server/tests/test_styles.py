from pathlib import Path

import pytest
import yaml

from app.styles import KEEP, StyleForm, StyleLibrary, build_prompt

EXPECTED = {
    "3d_animated": ("illustrated", {"image", "video"}),
    "anime": ("illustrated", {"image", "video"}),
    "cartoon": ("illustrated", {"image", "video"}),
    "comic_book": ("illustrated", {"image", "video"}),
    "claymation": ("illustrated", {"image", "video"}),
    "8bit_pixel_art": ("illustrated", {"image", "video"}),
    "chibi_sticker": ("illustrated", {"image"}),
    "storybook_illustration": ("illustrated", {"image"}),
    "flat_vector": ("illustrated", {"image"}),
    "line_art": ("illustrated", {"image"}),
    "fantasy_adventurer": ("illustrated", {"image"}),
    "superhero": ("illustrated", {"image"}),
    "watercolor": ("painted", {"image", "video"}),
    "oil_painting": ("painted", {"image", "video"}),
    "sketchbook_pencil": ("painted", {"image", "video"}),
    "pen_sketch": ("painted", {"image"}),
    "charcoal": ("painted", {"image", "video"}),
    "impressionist_brushwork": ("painted", {"image"}),
    "pop_art": ("painted", {"image"}),
    "art_deco": ("painted", {"image"}),
    "block_print": ("painted", {"image"}),
    "mosaic": ("painted", {"image"}),
    "collectible_figurine": ("collectibles", {"image"}),
    "enamel_pin": ("collectibles", {"image"}),
    "plushie": ("collectibles", {"image"}),
    "capsule_toy": ("collectibles", {"image"}),
    "professional_headshot": ("photo_looks", {"image"}),
    "dramatic_black_and_white": ("photo_looks", {"image", "video"}),
    "film_noir": ("photo_looks", {"image", "video"}),
    "sun_worn_vintage": ("photo_looks", {"image", "video"}),
    "35mm_film_grain": ("photo_looks", {"image", "video"}),
    "instant_film_with_flash": ("photo_looks", {"image"}),
    "fashion_photoshoot": ("photo_looks", {"image"}),
    "red_carpet": ("photo_looks", {"image"}),
    "photo_booth_strip": ("photo_looks", {"image"}),
    "fisheye": ("photo_looks", {"image"}),
    "birthday_card": ("occasions", {"image"}),
    "watercolor_greeting_card": ("occasions", {"image"}),
    "holiday_scene": ("occasions", {"image"}),
    "halloween_ghost": ("occasions", {"image", "video"}),
    "golden_morning_relight": ("scenes", {"image", "video"}),
    "greenhouse_backdrop": ("scenes", {"image", "video"}),
    "underwater_world": ("scenes", {"image", "video"}),
    "snowy_wonderland": ("scenes", {"image", "video"}),
}
DENY = ["pixar", "ghibli", "disney", "lego", "polaroid", "funko", "van gogh", "marvel", "nintendo", "picasso", "monet"]


@pytest.fixture
def lib(client):
    return client.app.state.styles


def test_builtins_match_spec_table(lib):
    assert {s.id: (s.category, s.media_types) for s in lib.all()} == EXPECTED


def test_every_prompt_keeps_people(lib):
    assert all(KEEP in s.prompt and s.preview_prompt and s.status_text for s in lib.all())


def test_no_brand_names(lib):
    from app.styles import BUILTIN_DIR
    text = " ".join(p.read_text().lower() for p in BUILTIN_DIR.glob("*.yaml"))
    assert [w for w in DENY if w in text] == []


def test_user_file_overrides_builtin(lib, tmp_path):
    (tmp_path / "styles").mkdir()
    f = tmp_path / "styles" / "anime.yaml"
    f.write_text(yaml.safe_dump({"id": "anime", "name": "My Anime", "category": "illustrated", "media_types": ["image"], "prompt": "x"}))
    s = lib.get("anime")
    assert (s.name, s.media_types) == ("My Anime", {"image"})


def test_custom_prompt_wrapped(lib):
    assert build_prompt(None, "  a pirate ship ") == (f"a pirate ship {KEEP}", None)
    p, n = build_prompt(lib.get("watercolor"), None)
    assert p == lib.get("watercolor").prompt and n


def form(**kw):
    return StyleForm(**{"id": "my_style", "name": "My Style", "category": "scenes", "media_types": ["image"], "prompt": "Make it glow.", **kw})


def test_save_user_writes_yaml_and_reloads(lib, tmp_path):
    s = lib.save_user(form(strength=0.5))
    assert (tmp_path / "styles" / "my_style.yaml").is_file()
    assert KEEP in s.prompt and not s.builtin
    assert lib.get("my_style").strength == 0.5 and len(lib.all()) == 45


def test_delete_builtin_rejected(client):
    assert client.delete("/api/styles/anime").status_code == 400
    assert client.delete("/api/styles/nope").status_code == 404
    assert client.delete("/api/styles/Bad-Id").status_code == 422


def test_routes(client):
    cats = client.get("/api/styles").json()["categories"]
    assert [c["id"] for c in cats][0] == "illustrated" and sum(len(c["styles"]) for c in cats) == 44
    assert cats[0]["styles"][0].keys() >= {"id", "name", "media_types", "preview_url", "builtin", "hidden"}
    body = {"id": "x", "name": "Mine", "category": "scenes", "media_types": ["image"], "prompt": "Glow."}
    assert client.put("/api/styles/mine", json=body).status_code == 200
    assert client.put("/api/styles/mine", json={"hidden": True}).status_code == 200
    ids = [s["id"] for c in client.get("/api/styles").json()["categories"] for s in c["styles"]]
    assert "mine" in ids
    assert client.put("/api/styles/anime", json={"order": ["comic_book", "anime"]}).status_code == 200
    first = client.get("/api/styles").json()["categories"][0]["styles"]
    assert [s["id"] for s in first[:2]] == ["comic_book", "anime"]
    assert client.delete("/api/styles/mine").status_code == 200
    assert client.put("/api/styles/BAD", json={"hidden": True}).status_code == 422
