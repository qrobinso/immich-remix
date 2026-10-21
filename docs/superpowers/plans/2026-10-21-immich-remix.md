# immich-remix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single self-hosted container that restyles Immich photos and videos with pluggable AI backends and saves the results back to Immich, stacked with the originals.

**Architecture:** A FastAPI backend in `server/` holds all secrets. It talks to Immich and to the providers, runs an in-process job queue, and stores state in SQLite plus files under `/data`. A static SvelteKit app in `web/` is built into `server/app/static` and served by the backend. The browser only talks to the backend.

**Tech Stack:** Python 3.12, FastAPI, httpx, Pydantic v2, Pillow, pillow-heif, piexif, PyYAML, cryptography (Fernet), itsdangerous, sqlite3, ffmpeg. Tests use pytest, pytest-asyncio and respx. The frontend is SvelteKit (adapter-static), TypeScript, Tailwind CSS and vitest.

**Spec:** [docs/spec.md](../../spec.md) plus [docs/superpowers/specs/2026-10-21-immich-remix-design.md](../specs/2026-10-21-immich-remix-design.md). Where they disagree, the design doc wins. Executors read both.

## Global Constraints

- One container and no external database. The static frontend is served by the backend. Port 8080, non-root user, all state in `/data`, `HEALTHCHECK` on `/healthz`, image under 400 MB.
- Immich v3 only. The app refuses server major versions below 3. All calls use the `x-api-key` header. Verify every Immich call against `GET http://192.168.1.20:2283/api/spec.json`, not from memory.
- Never modify, move or delete an original asset. The only writes are new uploads, metadata on those uploads, stacks, album membership and tags.
- No API key ever reaches the browser, a log line or a settings response. Settings returns `{"set": true, "source": "env"|"db"}` in place of a key.
- Model ids, clip limits and prices live in configuration with documented defaults. The Gemini default is `gemini-3.1-flash-image`. Each adapter author reads the provider's current API docs before writing it.
- Defaults: photo long edge 2048 px, JPEG quality 92, photo source `original`, video max 1080p, keep audio on, cleanup 14 days, `MAX_PHOTO_JOBS=2`, `MAX_VIDEO_JOBS=1`, album "Remixes", stack primary `original`.
- Timeouts: 180 s for cloud photos, 900 s for cloud videos, 1800 s for ComfyUI. One automatic retry with backoff on `RateLimited`/`Timeout`.
- Saved description: `Remix: <style name> · <backend name>`, plus ` · <custom prompt>` when one was used. Upload uses `deviceId="immich-remix"`. EXIF `Software="immich-remix"`.
- Every style prompt keeps people, faces, pose and composition recognizable. Custom prompts are wrapped with the same instruction.
- UI: dark default `#0B0B0C` with a light theme that follows the system. One accent color. Inter or system UI font at 13/15/20 px. Grid of 2 px gutters, 3 columns on phones and 5 to 8 on desktop. Style cards have 16 px radius and must read at 120 px. Motion 150 to 250 ms and respects reduced motion. Touch targets at least 44 × 44 px. Safe-area insets. WCAG AA.
- Env names: `IMMICH_URL`, `IMMICH_API_KEY`, `IMMICH_PUBLIC_URL`, `APP_PASSWORD`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `STABILITY_API_KEY`, `RUNWAY_API_KEY`, `LUMA_API_KEY`, `COMFYUI_URL`, `MAX_PHOTO_JOBS`, `MAX_VIDEO_JOBS`, `TZ`, plus `DATA_DIR` (default `/data`, for local dev). Env values win over stored settings.
- Live tests are marked `@pytest.mark.live`, skipped unless `RUN_LIVE=1`, and read `.env`.

## Review Focus

1. **An asset with no GPS, no `dateTimeOriginal` or no time zone** (screenshots, downloads). Write-back and EXIF and ffmpeg metadata skip the missing fields and the save still succeeds, falling back to the asset's `fileCreatedAt`. Tests are in Task 6 and Task 13.
2. **Gemini answers with text and no image, or with a safety block.** This raises `ContentRefused` with the model's text as the reason, never a crash or an empty result. Test is in Task 8.
3. **A video with no audio track while "keep audio" is on.** Finalizing succeeds with a silent output and no ffmpeg error. Test is in Task 7.
4. **Save is tapped twice, or a retry after a partial failure.** Exactly one Immich upload per result. A retry resumes from the step after the last one that completed. Test is in Task 13.
5. **A phone-shot portrait video (rotation metadata) or HEIC photo.** The output's displayed orientation matches the source. Tests are in Task 6 and Task 7.

---

## File structure

```
.gitignore .dockerignore Dockerfile README.md
server/
  pyproject.toml
  app/
    main.py          # app factory, lifespan, static mount, routers
    config.py        # env + Settings (defaults, env override, encryption)
    db.py            # sqlite schema + connection helper
    auth.py          # passcode, signed cookie, rate limit, auth dependency
    immich.py        # Immich client (all Immich calls)
    media/image.py   # photo input normalisation + output encode with EXIF
    media/video.py   # ffmpeg probe / prepare / finalize
    providers/base.py, registry.py, gemini.py, openai.py, stability.py, runway.py, luma.py, comfyui.py
    styles.py        # YAML loading, overrides, prompt building, user style writes
    previews.py      # preview generation, upload, resizing
    jobs.py          # job runner, progress pubsub, cleanup
    writeback.py     # resumable save sequence
    api/library.py, styles.py, jobs.py, settings.py, auth.py
    static/          # built frontend (gitignored, produced by web build)
  styles/            # 44 built-in *.yaml + previews/*.webp
  workflows/         # comfyui templates + sidecars
  scripts/build_previews.py
  tests/
web/
  src/lib/api.ts, filters.ts, trim.ts, components/*.svelte
  src/routes/+layout.svelte, +page.svelte (Library), item/[id]/+page.svelte, history/+page.svelte, settings/+page.svelte, login/+page.svelte
  static/manifest.webmanifest, sw.js, icons/
```

---

### Task 1: Bootstrap repo, toolchain, app skeleton

**Files:**
- Create: `.gitignore`, `.dockerignore`, `server/pyproject.toml`, `server/app/main.py`, `server/app/config.py`, `server/tests/conftest.py`, `server/tests/test_health.py`
- Modify: `.env` (rename `IMMICH_KEY` to `IMMICH_API_KEY` and `GOOGLE_KEY` to `GEMINI_API_KEY`, and add `IMMICH_URL=http://192.168.1.20:2283`; the owner allowed this)

**Interfaces:**
- Produces: `create_app(env: Mapping[str, str] | None = None) -> FastAPI`; `Env` (Pydantic model of the env vars above, `IMMICH_URL` and `IMMICH_API_KEY` required); fixture `client` (TestClient with a temporary `DATA_DIR` and fake Immich env); fixture `live_env` (reads `.env`, skips unless `RUN_LIVE=1`).

