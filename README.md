# immich-remix

A Google Photos "Remix" for your own Immich library. Pick a photo or video on your phone, pick a style by its picture, and get a restyled copy saved back to Immich, stacked next to the original (the original stays primary and is never modified). It ships as one Docker container with 44 built-in styles plus Custom, and pluggable backends: Gemini, OpenAI, Stability, Runway, Luma and your own ComfyUI.

Requires **Immich v3 or newer**; older servers are refused with a banner. Single user: every save goes to the account that owns the API key.

## 1. Create the Immich API key

Immich: Account Settings > API Keys > New. Choose these permissions and nothing else (there is no delete permission, by design):

`asset.read`, `asset.view`, `asset.download`, `asset.upload`, `asset.update`, `person.read`, `album.read`, `album.create`, `albumAsset.create`, `stack.create`, `stack.read`, `stack.update`, `tag.read`, `tag.create`, `tag.asset`, `user.read`, `server.about`

## 2. Run it

```bash
docker build -t immich-remix .
docker run -d --name immich-remix --restart unless-stopped \
  -p 8080:8080 -v /opt/immich-remix:/data \
  -e IMMICH_URL=http://192.168.1.20:2283 \
  -e IMMICH_API_KEY=... \
  -e APP_PASSWORD=... \
  -e GEMINI_API_KEY=... \
  immich-remix
```

Or keep the variables in a file: `docker run -d --name immich-remix --restart unless-stopped -p 8080:8080 -v /opt/immich-remix:/data --env-file .env immich-remix`. The container runs as uid 1000 (`remix`), so `chown 1000 /opt/immich-remix` first if the folder is not writable. Open `http://<host>:8080`.

| Variable | Purpose |
| --- | --- |
| `IMMICH_URL` | Immich base URL (required) |
| `IMMICH_API_KEY` | Immich API key (required) |
| `IMMICH_PUBLIC_URL` | Optional link target for "Open in Immich" |
| `APP_PASSWORD` | Passcode for the app; unset means no login |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `STABILITY_API_KEY`, `RUNWAY_API_KEY`, `LUMA_API_KEY` | Enable that backend |
| `COMFYUI_URL` | Enable ComfyUI, e.g. `http://192.168.1.30:8188` |
| `MAX_PHOTO_JOBS` / `MAX_VIDEO_JOBS` | Concurrent jobs (default 2 / 1) |
| `TZ` | Time zone |
| `DATA_DIR` | State folder (default `/data`; set only for local dev) |

A value set by environment shows in Settings as "Set by environment" and is read-only; everything else can be set in Settings and is stored in `/data`. Keys never reach the browser, logs or the settings API.

## 3. Add it to your phone

- **iPhone:** Share > Add to Home Screen. It opens full screen, over plain HTTP too.
- **Android over plain HTTP:** Chrome gives a home-screen shortcut, not a full app install.
- **Android full install (HTTPS):** put HTTPS in front, e.g. [`tailscale serve`](https://tailscale.com/kb/1242/tailscale-serve) on the host.

**Never forward this port to the internet.** The app has a single passcode and no TLS. To use it away from home, put it behind your own VPN such as Tailscale.

## 4. Backends

Each backend appears only once configured and healthy. The UI says before every remix whether your media leaves your network.

- **Gemini** (photos, default `gemini-3.1-flash-image`): API key from Google AI Studio. **It must be a billing-enabled key: the free tier has zero image-generation quota** and every remix returns a rate-limit error.
- **OpenAI** (photos): `OPENAI_API_KEY`; image editing may require a verified organization.
- **Stability** (photos): `STABILITY_API_KEY`.
- **Runway** (video): `RUNWAY_API_KEY`.
- **Luma** (video): `LUMA_API_KEY`. Uses Luma's Agents API (inline video edit, 50 MB cap) because Modify Video needs a public URL. Whether an existing Luma key works with the Agents API is unverified.
- **ComfyUI** (photo and video): set `COMFYUI_URL` to a ComfyUI server you run on a GPU machine. The server needs a recent ComfyUI (core nodes only) and the model files below, placed under its `models/` folder. These details are also in each workflow's header in `server/workflows/*.yaml`.

| Template | Media | Custom nodes | Model files |
| --- | --- | --- | --- |
| `qwen-image-edit` | photo | none | `diffusion_models/qwen_image_edit_fp8_e4m3fn.safetensors`, `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`, `vae/qwen_image_vae.safetensors` (optional LoRA `Qwen-Image-Lightning-4steps-V1.0` for speed) |
| `flux-kontext` | photo | none | `diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors`, `text_encoders/clip_l.safetensors`, `text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors`, `vae/ae.safetensors` |
| `wan-vace` | video | none | `diffusion_models/wan2.1_vace_14B_fp16.safetensors`, `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `vae/wan_2.1_vae.safetensors` |

**What has been tested live:** only Immich and Gemini. OpenAI, Stability, Runway, Luma and ComfyUI were built from each provider's current docs against mocked HTTP and have not been run against the real services, so your first real use is their first live test. Please report breakage.

## 5. Styles

Built-in styles live in the image. To add or override one, drop a YAML file into `/data/styles/` (same schema as `server/styles/*.yaml`; the same `id` overrides a built-in) and, optionally, its previews as `/data/styles/previews/<id>.card.webp` (600x600) and `<id>.full.webp` (1600 px). It shows up without a restart or rebuild. You can also create and edit styles in Settings, which writes the same files.

Built-in previews are generated with Gemini, not shipped yet. Until you generate them, cards show a neutral placeholder. Generate them once (44 images, cost about 44 x the Gemini per-image price, roughly $3 at the default):

```bash
cd server && uv run python scripts/build_previews.py   # reads ../.env; --only a,b and --force are available
```

## 6. Development and tests

Run without Docker: `npm start` from the repo root. It builds the web app, loads `.env` and serves on port 8080 (`PORT=` to change), with state in `~/immich-remix-data` (`DATA_DIR=` to change). It needs `uv` and the web dependencies (`cd web && npm ci`).

```bash
cd server && uv sync && uv run pytest -q          # unit tests, no network
cd web && npm ci && npx vitest run
RUN_LIVE=1 uv run pytest -m live -q               # needs .env; run from server/
```

Live tests read the repo's `.env`. The write-back live test uploads its own synthetic photo and a result into an album named **`Remixes-test`**. The API key has no delete permission, so the test cannot clean up: **trash the assets in `Remixes-test` by hand in Immich afterwards.** The Gemini remix live test needs a billing-enabled key.

If thumbnails are missing in the app, the asset has none in Immich: re-run Immich's "Generate thumbnails" job.