- [ ] **Step 1:** `git init`. Run `brew install uv`, then `uv python install 3.12`. In `server/`, run `uv init --python 3.12` and add dependencies: `fastapi uvicorn[standard] httpx pydantic pillow pillow-heif piexif pyyaml cryptography itsdangerous python-multipart`. Dev dependencies: `pytest pytest-asyncio respx`. The `.gitignore` covers `.env`, `server/app/static/`, `web/build`, `node_modules`, `.venv` and `__pycache__`. The `.dockerignore` covers the same plus `.git` and `docs`.
- [ ] **Step 2:** Write the failing test.

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}

def test_missing_required_env_fails():
    with pytest.raises(ValidationError):
        create_app(env={"DATA_DIR": "/tmp/x"})
```

- [ ] **Step 3:** Run `cd server && uv run pytest -q`. Expected: FAIL, import error.
- [ ] **Step 4:** Implement `Env`, `create_app` and `/healthz`. If `app/static/index.html` exists, mount it with an SPA fallback (unknown non-`/api` paths return `index.html`).
- [ ] **Step 5:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 6:** Commit with message `chore: bootstrap server skeleton`.

### Task 2: SQLite store and Settings

**Files:**
- Create: `server/app/db.py`, `server/tests/test_settings.py`
- Modify: `server/app/config.py`

**Interfaces:**
- Produces: `connect(data_dir: Path) -> sqlite3.Connection`, which creates the schema on first open (tables `settings`, `styles`, `jobs`, `results` as in spec.md, minus `preview_video_path`, plus `results.save_step TEXT` and `results.save_error TEXT`; `row_factory=sqlite3.Row`, WAL mode). `Settings(conn, env, data_dir)` with `get(key) -> Any`, `set(key, value) -> None` (raises `ReadOnlySetting` for env-sourced keys), `source(key) -> Literal["env","db","default"]`, and `public() -> dict` (secrets masked). `DEFAULTS: dict[str, Any]` holds the keys below. `SECRET_KEYS` is the set of `providers.*.api_key`.
- Setting keys: `providers.<id>.enabled|api_key|model|url`, `default_provider.image`, `default_provider.video`, `save.stack_primary`, `save.album`, `save.tag`, `photo.max_px`, `photo.jpeg_quality`, `photo.source`, `video.max_height`, `video.keep_audio`, `cleanup.days`, `styles.category_order`.
- Env-to-key map: `GEMINI_API_KEY`→`providers.gemini.api_key`, the same pattern for openai/stability/runway/luma, `COMFYUI_URL`→`providers.comfyui.url`. A provider with an env key is enabled by default.

- [ ] **Step 1:** Write the failing tests.

```python
def test_defaults(settings): assert settings.get("photo.max_px") == 2048 and settings.get("save.album") == "Remixes"
def test_env_wins_and_is_readonly(settings_with_env):
    s = settings_with_env({"GEMINI_API_KEY": "k1"})
    assert s.get("providers.gemini.api_key") == "k1" and s.source("providers.gemini.api_key") == "env"
    with pytest.raises(ReadOnlySetting): s.set("providers.gemini.api_key", "k2")
def test_secret_encrypted_at_rest(settings, conn):
    settings.set("providers.openai.api_key", "sk-secret")
    raw = conn.execute("select value from settings where key='providers.openai.api_key'").fetchone()[0]
    assert "sk-secret" not in raw and settings.get("providers.openai.api_key") == "sk-secret"
def test_public_masks_secrets(settings):
    settings.set("providers.openai.api_key", "sk-secret")
    assert "sk-secret" not in json.dumps(settings.public())
```

- [ ] **Step 2:** Run `uv run pytest tests/test_settings.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Fernet key at `<data_dir>/secret.key`, created on first run with mode 0600.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: sqlite store and settings`.

### Task 3: Passcode auth

**Files:**
- Create: `server/app/auth.py`, `server/app/api/auth.py`, `server/tests/test_auth.py`

**Interfaces:**
- Produces: `require_auth` (a FastAPI dependency applied to every `/api/*` router except `POST /api/login`, which is a no-op when `APP_PASSWORD` is blank). Endpoints `POST /api/login {password}` returns 204 and sets cookie `remix_session`. `POST /api/logout` clears it.

- [ ] **Step 1:** Write the failing tests: wrong password returns 401; the 6th failed attempt from one IP within 60 s returns 429; the right password sets an HttpOnly, `SameSite=Lax` cookie with `Max-Age=2592000` and no `Secure` over http; `GET /api/status` without the cookie returns 401 and with it returns 200; a blank `APP_PASSWORD` gives 200 with no cookie.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Sign with `itsdangerous.TimestampSigner`, using a key from `<data_dir>/secret.key` (derive with HMAC so it isn't reused raw). Set `Secure` only when `request.url.scheme == "https"` or `X-Forwarded-Proto: https`. The rate limit is an in-memory dict of IP to deque of timestamps.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: passcode auth`.

### Task 4: Immich client and library API

**Files:**
- Create: `server/app/immich.py`, `server/app/api/library.py`, `server/tests/test_immich.py`, `server/tests/test_library_api.py`, `server/tests/test_live_immich.py`

**Interfaces:**
- Produces: `class Immich(base_url: str, api_key: str, client: httpx.AsyncClient | None = None)` with these methods:
  - `version() -> tuple[int, int, int]`, `me() -> dict`
  - `search(q: SearchQuery) -> SearchPage`
  - `people(page: int, size: int = 100) -> list[Person]`
  - `places(q: str) -> list[Place]`
  - `stream(path: str, headers: dict) -> httpx.Response`, a streaming GET used for thumbnails, video and originals
  - `asset(id: str) -> dict`, `original(id: str) -> bytes`, `preview(id: str) -> bytes`
  - `upload(data: bytes, filename: str, device_asset_id: str, created_at: datetime) -> str`, which returns the asset id and also returns the existing id when Immich reports a duplicate
  - `update_assets(ids: list[str], **fields) -> None`
  - `create_stack(asset_ids: list[str]) -> str`
  - `find_or_create_album(name: str) -> str`, `add_to_album(album_id: str, ids: list[str]) -> None`
  - `find_or_create_tag(name: str) -> str`, `tag_assets(tag_id: str, ids: list[str]) -> None`
- `SearchQuery` fields: `query: str | None`, `person_ids: list[str]`, `place: Place | None`, `date_from: date | None`, `date_to: date | None`, `type: Literal["all","photo","video"]`, `page: int`, `size: int = 100`.
- `SearchPage`: `items: list[AssetCard]`, `next_page: int | None`.
- `AssetCard`: `id`, `type: "photo"|"video"`, `taken_at`, `ratio: float`, `duration_s: float | None`, `thumbhash: str | None`, `alt: str | None`.
- `Person`: `id`, `name`. `Place`: `kind: "city"|"state"|"country"`, `value: str`.
- `app.state.immich` is created in the lifespan. On startup, a major version below 3 or an unreachable server sets `app.state.immich_error`, and `/api/status` reports it. The app still serves the History page.
- Routes:
  - `GET /api/status` returns `{immich: {ok, version, user, error}, providers: [...]}`. Providers are filled in by Task 8.
  - `GET /api/people?page=`
  - `GET /api/people/{id}/thumb`
  - `GET /api/places?q=`, returning at most 50 entries
  - `POST /api/search`
  - `GET /api/assets/{id}/thumb?size=thumbnail|preview`
  - `GET /api/assets/{id}/video`

**Rules:**
- **Search:** if `query` is non-empty, call `POST /api/search/smart`. Otherwise call `POST /api/search/metadata` with `order: "desc"`. Omit `type` for `all`; map `photo` to `IMAGE` and `video` to `VIDEO`. `date_from`/`date_to` map to `takenAfter`/`takenBefore`, both inclusive (`date_to` becomes end of day). `place.kind` maps to the `city`/`state`/`country` field.
- **Live photos:** they come back as `IMAGE` and are treated as photos.
- **People:** the server excludes hidden people. Named people come first, then the rest, keeping Immich's order inside each group.
- **Places:** union the three suggestion lists, filter by case-insensitive substring of `q`, and cache them in memory for 10 minutes.
- **Proxied media:** forward `Range` requests. Pass through `Content-Type`, `Content-Length`, `Content-Range` and `Accept-Ranges` along with the status (200 or 206). Thumbnails get `Cache-Control: private, max-age=86400`.

- [ ] **Step 1:** Write failing tests in `test_immich.py`, with respx mocks whose shapes come from `spec.json`:
  - `test_text_query_uses_smart_search`: asserts the request path and JSON body `{"query":"beach","type":"VIDEO","personIds":["p1"],"city":"Paris","page":1,"size":100}`.
  - `test_no_query_uses_metadata_desc`
  - `test_people_named_first`
  - `test_places_filter_and_cap`
  - `test_upload_duplicate_returns_existing_id`

  In `test_library_api.py`, write:
  - `test_video_proxy_forwards_range`: sends a `Range: bytes=0-99` request, expects a 206, and checks the `Content-Range` header is passed through.
  - `test_api_key_never_in_response`: scans every library route's response for the key.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement against `spec.json` (download it to `server/tests/fixtures/immich-spec.json` and keep it for reference).
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Write the live test `test_live_immich.py`. It checks:
  - `version()[0] >= 3`
  - a `"beach"` search returns items
  - a video-only search returns only videos
  - `people(1)` returns at least 1 person
  - `places("a")` returns at most 50 results

  Run it with `RUN_LIVE=1 uv run pytest -m live -q`. Expected: PASS.
- [ ] **Step 6:** Commit with message `feat: immich client and library api`.

### Task 5: Styles, prompts and the 44 built-ins

**Files:**
- Create: `server/app/styles.py`, `server/app/api/styles.py`, `server/styles/*.yaml` (44 files), `server/tests/test_styles.py`

**Interfaces:**
- Produces: `Style` (Pydantic) with these fields:
  - `id`, `name`, `category`
  - `media_types: set[MediaType]`
  - `prompt`, `negative_prompt: str | None`, `strength: float | None`
  - `default_provider: dict[MediaType, str]`
  - `providers: dict[str, dict]`
  - `preview_prompt: str | None`, `preview_image: str | None`
  - `status_text: str | None`
  - `builtin: bool`, `hidden: bool`, `sort_order: int`

  `segmentable` and `preview.video` are accepted and ignored.
- Other names:
  - `StyleLibrary(builtin_dir: Path, user_dir: Path, conn)` with `all() -> list[Style]`, `get(id) -> Style`, `save_user(style: StyleForm) -> Style` (writes `<user_dir>/<id>.yaml`), `delete_user(id)`, `set_hidden(id, bool)`, `set_order(ids: list[str])`.
  - `CATEGORIES = [("illustrated","Illustrated"),("painted","Painted and drawn"),("collectibles","Collectibles"),("photo_looks","Photo looks"),("occasions","Occasions"),("scenes","Scenes")]`.
  - `KEEP = "Keep every person, face, pose and the overall composition recognizable."`.
  - `build_prompt(style: Style | None, custom: str | None) -> tuple[str, str | None]`, which returns the prompt and negative prompt. For custom it returns `f"{custom.strip()} {KEEP}"`.
  - `StyleForm` holds the form fields listed in the design doc.
- Routes:
  - `GET /api/styles` returns `{categories: [{id, name, styles: [{id, name, media_types, preview_url | null, builtin, hidden}]}]}`
  - `PUT /api/styles/{id}` takes a `StyleForm`, or `{hidden}`, or `{order}`
  - `DELETE /api/styles/{id}` (user styles only, returns 400 for a built-in without an override)

- [ ] **Step 1:** Write the failing tests. `EXPECTED` copies the spec.md table as `id → (category, media_types)`, for example `"anime": ("illustrated", {"image","video"})`, for all 44 rows. Ids are the snake_case names.
  - `test_builtins_match_spec_table`: `{s.id: (s.category, s.media_types) for s in lib.all()} == EXPECTED`
  - `test_every_prompt_keeps_people`: `KEEP` is in every built-in prompt
  - `test_user_file_overrides_builtin`
  - `test_custom_prompt_wrapped`
  - `test_save_user_writes_yaml_and_reloads`
  - `test_delete_builtin_rejected`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement `styles.py` and the routes. Write the 44 YAML files from the spec.md table. Each one has a prompt ending in `KEEP`, a `preview_prompt` (a person outdoors, face visible, some background, rendered in the style), and a `status_text` ("Painting with watercolors…"). Defaults are `default_provider: {image: gemini, video: runway}`. Names stay generic, with no brand, studio or artist names.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: style library with 44 built-ins`.

### Task 6: Photo media pipeline

**Files:**
- Create: `server/app/media/image.py`, `server/tests/test_image.py`

**Interfaces:**
- Produces: `SourceMeta` (dataclass) with `taken_at: datetime | None` (timezone-aware when known), `tz: str | None` ("+02:00"), `lat: float | None`, `lon: float | None`.
- `source_meta(asset: dict) -> SourceMeta` builds it from Immich `exifInfo`, falling back to `fileCreatedAt`.
- `prepare_image(data: bytes, max_px: int) -> bytes` registers pillow-heif, applies `exif_transpose`, converts to RGB, shrinks the long edge to `max_px` or less, and returns a JPEG at quality 95 with no EXIF. It raises `UnsupportedImage` if Pillow can't open the data.
- `encode_output(data: bytes, meta: SourceMeta, description: str, quality: int) -> bytes` returns a JPEG with `DateTimeOriginal`, `OffsetTimeOriginal`, GPS, `ImageDescription` and `Software="immich-remix"`. It writes only the fields that exist.

- [ ] **Step 1:** Write the failing tests, generating fixtures in the test with Pillow and pillow-heif:
  - `test_heic_converted`
  - `test_exif_rotation_applied`: a 100×50 image with orientation=6 comes out 50×100
  - `test_resized_to_max`: 4000×3000 at max 2048 comes out 2048×1536
  - `test_input_has_no_exif`: a source with GPS gives `piexif.load(out)["GPS"] == {}`
  - `test_output_metadata_roundtrip`: date, offset and GPS read back to within 1e-5
  - `test_output_without_gps_or_date` (Review Focus 1)
  - `test_unsupported_raises`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: photo pipeline`.

### Task 7: Video media pipeline

**Files:**
- Create: `server/app/media/video.py`, `server/tests/test_video.py`

**Interfaces:**
- Produces: `VideoInfo` with `duration`, `fps: float`, `width`, `height`, `rotation: int`, `has_audio: bool`, `codec`.
- `probe(path: Path) -> VideoInfo` uses `ffprobe -show_streams -show_format -of json`.
- `prepare_video(src: Path, out: Path, start: float, end: float, max_height: int) -> VideoInfo` trims, applies rotation (ffmpeg autorotate), scales so the short edge is at most `max_height`, and encodes H.264 yuv420p with `-an -map_metadata -1`.
- `finalize_video(remix: Path, original: Path, out: Path, start: float, end: float, keep_audio: bool, meta: SourceMeta) -> None` works as follows:
  - Conforms to the original's fps with `-r`.
  - Fixes the length to `end-start`: trims if longer, or pads the last frame with `tpad` if short by less than 0.5 s. If it's shorter than that, it keeps the remix length and cuts the audio to match.
  - When `keep_audio and has_audio`, it muxes in the original's `[start,end]` audio as AAC.
  - It writes `-metadata creation_time=<iso>` and, when GPS is known, the ISO 6709 location (`+DD.DDDD+DDD.DDDD/` with `-movflags use_metadata_tags`).
- `ffmpeg` and `ffprobe` are found on `PATH`.

- [ ] **Step 1:** Write failing tests. Fixtures come from `ffmpeg -f lavfi -i testsrc`, with `sine` audio where needed:
  - `test_prepare_trims_and_strips`: a 10 s 30 fps HEVC clip trimmed to [2,5] comes out H.264, about 3 s long, with no audio stream and no `creation_time`
  - `test_prepare_respects_rotation`: a 1920×1080 clip with `rotate=90` has displayed width less than height after prepare
  - `test_finalize_conforms_fps_and_length`: a 24 fps 2.8 s remix against a 30 fps 3 s source gives 30 fps, 3.0±0.05 s
  - `test_finalize_muxes_audio`
  - `test_finalize_no_audio_source_keep_on` (Review Focus 3)
  - `test_finalize_writes_creation_time_and_location`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement using `asyncio.create_subprocess_exec`. Raise `MediaError(stderr_tail)` when the exit code isn't zero.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: video pipeline`.

### Task 8: Provider interface, registry, Gemini

**Files:**
- Create: `server/app/providers/base.py`, `server/app/providers/registry.py`, `server/app/providers/gemini.py`, `server/tests/test_gemini.py`, `server/tests/test_live_gemini.py`
- Modify: `server/app/api/library.py` (fill `providers` in `/api/status`)

**Interfaces:**
- Produces: everything in spec.md's *Interface* block, verbatim, plus these additions:
  - `can_generate: bool`
  - `async def generate(self, prompt: str) -> bytes`
  - `async def list_models(self) -> list[ModelInfo]`
  - `ModelInfo(id: str, label: str, media_types: set[MediaType])`
  - `HealthResult(ok: bool, message: str | None)`
  - Errors `AuthError`, `RateLimited`, `ContentRefused(reason: str | None)`, `Timeout` and `ProviderError`, all subclasses of `ProviderFailure` with a `code` attribute
  - Every provider takes the constructor `__init__(self, cfg: ProviderConfig, http: httpx.AsyncClient)`, where `ProviderConfig(api_key: str | None, model: str | None, url: str | None, options: dict)`
- `Registry(settings: Settings)` has:
  - `enabled() -> list[Provider]`
  - `get(id) -> Provider`
  - `for_media(mt: MediaType) -> list[Provider]` (enabled and healthy)
  - `refresh_health() -> None`, which runs at startup and after a settings change and caches the results
  - `PROVIDER_CLASSES: dict[str, type]`, so adding a provider means one file plus one line
- `/api/status` lists providers as `{id, name, media_types, leaves_network, healthy, message, price_per_output: {image?: float, video?: float} | null}`. Each provider class exposes `price_per_output` from config, so the UI can estimate the cost before a remix.

**Gemini rules:**
- **Remix:** `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with header `x-goog-api-key`. `contents=[{parts:[{inline_data:{mime_type, data}}, {text: prompt + (" Avoid: " + negative if negative)}]}]` and `generationConfig.responseModalities=["IMAGE"]`. Make one call per variation.
- **Result:** the image comes from the first `inlineData` part.
  - No image part, or a `finishReason`/`promptFeedback.blockReason` of SAFETY/PROHIBITED_CONTENT/IMAGE_SAFETY etc., raises `ContentRefused(text parts or reason)`.
  - 401/403 raises `AuthError`. 429 raises `RateLimited`. A read timeout raises `Timeout`. Other non-2xx raises `ProviderError`.
- **Generate:** the same call with a text-only part.
- **list_models:** `GET /v1beta/models?pageSize=200`. Keep names containing `image`, labelled `"{displayName} · {id}"`.
- **Health:** `list_models` succeeds.
- **Other settings:** `leaves_network=True`, `max_input_px=2048`, `max_variations={IMAGE: 4}`. Price per image is config `providers.gemini.price_per_image`, default from Google's current pricing page.

- [ ] **Step 1:** Write failing tests (respx):
  - `test_remix_parses_image`
  - `test_text_only_answer_is_refusal` (Review Focus 2)
  - `test_safety_block_is_refusal`
  - `test_401_auth_error`
  - `test_429_rate_limited`
  - `test_variations_call_n_times`
  - `test_list_models_filters_image`
  - `test_registry_hides_unhealthy`

  Live tests:
  - `test_live_list_models_has_default`: `gemini-3.1-flash-image` is in the ids
  - `test_live_remix_small_image`: a 256 px synthetic JPEG returns one image. This costs one generation.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the unit tests and then `RUN_LIVE=1 uv run pytest tests/test_live_gemini.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: provider interface and gemini`.

### Task 9: OpenAI and Stability providers (mocked)

**Files:**
- Create: `server/app/providers/openai.py`, `server/app/providers/stability.py`, `server/tests/test_openai.py`, `server/tests/test_stability.py`

**Interfaces:**
- Consumes: Task 8's interface. Produces two registry entries, `openai` and `stability`.

- [ ] **Step 1:** Read OpenAI's current Images API docs (edits, generations, models list) and Stability's current Stable Image docs (control and style endpoints). Record the default model ids and endpoints in each module's config defaults, with the doc URL in a comment.
- [ ] **Step 2:** Write failing tests (respx, using the documented response shapes):
  - **OpenAI:** `test_edit_multipart_fields`, `test_n_variations_single_call`, `test_moderation_error_is_refusal`, `test_list_models`
  - **Stability:** `test_style_image_from_preset_sent`, `test_strength_passed`, `test_one_call_per_variation`, `test_content_filtered_is_refusal`
- [ ] **Step 3:** Run the tests. Expected: FAIL.
- [ ] **Step 4:** Implement. Stability has no model-list API, so its `list_models` returns the configured endpoint choices. Both providers have `leaves_network=True`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit with message `feat: openai and stability providers`.

### Task 10: Runway and Luma video providers (mocked)

**Files:**
- Create: `server/app/providers/runway.py`, `server/app/providers/luma.py`, `server/tests/test_runway.py`, `server/tests/test_luma.py`

**Interfaces:**
- Consumes: Task 8's interface, with `media_types={VIDEO}`, `max_variations={VIDEO: 2}` and `max_video_seconds` from config (Runway default about 5, Luma about 10, taken from the docs).

- [ ] **Step 1:** Read the current docs for Runway's video-to-video API (Aleph) and Luma's Modify Video API. **Check how each one accepts input video.** If an API only takes a public URL, with no upload endpoint and no data URI, the app can't serve one from a home network. In that case, stop and report it to the owner before writing that adapter.
- [ ] **Step 2:** Write failing tests (respx, using the documented shapes):
  - `test_upload_then_create_task`
  - `test_polls_until_succeeded`
  - `test_failed_task_maps_error`
  - `test_moderation_is_refusal`
  - `test_downloads_output`
  - `test_poll_timeout_raises_timeout`: uses a fake clock and the 900 s limit
- [ ] **Step 3:** Run the tests. Expected: FAIL.
- [ ] **Step 4:** Implement. Poll every 5 s. `list_models` returns the configured model list, since neither provider has a list API.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit with message `feat: runway and luma providers`.

### Task 11: ComfyUI provider and workflow templates

**Files:**
- Create: `server/app/providers/comfyui.py`, `server/tests/test_comfyui.py`, and in `server/workflows/`: `qwen-image-edit.json` + `.yaml`, `flux-kontext.json` + `.yaml`, `wan-vace.json` + `.yaml`

**Interfaces:**
- **Sidecar YAML:** `{name, media_type: image|video, output_node: str, options: {}}`.
- **Templates:** loaded from `/app/workflows` and then `/data/workflows` (same-name files override).
- **Models in the dropdown:** `list_models()` returns the workflow templates.
- **Choosing a workflow:** a style's `providers.comfyui.workflow` picks the template, and otherwise the selected model (workflow) applies.
- **Placeholders:**
  - `{{input_image}}`, `{{input_video}}`, `{{prompt}}`, `{{negative_prompt}}`, `{{seed}}`, `{{strength}}`, `{{fps}}`, `{{frames}}`.
  - If a JSON string value is exactly one placeholder, replace the whole value with the typed value, so numbers stay numbers.
  - If the placeholder is only part of a string, substitute it as text.
  - Style `options` override matching node inputs by `node_id.input` keys.
- **Flow:** `POST /upload/image` (multipart, also used for the video file) → `POST /prompt {prompt, client_id}` → poll `GET /history/{prompt_id}` every 2 s until it has outputs → `GET /view?filename=&subfolder=&type=` for each output in `output_node`. The time limit is 1800 s.
- **Provider settings:** `leaves_network=False`, `can_generate=False`, `media_types` comes from the templates found, and health is `GET /system_stats`.

- [ ] **Step 1:** Write the failing tests:
  - `test_whole_placeholder_typed`: `"{{seed}}"` becomes the int `42`
  - `test_inline_placeholder_text`
  - `test_options_override_node_input`
  - `test_flow_upload_prompt_history_view`
  - `test_user_template_overrides`
  - `test_video_template_only_for_video`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Write the three templates in ComfyUI API format, using current node names from the Qwen-Image-Edit, FLUX.1 Kontext and Wan VACE example workflows. List each template's required custom nodes and model files in a header comment of its sidecar (they go into the README in Task 21).
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: comfyui provider and templates`.

### Task 12: Job runner, jobs/results/history API, SSE, cleanup

**Files:**
- Create: `server/app/jobs.py`, `server/app/api/jobs.py`, `server/tests/test_jobs.py`

**Interfaces:**
- Consumes: `Immich`, `StyleLibrary.get`, `build_prompt`, `prepare_image`, `prepare_video`, `finalize_video`, `Registry`, `Settings`.
- Produces: `JobRunner(conn, settings, registry, immich, styles, data_dir)` with these methods:
  - `start()`: called from the lifespan. It marks `queued`/`running` jobs `failed` with `error_code="interrupted"` and `error_message="Interrupted"`.
  - `submit(req: JobCreate) -> str`
  - `events(job_id) -> AsyncIterator[dict]`
  - `retry(job_id) -> str`, which creates a new job with the same settings
- `JobCreate` fields: `asset_id`, `style_id: str | None`, `custom_prompt: str | None`, `provider_id: str | None` (None means the style's default, then the settings default), `variations: int`, `clip_start: float | None`, `clip_end: float | None`.
- `cleanup_results(conn, data_dir, days: int, now: datetime) -> int` runs at startup and every 24 h.
- Routes:
  - `POST /api/jobs` returns `{id}`. It returns 422 when the provider can't handle the media type, when variations are over the provider or media cap (4 photo, 2 video), or when the clip is longer than `max_video_seconds`.
  - `GET /api/jobs/{id}` returns the job plus `results: [{id, index, url, mime, width, height, duration_s, saved_asset_id, discarded}]`.
  - `GET /api/jobs/{id}/events` is SSE (`text/event-stream`, a `data: {json}` frame on each change, and a keep-alive every 15 s).
  - `GET /api/results/{id}/media` supports range requests (use Starlette `FileResponse`).
  - `POST /api/results/{id}/discard`
  - `GET /api/history?page=` returns pages of 30 jobs, newest first, each with its results.

**Job flow:**
1. Fetch the asset.
2. Prepare the input:
   - For a photo: use the original or the preview according to `photo.source`. If `prepare_image` raises `UnsupportedImage` (RAW files), fall back to the preview.
   - For a video: download the original to a temp file and run `prepare_video`.
3. Run the remix, with one automatic retry with backoff of 5 s on `RateLimited`/`Timeout`, under `asyncio.timeout` (180/900/1800 s).
4. For a video, `finalize_video` each output. Don't keep the original audio's metadata in the cached result.
5. Write `/data/results/<job_id>/<index>.<jpg|mp4>` and the result rows, and set status `done`. A failure sets `failed` with `error_code`/`error_message` from `ProviderFailure` or `MediaError`.
6. Concurrency: semaphores sized from `MAX_PHOTO_JOBS` and `MAX_VIDEO_JOBS`.
7. Events are `{status, message}`. The message is the style's `status_text` or "Remixing…". Video events also carry `eta_s`, which is the provider's config `typical_seconds`.

- [ ] **Step 1:** Write failing tests with a fake provider and a fake Immich:
  - `test_photo_job_runs_to_done_and_writes_files`
  - `test_variations_capped_422`
  - `test_provider_wrong_media_422`
  - `test_rate_limit_retried_once_then_fails`
  - `test_refusal_sets_error_code`
  - `test_restart_marks_interrupted`
  - `test_sse_streams_status_changes`
  - `test_concurrency_limits`
  - `test_cleanup_deletes_only_old_unsaved_undiscarded`
  - `test_raw_falls_back_to_preview`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: job runner and history`.

### Task 13: Write-back (save)

**Files:**
- Create: `server/app/writeback.py`, `server/tests/test_writeback.py`, `server/tests/test_live_writeback.py`
- Modify: `server/app/api/jobs.py` (add `POST /api/results/{id}/save`)

**Interfaces:**
- Produces: `async def save_result(result_id: str, ctx: SaveContext) -> SaveOutcome`.
  - `SaveOutcome` has `asset_id: str | None`, `link: str | None`, `failed_step: str | None` and `error: str | None`.
  - Steps run in this order: `upload`, `metadata`, `stack`, `album`, `tag`. `results.save_step` records the last completed step.
  - An `asyncio.Lock` per result id makes a double-tap wait, then return the same outcome.
- The route returns 200 with `{asset_id, link}`, or 207 with `{asset_id, failed_step, error}`. Calling it again resumes after `save_step`.

**Step rules:**
- **Encode:**
  - Photos: `encode_output` with `SourceMeta`, the description and `photo.jpeg_quality`.
  - Videos: the finalized MP4 already has its metadata (Task 7).
- **upload:** `device_asset_id=f"immich-remix-{result_id}"`. `fileCreatedAt` and `fileModifiedAt` are set to `meta.taken_at`, or the source's `fileCreatedAt` when that's missing.
- **metadata:** `update_assets([new], dateTimeOriginal, latitude, longitude, timeZone, description)`, sending only the known fields. The description is in the format from Global Constraints.
- **stack:**
  - Read the source's `stack`.
  - With `save.stack_primary == "original"`, the ids are the source stack's current primary (or the source) first, then the new asset.
  - With `"remix"`, the new asset comes first.
  - Call `create_stack(ids)`. Immich merges existing stacks; confirm this against `spec.json` and in the live test.
- **album:** runs if `save.album` is set: `find_or_create_album` and then `add_to_album`.
- **tag:** runs if `save.tag` is set.
- **Done:** set `saved_asset_id` and `saved_at`, delete the result file, and return `link = f"{IMMICH_PUBLIC_URL or IMMICH_URL}/photos/{asset_id}"`.

- [ ] **Step 1:** Write failing tests with a mocked `Immich`:
  - `test_full_sequence_order_and_payloads`: checks the description `"Remix: Watercolor · Google Gemini"`, plus the custom prompt suffix
  - `test_no_gps_no_date_still_saves` (Review Focus 1)
  - `test_double_save_uploads_once` (Review Focus 4)
  - `test_album_failure_then_retry_resumes_at_album`
  - `test_source_in_stack_keeps_existing_primary`
  - `test_remix_primary_setting`
  - `test_original_never_updated`: asserts that `update_assets` is never called with the source id
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Write the live test `test_live_writeback.py`. It must not touch real photos:
  - Upload a synthetic 800×600 JPEG as the "original", with a date of 2020-06-01T12:00:00+02:00 and GPS 48.8584, 2.2945.
  - Snapshot its `checksum`, `exifInfo.dateTimeOriginal`, `latitude` and `longitude`.
  - Run a real Gemini job on it, then `save_result` with `save.album="Remixes-test"`.
  - Assert that the new asset's date and GPS match, that the stack contains both assets with the original as primary, that it's in the album, and that the original's snapshot is unchanged.
  - Print `Trash the assets in album "Remixes-test" when done.`

  Run it with `RUN_LIVE=1 uv run pytest tests/test_live_writeback.py -q -s`. Expected: PASS.
- [ ] **Step 6:** Commit with message `feat: write-back to immich`.

### Task 14: Settings API

**Files:**
- Create: `server/app/api/settings.py`, `server/tests/test_settings_api.py`

**Interfaces:**
- Routes:
  - `GET /api/settings` returns `{values: Settings.public(), sources: {key: "env"|"db"|"default"}, providers: [{id, name, media_types, enabled, healthy, message, key_set, key_source, model, url}]}`.
  - `PUT /api/settings {key: value, ...}` validates the type and range of each known key. It returns 409 for an env-sourced key and refreshes the registry when a `providers.*` key changes.
  - `POST /api/providers/{id}/test` returns a `HealthResult`.
  - `GET /api/providers/{id}/models` returns `list[ModelInfo]`, or `{"error": "...", "fallback": true}` if listing fails, in which case the UI shows a text field.
  - `GET /api/albums` returns `[{id, name}]` for the album picker. It needs Immich `GET /api/albums`.

- [ ] **Step 1:** Write the failing tests:
  - `test_keys_never_returned`: set a key and scan the GET body
  - `test_env_key_put_409`
  - `test_invalid_value_422`: e.g. `photo.max_px=10`, or `jpeg_quality=101`
  - `test_models_endpoint_fallback`
  - `test_provider_toggle_refreshes_registry`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: settings api`.

### Task 15: Style previews

**Files:**
- Create: `server/app/previews.py`, `server/scripts/build_previews.py`, `server/tests/test_previews.py`
- Modify: `server/app/api/styles.py` (add preview routes)

**Interfaces:**
- Produces:
  - `write_preview(png_or_jpeg: bytes, dest_dir: Path, style_id: str) -> None` writes `<id>.card.webp` (600×600, center crop) and `<id>.full.webp` (1600 px long edge).
  - `async def generate_preview(style: Style, provider: Provider) -> bytes` uses `style.preview_prompt or style.prompt`.
  - `estimate_preview_cost(provider) -> float | None`
- Routes:
  - `GET /api/styles/{id}/preview?kind=card|full` serves from `/data/styles/previews/` first, then `/app/styles/previews/`, and returns 404 if neither has it. It sets `Cache-Control: max-age=86400`.
  - `POST /api/styles/{id}/preview` takes multipart `file` to upload, or JSON `{generate: true, provider_id?}`. It returns `{preview_url}`. `{estimate: true}` returns `{cost_usd}` and does nothing.
  - `GET /api/styles` sets `preview_url` to null when no file exists; the UI then shows a placeholder.
- **The script:** `uv run python scripts/build_previews.py [--only id,...] [--force]` generates the built-in previews with Gemini into `server/styles/previews/`, skipping existing files unless `--force`.

- [ ] **Step 1:** Write the failing tests:
  - `test_write_preview_sizes`
  - `test_user_preview_overrides_builtin`
  - `test_upload_preview`
  - `test_generate_uses_preview_prompt` (with a fake provider)
  - `test_generate_hidden_when_no_generator`: `can_generate` is false everywhere, so the API returns 409
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** **Ask the owner before running.** This makes 44 Gemini generations; state the cost estimate. Run `uv run python scripts/build_previews.py`, look at 5 random cards, and re-run `--only` for any that are poor. Card files must be under 150 KB.
- [ ] **Step 6:** Commit with message `feat: style previews`, including the generated `.webp` files.

### Task 16: Frontend shell

**Files:**
- Create: `web/` (SvelteKit + adapter-static + TS + Tailwind + vitest), `web/src/lib/api.ts`, `web/src/routes/+layout.svelte`, `web/src/routes/login/+page.svelte`, `web/src/lib/components/BottomNav.svelte`, `web/static/manifest.webmanifest`, `web/static/sw.js`, `web/static/icons/*`
- Modify: `web/vite.config.ts` (dev proxy `/api` → `http://localhost:8080`)

**Interfaces:**
- Produces:
  - `api.ts` with typed `get<T>(path)`, `post<T>(path, body)`, `put<T>(path, body)` and `events(jobId, onMsg) -> close()`. `events` uses SSE and falls back to polling `GET /api/jobs/{id}` every 2 s on error.
  - On a 401 response it redirects to `/login`.
  - Response types mirror the backend routes above.
- **Build output:** `npm run build` writes to `../server/app/static` (adapter-static `pages`/`assets` and `fallback: "index.html"`).
- **Theme:** CSS variables on `:root` for background, foreground, muted and accent. Dark is the default; light comes from `prefers-color-scheme: light`. The accent is the builder's choice and must pass AA on both themes.
- **Layout:** a bottom nav with Library, History and Settings, 44 px targets and safe-area padding.
- **Manifest:** `display: standalone`, `background_color` and `theme_color` `#0B0B0C`, and 192/512 icons plus `apple-touch-icon`.
- **Service worker:** registered only if `'serviceWorker' in navigator && isSecureContext`. It caches the app shell (`/`, `_app/immutable/*`) and never caches `/api/*`.
- **Immich unreachable:** if `/api/status.immich.ok` is false, a full-screen banner shows the error with a Retry button on Library. History stays usable.

- [ ] **Step 1:** Scaffold with `npx sv create web` (minimal, TS), then `npx sv add tailwindcss vitest`, and install `@sveltejs/adapter-static`.
- [ ] **Step 2:** Write the failing vitest `api.test.ts`: `test 401 redirects to /login` and `test events falls back to polling`.
- [ ] **Step 3:** Run `cd web && npx vitest run`. Expected: FAIL.
- [ ] **Step 4:** Implement the shell, login page, theme, nav, manifest and SW.
- [ ] **Step 5:** Run `npx vitest run && npm run build`. Expected: PASS, and `server/app/static/index.html` exists.
- [ ] **Step 6:** Commit with message `feat: web shell`.

### Task 17: Library screen

**Files:**
- Create: `web/src/routes/+page.svelte`, `web/src/lib/filters.ts`, `web/src/lib/components/{Grid,SearchBar,PeopleRow,PlacePicker,DateChip,TypeToggle,FilterChips}.svelte`, `web/src/lib/filters.test.ts`

**Interfaces:**
- Produces:
  - `Filters` with `query`, `people: {id,name}[]`, `place: Place | null`, `dateFrom`, `dateTo`, `type: "all"|"photo"|"video"`.
  - `toSearchBody(f: Filters, page: number)` builds the `POST /api/search` body.
  - Filters are stored in the URL query string, so Back returns to the same search.

**Behaviour:**
- **Grid:** square tiles, 3 columns on phone and 5 to 8 on desktop (by width), 2 px gap. Infinite scroll uses `IntersectionObserver` and `next_page`.
- **Tiles:** thumbnails `loading="lazy"`, fade in over 200 ms, with a thumbhash placeholder (use the `thumbhash` npm package). Video tiles show a duration badge `m:ss`. Alt text comes from `alt`.
- **Search:** the search bar is debounced by 400 ms.
- **People row:** horizontal scroll, pages more on scroll end, and multi-select.
- **Place picker:** a bottom sheet with a search input that queries `/api/places?q=`.
- **Date chip:** a year or a range.
- **Type toggle:** All, Photos or Videos.
- **Active filters:** shown as removable chips above the grid.

- [ ] **Step 1:** Write failing vitest tests:
  - `toSearchBody` maps all fields
  - an empty query is omitted
  - `type all` is passed through as `all`
  - URL round-trip preserves filters
- [ ] **Step 2:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS. Then run the backend with `cd server && uv run uvicorn app.main:create_app --factory --port 8080` and the dev server, and check with Playwright at 390×844: the first screen of thumbnails shows in under 2 s, "beach" search works, a person filter works, and Videos-only shows duration badges.
- [ ] **Step 5:** Commit with message `feat: library screen`.

### Task 18: Item viewer, style sheet, remix

**Files:**
- Create: `web/src/routes/item/[id]/+page.svelte`, `web/src/lib/trim.ts`, `web/src/lib/trim.test.ts`, `web/src/lib/components/{StyleSheet,StyleCard,StylePreviewModal,RemixOptions,Trimmer,Shimmer}.svelte`

**Interfaces:**
- Consumes: `GET /api/styles`, `GET /api/status`, `POST /api/jobs`, `api.events`.
- Produces: `clampTrim(start: number, end: number, duration: number, max: number | null) -> {start, end}` keeps `0 <= start < end <= duration` and `end - start <= max`. The default range is `[0, min(duration, max)]`.

**Behaviour:**
- **Viewer:** a full-screen preview, or for a video a muted looping `<video>` from `/api/assets/{id}/video`. The style sheet springs up over 250 ms.
- **Style cards:** grouped in category rows using `preview_url`, with a neutral placeholder plus the name when it's null. A video shows only video-capable styles. The selected card gets an accent ring.
- **Full preview:** long-press (500 ms) or the info icon opens `StylePreviewModal` with the full preview image.
- **Custom card:** the last card. It opens a text field.
- **Options:** collapsed by default:
  - backend, limited to `for_media` providers, with the style's default preselected
  - variations, 1 to 4 for photos and 1 to 2 for videos, capped by the provider
  - a trimmer for videos
  - a network note: "Sent to <Name>" if `leaves_network`, otherwise "Runs locally"
  - for cloud backends, the estimated cost "≈ $X.XX", computed as `price_per_output × variations`; video price is per second × clip length
- **Remix:** the primary button sits in the bottom third.
- **While running:** a diagonal shimmer over the image plus the status line from SSE, and "about N min" for videos. The user can navigate away.
- **When done:** go to the review route (Task 19). Failure shows the error message: for `content_refused`, "This style couldn't be applied" plus the reason and a hint to try another backend.

- [ ] **Step 1:** Write failing vitest `trim.test.ts`: the default range caps at max, a range dragged past the end is clamped, a no-limit provider gives the full duration, and start < end is enforced.
- [ ] **Step 2:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`. Expected: PASS. Then use Playwright at 390×844: pick a photo, then Watercolor, then Remix, and see the shimmer and status text, then done. This costs one Gemini generation.
- [ ] **Step 5:** Commit with message `feat: viewer, style sheet and remix`.

### Task 19: Review screen and History

**Files:**
- Create: `web/src/routes/review/[jobId]/+page.svelte`, `web/src/routes/history/+page.svelte`, `web/src/lib/components/{BeforeAfter,VideoCompare,Toast}.svelte`

**Interfaces:**
- Consumes: `GET /api/jobs/{id}`, `GET /api/results/{id}/media`, `POST /api/results/{id}/save|discard`, `GET /api/history`.

**Behaviour:**
- **Photo review:** `BeforeAfter` has a draggable divider (pointer events, keyboard arrows move it 5%). Swipe moves between variations.
- **Video review:** `VideoCompare` plays the original and the remix synced to one `currentTime`, with a toggle and a split view.
- **Actions:**
  - **Save:** a 200 response shows the toast "Saved to Immich" with an "Open in Immich" link. A 207 shows "Saved, but <step> failed" with Retry.
  - **Try again:** `POST /api/jobs` with the same body.
  - **Change style:** goes back to the item with the sheet open.
  - **Discard.**
- **History:** a grid of result thumbnails, newest first, with the style name and a running, failed or saved badge. Tapping opens the review page. Failed jobs show a Retry.

- [ ] **Step 1:** Implement. Unit tests aren't needed, since the logic lives in the backend and is tested there.
- [ ] **Step 2:** Use Playwright at 390×844:
  - Review the Task 18 result and drag the divider.
  - Save to the `Remixes-test` album: in Settings, temporarily set the album to `Remixes-test`.
  - Check that the toast link opens Immich, and that History shows the job as saved.
- [ ] **Step 3:** Commit with message `feat: review and history`.

### Task 20: Settings screen

**Files:**
- Create: `web/src/routes/settings/+page.svelte`, `web/src/lib/components/{ProviderCard,StyleEditor,StyleManager}.svelte`

**Behaviour:**
- **Immich status:** server version and signed-in user.
- **Provider cards:**
  - an enable toggle
  - a key field that is write-only (shows "Set by environment" and is read-only when `key_source == "env"`, otherwise "Saved")
  - the ComfyUI URL
  - a model dropdown from `/api/providers/{id}/models`, which falls back to a text input
  - a Test button
- **Default backend:** one for photos and one for videos.
- **Styles:** a reorderable list per category (drag handle plus up/down buttons for accessibility), hide toggles, and Edit or New, which opens the `StyleEditor` form with the fields from the design doc.
- **Previews:** "Generate preview" shows the estimate first, then generates. Upload is also offered.
- **Save behaviour:** stack primary, an album picker (none, or any existing album, default "Remixes"), and a tag.
- **Photo output:** max px, JPEG quality, and source (original or preview).
- **Video output:** max resolution and keep audio.
- **Cleanup:** days.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Use Playwright:
  - The Gemini key shows "Set by environment".
  - The model dropdown lists the Nano Banana models with Nano Banana 2 selected.
  - Changing JPEG quality persists across a reload.
  - Creating a style "Test Neon" with an uploaded preview makes it show in the sheet; then delete it.
- [ ] **Step 3:** Commit with message `feat: settings screen`.

### Task 21: Dockerfile, README, acceptance pass

**Files:**
- Create: `Dockerfile`, `README.md`

**Dockerfile:**
- Stage 1, `node:24-slim`: `npm ci && npm run build` in `web/`.
- Stage 2, `python:3.12-slim`:
  - `apt-get install --no-install-recommends ffmpeg`
  - `pip install` from the uv-exported requirements
  - copy `server/app`, `server/styles`, `server/workflows`, and the built static files to `/app`
- Runtime: non-root user `remix` (uid 1000), `ENV DATA_DIR=/data`, `VOLUME /data`, `EXPOSE 8080`, `HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"`, and `CMD uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080`.

**README contents:**
- what the app is
- creating the Immich API key with the exact permission list from the design doc
- the `docker run` command from spec.md, plus the `--env-file` alternative
- the env vars table
- adding it to a phone home screen (iOS full screen; on Android, plain HTTP gives a shortcut and `tailscale serve` gives the full install)
- a warning not to forward the port to the internet
- setup for each backend
- ComfyUI custom nodes and models per template
- a note that OpenAI, Stability, Runway, Luma and ComfyUI were built from their docs and not tested live
- live tests and the `Remixes-test` cleanup

- [ ] **Step 1:** Write the Dockerfile and README.
- [ ] **Step 2:** If Docker is available locally, or on the owner's Proxmox Docker host, run `docker build -t immich-remix .` and check `docker image ls immich-remix`: under 400 MB. Then `docker run --env-file .env -p 8080:8080 -v $PWD/.data:/data immich-remix`, after which `/healthz` returns 200 and the container user is not root. If no Docker is available, stop and ask the owner where to build.
- [ ] **Step 3:** Run the acceptance pass against the running container, checking each item in spec.md's *Acceptance criteria* as amended by the design doc. Mark the video-backend items as mocked-only.
  - Grep the logs and every captured network response for each key value. Expected: no hits.
  - Drop a new YAML file plus a preview into `/data/styles/` and reload. The style appears without a rebuild.
- [ ] **Step 4:** Run the full suites: `cd server && uv run pytest -q`, `RUN_LIVE=1 uv run pytest -m live -q`, `cd web && npx vitest run`. Expected: all PASS.
- [ ] **Step 5:** Commit with message `feat: docker image and readme`.
