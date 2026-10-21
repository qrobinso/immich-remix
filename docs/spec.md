# immich-remix — Product & Technical Spec

Oct 21, 2026 · @Quentin Robinson

## Overview

immich-remix is a single self-hosted container that works like Google Photos Remix for an Immich library, for both photos and videos. You pick any photo or video, pick a style from a gallery of visual previews, and get a restyled version back. You then save it to Immich, stacked next to the original. It is used mostly from a phone browser and connects to an existing Immich server over its REST API. The generation work goes to a backend you choose: a cloud API with your own key, or your own local model.

**Goals**

- Find any photo or video in under 10 seconds on a phone: search by text, person, place or date.
- Restyle in 3 taps: pick the photo or video, pick a style, tap Remix.
- See before you choose: every style shows a preview image of what it looks like.
- Remix videos as well as photos, keeping the original's motion and timing.
- Bring your own backend: cloud APIs with your own keys (Google Gemini, OpenAI, Stability AI, Runway, Luma) or your own local ComfyUI server, switchable per style.
- Save results back to Immich with the original's date and location, stacked with the original, so the timeline stays clean.
- Simple and beautiful: photo-forward, minimal chrome, feels like a native app on iOS and Android.

**Scope boundaries**

- **Remote access:** built for a home network. The user sets up access from outside the home themselves, for example with Tailscale. The app includes no tunnel, public sharing or internet-facing hardening beyond its passcode.
- **Models:** none are bundled. Cloud backends use the user's own API keys. Local generation uses the user's own ComfyUI server and models, reached by URL.
- **Interface:** the app has its own UI only. It does not inject into Immich's web UI and ships no browser extension or userscript.
- **Triggering:** a person starts every remix in the app. There is no automatic remixing from albums or Immich workflows.
- **Packaging:** a Dockerfile and a documented `docker run` command, with no compose file.

## User experience

The app has three screens behind a bottom navigation bar: **Library** (the photo picker), **History**, and **Settings**. Everything is designed for one-handed use on a phone first. On desktop the same layout widens into a multi-column grid.

### Core flow

1. **Open the app.** Library shows recent photos and videos in a dense grid, newest first, with infinite scroll. Videos show a duration badge.
2. **Find something to remix.** Use any of these, alone or together:
   - **Search bar:** free-text smart search ("beach sunset", "birthday cake") using Immich's CLIP search.
   - **People:** a horizontal row of face circles from Immich's recognized people, named people first. Tapping one or more filters the grid to items containing all selected people.
   - **Places:** a list of cities, states and countries from Immich's location data, searchable. Tapping one filters the grid.
   - **Date:** an optional year or date-range chip.
   - **Type:** All, Photos or Videos.
   - Active filters show as removable chips above the grid. Text, people, place, date and type combine.
3. **Tap an item.** It opens full screen, with videos playing muted on loop. The style sheet slides up from the bottom.
4. **Choose a style by looking at it.** Styles appear as a scrolling gallery of preview cards, grouped into the categories in the style library (Illustrated, Painted and drawn, Collectibles, Photo looks, Occasions, Scenes). Each card shows the style's preview image: the same reference photo rendered in that style, so cards compare like for like. Picking "Cartoon" shows what a cartoon remix looks like before you commit. For a video, only video-capable styles appear, and the selected card plays its looping preview clip. Long-press a card, or tap its info icon, to see the preview full screen with a before/after slider against the unstyled reference. The last card is **Custom**, which opens a text field for a free-form prompt.
5. **Optional settings** (collapsed by default):
   - Backend: only backends that support this media type are offered; the style's default is preselected.
   - Variations: 1 to 4 for photos, 1 or 2 for videos.
   - For videos, a clip trimmer preset to the backend's maximum length.
   - A note showing whether the media will leave the network ("Sent to Google" versus "Runs locally").
6. **Tap Remix.** The item stays on screen with a soft animated shimmer and a status line ("Painting with watercolors…"). Video jobs also show an estimated time. The user can leave; the job keeps running and shows up in History.
7. **Review the result.**
   - Photos: a before/after view with a draggable divider; swipe between variations.
   - Videos: original and remix play in sync, with a toggle or a split view.
   - Actions: **Save to Immich**, **Try again** (same settings, new result), **Change style**, **Discard**.
8. **Save.** A toast confirms "Saved to Immich" with an "Open in Immich" link that deep-links to the new asset.

### History

A grid of past remixes, newest first, each showing the result thumbnail with the style name. Status badges: running, failed, saved. Tap to reopen the review screen. Unsaved results can still be saved later until cleanup removes them.

### Settings

- Immich connection status (server version, signed-in user).
- Backends: enable or disable each, enter API keys or the ComfyUI URL, test the connection, and pick a default backend for photos and one for videos.
- Styles: reorder categories and styles, hide, edit, add custom presets, and regenerate previews.
- Save behavior: stack primary (original or remix), add to album (none, or a chosen album, default "Remixes"), add a tag.
- Photo output: maximum long edge sent to the backend (default 2048 px), JPEG quality.
- Video output: maximum resolution (default 1080p), keep or drop the original audio (default keep).
- Cleanup: keep unsaved results for N days (default 14).

## Visual design direction

The photos are the interface. The UI is quiet, dark-first, and gets out of the way. It should feel closer to a camera app than to a dashboard.

- **Theme:** dark by default (near-black #0B0B0C background), with a light theme following the system setting. One accent color for primary actions and selection. No other decorative color.
- **Type:** Inter (or the system UI font) with three sizes: 13, 15 and 20 px. Semibold for titles, regular for everything else.
- **Grid:** edge-to-edge square thumbnails with 2 px gutters: 3 columns on phones, 5 to 8 on desktop. Thumbnails fade in as they load. Use blurhash or Immich's thumbhash placeholder if available.
- **Style cards:** rounded 16 px corners, the style's preview image filling the card, and the name on a subtle bottom gradient. The selected card gets an accent ring, and on a video it starts its looping preview. Previews are the main way people choose a style, so they must read clearly at 120 px wide. Category headers sit above each row.
- **Motion:** short and purposeful, 150 to 250 ms. The bottom sheet springs up, results cross-fade in, and the shimmer while generating is a slow diagonal sweep.
- **Touch:** every target at least 44 by 44 px. Primary actions sit in the bottom third of the screen. Respect iOS safe-area insets.
- **PWA:** web app manifest, app icon, full-screen standalone display, so it can be added to the home screen and launch like an app. A service worker caches the app shell only, never photos.
- **Accessibility:** WCAG AA contrast, visible focus states, alt text from Immich descriptions where present, and respect for reduced-motion settings.

## Architecture

One container serves both the web UI and a small backend API. The browser only ever talks to immich-remix. The backend holds every secret and talks to Immich and to the image backends.

&#91;embedded content: immich-remix architecture · one container, two outside services\]

The App API is the only part that talks to Immich and the backends, so no key ever reaches the phone.

### Components inside the container

- **Web UI:** a static single-page app, built at image build time and served by the backend.
- **App API:** REST endpoints for search, thumbnails, styles, jobs, results and settings (see the API surface section).
- **Immich client:** a typed wrapper over the Immich REST API. All Immich calls go through it.
- **Job runner:** an in-process async queue. Concurrency is configurable: by default 2 photo jobs and 1 video job run at a time. It survives page closes. Interrupted jobs are marked failed on restart.
- **Provider registry:** loads the enabled backends behind one interface.
- **Store:** SQLite for settings, styles, jobs and results, plus a results folder on disk. Both live under `/data`.

### Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, httpx, Pydantic v2 | Async I/O for long provider calls; strongest SDK support for image and video APIs |
| Images | Pillow, pillow-heif, piexif | HEIC input, resizing, EXIF write-back |
| Video | ffmpeg (bundled in the image) | Trim, transcode to H.264, conform frame rate, mux original audio back, write metadata |
| Storage | SQLite via SQLModel or plain sqlite3 | Zero-ops, single file |
| Frontend | SvelteKit (static adapter), TypeScript, Tailwind CSS | Small bundles, fast on phones; same framework family as Immich's web UI |
| Progress | Server-sent events per job, with polling fallback | Simple live status without WebSockets |

The coding model may substitute equivalents, but must keep a single container, a static frontend served by the backend, and no external database.

## Immich integration

immich-remix authenticates to Immich with one API key sent in the `x-api-key` header. It targets Immich v2 and v3 and reads the server version at startup.

**Build rule:** generate or verify every call against the running server's OpenAPI spec (`GET /api/spec.json`), not against memory. Endpoint names below are the expected ones and must be checked.

### Calls used

| Purpose | Expected endpoint |
| --- | --- |
| Health and version | `GET /api/server/version`, `GET /api/users/me` |
| Text search | `POST /api/search/smart` (query, type IMAGE or VIDEO, page, size, plus personIds, city, state, country, takenAfter, takenBefore) |
| Filter-only browse | `POST /api/search/metadata` (same filters including type, ordered by date, newest first) |
| People row | `GET /api/people` (hidden people excluded, named first) and `GET /api/people/{id}/thumbnail` |
| Places list | `GET /api/search/suggestions?type=country`, `type=state`, `type=city` |
| Grid thumbnails | `GET /api/assets/{id}/thumbnail?size=thumbnail` |
| Full-screen photo | `GET /api/assets/{id}/thumbnail?size=preview` |
| Video playback in the app | `GET /api/assets/{id}/video/playback` (Immich's transcoded stream), proxied with HTTP range requests |
| Backend input | Photos: preview (fast) or `GET /api/assets/{id}/original` (best quality). Videos: original |
| Source metadata | `GET /api/assets/{id}` (type, duration, dateTimeOriginal, GPS, timezone, description, stack) |
| Upload result | `POST /api/assets` (multipart: assetData, deviceAssetId, deviceId="immich-remix", fileCreatedAt, fileModifiedAt); JPEG for photos, MP4 for videos |
| Fix metadata | `PUT /api/assets` (dateTimeOriginal, latitude, longitude, description) |
| Stack | `POST /api/stacks` with assetIds, primary first; if the source is already in a stack, add to that stack instead |
| Album | `GET /api/albums`, `POST /api/albums`, `PUT /api/albums/{id}/assets` |
| Tag (optional) | `PUT /api/tags/assets` or the version's equivalent |

Search returns photos and videos. A live photo is treated as a photo, using its still image only. The backend proxies every thumbnail so the API key never reaches the browser, and sets cache headers so the phone does not re-download thumbnails.

### Write-back rules

1. Encode the result. Photos: JPEG (quality from Settings, default 92). Videos: H.264 MP4 at the original's frame rate, with AAC audio. The original's audio is muxed back when "keep audio" is on. If the user trimmed, only the trimmed segment is saved.
2. Copy metadata from the source. Photos: EXIF date taken, timezone offset and GPS with piexif, plus `ImageDescription` and `Software` = "immich-remix". Videos: `creation_time` and location (QuickTime location tag) written with ffmpeg metadata options.
3. Upload with fileCreatedAt and fileModifiedAt set to the source's date taken, so the remix lands next to the original on the timeline.
4. Set the description to `Remix: <style name> · <backend name>`, plus the custom prompt if one was used.
5. Stack with the original. The original stays primary by default (setting). Never modify, move or delete the original asset.
6. Add to the configured album (default "Remixes", created on first save if missing) and the optional tag.
7. Record the new asset id against the result and return a deep link: `<IMMICH_URL>/photos/<assetId>`.
8. If any step after upload fails, keep the uploaded asset, report which step failed, and offer a retry of only the remaining steps.

### Minimum API key permissions

Read assets, view and download assets, upload assets, update assets, read people, use search, create and update stacks, read and create albums, add assets to albums, and assign tags if tagging is enabled. Map these to the exact permission names in the target Immich version, and list them in the README.

## Pluggable backends

Every backend implements one small interface, so adding a provider means adding one file and registering it. Model names are configuration, never hard-coded, because providers rename and replace models often.

### Interface

```python
class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"

class Provider(Protocol):
    id: str                          # "gemini", "openai", "stability", "runway", "luma", "comfyui"
    name: str                        # shown in the UI
    media_types: set[MediaType]      # what this backend can remix
    leaves_network: bool             # drives the "Sent to Google" / "Runs locally" note
    max_variations: dict[MediaType, int]
    max_input_px: int                # long edge; the runner resizes before calling
    max_video_seconds: float | None  # clip limit; the runner trims or segments to fit

    async def health(self) -> HealthResult: ...
    async def remix(self, req: RemixRequest) -> RemixResult: ...

class RemixRequest(BaseModel):
    media_type: MediaType
    data: bytes                      # JPEG/PNG, or H.264 MP4; already normalized
    mime: str
    prompt: str                      # final prompt built from the style preset
    negative_prompt: str | None
    strength: float | None           # 0..1, how far from the original; ignored if unsupported
    variations: int
    seed: int | None
    style_reference: bytes | None    # optional reference image from the preset
    options: dict                    # provider-specific overrides from the style preset

class RemixResult(BaseModel):
    outputs: list[bytes]
    mime: str
    provider_model: str              # the exact model id used, stored in history
    cost_estimate_usd: float | None
```

If a provider cannot return several images in one call, the runner calls it once per variation. Providers raise typed errors (`AuthError`, `RateLimited`, `ContentRefused`, `Timeout`, `ProviderError`) so the UI can show a clear message.

**Long videos.** Video backends accept only short clips per call, and the limits differ by provider. If the selected range is longer than `max_video_seconds`, the trimmer asks the user to shorten it. When a style is marked `segmentable`, the runner can instead split the clip into segments, remix each with the same prompt and seed, and join them with ffmpeg. Joins can show visible style drift, so the UI warns before a segmented job.

### Initial providers

| Provider | Media | How it works | Config |
| --- | --- | --- | --- |
| Google Gemini | Photos | Image-editing call to Gemini's image model ("Nano Banana" family) with the photo and the style prompt. Closest to Google's own Remix. | `GEMINI_API_KEY`, model id |
| OpenAI | Photos | Image edits endpoint with the photo and prompt. | `OPENAI_API_KEY`, model id |
| Stability AI | Photos | Stable Image style-transfer or control endpoints; a preset can supply a style reference image. | `STABILITY_API_KEY`, endpoint choice |
| Runway | Videos | Video-to-video restyling with Runway's Aleph model, which keeps the original motion and structure. Short clips per call (about 5 s per [one comparison](https://www.atlabs.ai/blog/runway-aleph-vs-luma-modify-video)). | `RUNWAY_API_KEY`, model id |
| Luma | Videos | Luma's Modify Video restyles footage while keeping motion and framing, with a choice of how strong the change is. Longer clips than Runway (up to about 10 s). | `LUMA_API_KEY`, model id |
| ComfyUI (user's own server) | Photos and videos | Submits a workflow JSON, uploads the input, polls `/history`, downloads the output. Photos: Qwen-Image-Edit or FLUX.1 Kontext. Videos: a Wan-family video edit workflow (for example Wan VACE). | `COMFYUI_URL`, workflow files |

Model ids, clip limits and prices change often, so each lives in configuration with a documented default. The adapters must read the provider's current API docs at build time.

### ComfyUI workflow templates

Ship two workflow JSON files under `/app/workflows/` (Qwen-Image-Edit and FLUX.1 Kontext), exported in ComfyUI's API format. The user can drop more into `/data/workflows/`. Templates use placeholders the runner substitutes: `{{input_image}}`, `{{prompt}}`, `{{negative_prompt}}`, `{{seed}}`, `{{strength}}`. Each template has a small sidecar YAML naming the output node id and any options. Document in the README which custom nodes and model files the templates need.

Also ship one video workflow template (a Wan-family video edit workflow) with the same placeholders plus `{{input_video}}`, `{{fps}}` and `{{frames}}`. Video templates declare `media_type: video` in their sidecar so the app only offers them for videos.

## Styles, configuration, data and API

### Style presets

Styles are YAML files. Built-ins ship in `/app/styles/` and user styles live in `/data/styles/`; a user file with the same id overrides a built-in. Every prompt must tell the model to keep the people, faces, pose and composition recognizable, because that is what makes a remix feel like *your* photo.

```yaml
id: watercolor
name: Watercolor
category: painted
media_types: [image, video]
preview:
  image: watercolor.webp        # the reference photo rendered in this style
  video: watercolor.mp4         # the reference clip in this style, 3 s loop
default_provider:
  image: gemini
  video: luma
prompt: >
  Repaint this photo as a loose, luminous watercolor painting on textured paper.
  Keep every person, face, pose and the overall composition recognizable.
negative_prompt: photorealistic, text, watermark
strength: 0.65
segmentable: false
providers:                      # optional per-provider overrides
  comfyui: { workflow: qwen-image-edit, steps: 30 }
  stability: { style_image: watercolor-ref.jpg }
```

**Custom** is not a file. It uses the user's text as the prompt, wrapped with the same "keep it recognizable" instruction. This matches Apple's "Any Style" option and free-text prompting in Google Photos.

### Built-in style library

The app ships 44 built-in styles plus Custom. The list starts from Google Photos Remix and Video Remix as the baseline. It then adds every distinct style offered by Apple Image Playground, Samsung Galaxy AI, Meta's Restyle, Google Whisk, Picsart, Prisma, Pika and Adobe Firefly. Names are generic, never a studio, artist or brand. A style is video-capable only where the look holds up across moving frames.

| Category | Style | Media | Seen in |
| --- | --- | --- | --- |
| Illustrated | 3D Animated | Photo, video | Google Remix, Apple (Animation), Samsung (3D Cartoon), Pika |
| Illustrated | Anime | Photo, video | Google Remix, Apple, Meta, Picsart, Pika |
| Illustrated | Cartoon | Photo, video | Samsung Portrait Studio, Picsart, Fotor |
| Illustrated | Comic Book | Photo, video | Google Remix, Samsung |
| Illustrated | Claymation | Photo, video | Pika, Gemini Omni demos |
| Illustrated | 8-bit Pixel Art | Photo, video | Google Remix, Meta, Picsart |
| Illustrated | Chibi Sticker | Photo | Google Remix, Google Whisk, Samsung (Cutout) |
| Illustrated | Storybook Illustration | Photo | Apple (Illustration), Samsung (Illustrations) |
| Illustrated | Flat Vector | Photo | Apple (Vector) |
| Illustrated | Line Art | Photo | Samsung (Outline) |
| Illustrated | Fantasy Adventurer | Photo | Google Remix, Picsart (Fantasy) |
| Illustrated | Superhero | Photo | Picsart |
| Painted and drawn | Watercolor | Photo, video | Google Remix and Video Remix, Apple, Samsung, Meta |
| Painted and drawn | Oil Painting | Photo, video | Google Remix and Video Remix, Apple, Samsung (artistic painting) |
| Painted and drawn | Sketchbook Pencil | Photo, video | Google Video Remix (raw sketchbook), Apple, Samsung |
| Painted and drawn | Pen Sketch | Photo | Google Remix |
| Painted and drawn | Charcoal | Photo, video | Gemini Omni demos |
| Painted and drawn | Impressionist Brushwork | Photo | Prisma |
| Painted and drawn | Pop Art | Photo | Samsung, Prisma |
| Painted and drawn | Art Deco | Photo | Google Remix |
| Painted and drawn | Block Print | Photo | Apple (Print) |
| Painted and drawn | Mosaic | Photo | Prisma |
| Collectibles | Collectible Figurine | Photo | Google Remix |
| Collectibles | Enamel Pin | Photo | Google Remix, Google Whisk |
| Collectibles | Plushie | Photo | Google Whisk |
| Collectibles | Capsule Toy | Photo | Google Whisk |
| Photo looks | Professional Headshot | Photo | Google Remix, Samsung (professional portrait) |
| Photo looks | Dramatic Black and White | Photo, video | Google Remix |
| Photo looks | Film Noir | Photo, video | Meta |
| Photo looks | Sun-worn Vintage | Photo, video | Google Remix, Samsung (Vintage), Adobe Firefly (antique photo) |
| Photo looks | 35mm Film Grain | Photo, video | Google Remix, Google Photos Moods |
| Photo looks | Instant Film with Flash | Photo | Google Remix |
| Photo looks | Fashion Photoshoot | Photo | Google Remix |
| Photo looks | Red Carpet | Photo | Google Remix |
| Photo looks | Photo Booth Strip | Photo | Google Remix |
| Photo looks | Fisheye | Photo | Samsung Portrait Studio |
| Occasions | Birthday Card | Photo | Google Remix |
| Occasions | Watercolor Greeting Card | Photo | Google Remix |
| Occasions | Holiday Scene | Photo | Google Remix (Christmas-themed) |
| Occasions | Halloween Ghost | Photo, video | Meta |
| Scenes | Golden Morning Relight | Photo, video | Google Video Remix (cinematic relighting) |
| Scenes | Greenhouse Backdrop | Photo, video | Google Video Remix (background swap) |
| Scenes | Underwater World | Photo, video | Meta |
| Scenes | Snowy Wonderland | Photo, video | Meta |

Left out on purpose: emoji-style output (it needs a separate sticker pipeline), novelty effects such as melt and explode (they are effects, not styles), and avatar packs that train on 10 or more selfies (a different workflow). A camera-angle trend Google offers, the "microwave angle," is also left out because it changes the shot rather than the style. Each style's prompt, default backends and preview are written as part of the build.

### Style previews

Every style shows a preview so people choose by sight, not by name.

- **One reference set.** Ship one original reference photo: a person outdoors, face clearly visible, with some background. Also ship one 3-second reference clip. Both must be created for the project or licensed for redistribution. Every built-in preview is that same reference rendered in the style, so cards compare like for like.
- **Files.** WebP stills at 600 × 600 px for cards and 1600 px long edge for the full-screen view. MP4 loops for video previews: H.264, 3 s, muted, under 1 MB. They are bundled in the image under `/app/styles/previews/`.
- **Where they show.** On the style card, in the full-screen preview with a before/after slider against the unstyled reference, and on video cards as a loop that plays when selected.
- **Custom styles.** Saving a new or edited style generates its preview by running it on the reference photo, and on the clip if the style supports video, with the style's default backend. The estimated cost is shown first. The user can upload their own preview image instead. Until a preview exists, the card shows a neutral placeholder with the style name.
- **Regenerate.** Settings can regenerate any preview, for example after switching backends.
- **Maintainers.** A script, `scripts/build_previews.py`, regenerates every built-in preview from the reference set, so previews stay consistent when prompts change.

### Configuration

Environment variables set the essentials. Everything else is editable in Settings and stored in SQLite. Environment values win over stored values when both exist.

| Variable | Required | Purpose |
| --- | --- | --- |
| `IMMICH_URL` | Yes | Base URL of the Immich server, for example `http://192.168.1.20:2283` |
| `IMMICH_API_KEY` | Yes | API key with the permissions listed above |
| `IMMICH_PUBLIC_URL` | No | URL used for "Open in Immich" links if it differs from `IMMICH_URL` (for example a Tailscale address) |
| `APP_PASSWORD` | Recommended | Passcode for the web UI; blank disables login |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `STABILITY_API_KEY` | No | Photo backends; each enables its provider |
| `RUNWAY_API_KEY`, `LUMA_API_KEY` | No | Video backends; each enables its provider |
| `COMFYUI_URL` | No | The user's own ComfyUI server, for example `http://192.168.1.30:8188` |
| `MAX_PHOTO_JOBS`, `MAX_VIDEO_JOBS` | No | Concurrency; defaults 2 and 1 |
| `TZ` | No | Container time zone for logs |

### Data model (SQLite)

| Table | Key fields |
| --- | --- |
| `settings` | key, value (JSON); API keys entered in the UI are encrypted with a key generated on first run and stored in `/data/secret.key` |
| `styles` | id, yaml, preview\_image\_path, preview\_video\_path, hidden, sort\_order (user styles and overrides; built-ins come from files) |
| `jobs` | id, source\_asset\_id, media\_type, style\_id, custom\_prompt, provider\_id, provider\_model, variations, clip\_start\_s, clip\_end\_s, segmented, status (queued, running, done, failed), error\_code, error\_message, cost\_estimate\_usd, created\_at, finished\_at |
| `results` | id, job\_id, index, file\_path, mime, width, height, duration\_s, saved\_asset\_id, saved\_at, discarded |

Results live in `/data/results/<job_id>/<index>.<jpg|mp4>`. A daily cleanup deletes unsaved, undiscarded results older than the retention setting. Saved results keep only their database row, since the image now lives in Immich.

### App API (consumed only by the bundled UI)

| Method and path | Purpose |
| --- | --- |
| `POST /api/login`, `POST /api/logout` | Passcode session (HTTP-only cookie) |
| `GET /api/status` | Immich connection, server version, enabled providers and their media types |
| `GET /api/people` | People for the filter row |
| `GET /api/people/{id}/thumb` | Proxied face thumbnail |
| `GET /api/places?q=` | Countries, states and cities, filtered by text |
| `POST /api/search` | Body: query, personIds, place, dateFrom, dateTo, type (all, photo, video), page. Returns asset ids, type, dates, aspect ratios, durations |
| `GET /api/assets/{id}/thumb?size=thumbnail\|preview` | Proxied image |
| `GET /api/assets/{id}/video` | Proxied video playback with range requests |
| `GET /api/styles` | Styles grouped by category, with media types and preview URLs |
| `PUT /api/styles/{id}`, `DELETE /api/styles/{id}` | User edits to styles |
| `GET /api/styles/{id}/preview?kind=card\|full\|video` | Preview image or loop |
| `POST /api/styles/{id}/preview` | Generate a preview on the reference set, or upload one |
| `POST /api/jobs` | Body: assetId, styleId or customPrompt, providerId, variations, clipStart, clipEnd. Returns the job id |
| `GET /api/jobs/{id}` and `GET /api/jobs/{id}/events` | Job state; server-sent events for live progress |
| `GET /api/results/{id}/media` | Result image or video, with range requests for video |
| `POST /api/results/{id}/save` | Runs the write-back; returns the Immich asset id and link |
| `POST /api/results/{id}/discard` | Marks discarded and deletes the file |
| `GET /api/history?page=` | Past jobs with results |
| `GET /api/settings`, `PUT /api/settings` | Settings (API keys write-only, never returned) |
| `POST /api/providers/{id}/test` | Connection test |
| `GET /healthz` | Container health check |

## Deployment

Ship a multi-stage `Dockerfile`: stage one builds the frontend with Node, stage two is `python:3.12-slim` with the backend and the built static files. Run as a non-root user, listen on port 8080, keep all state in `/data`, and add a `HEALTHCHECK` on `/healthz`. Include ffmpeg for video work. Target image size under 400 MB. No compose file.

On Proxmox it runs in an existing Docker host (an LXC or VM). ComfyUI, if used, runs elsewhere on a GPU machine and is reached by URL.

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

The README covers: creating the Immich API key and its permissions, the `docker run` command, adding to a phone home screen, setting up each backend, and the ComfyUI models and custom nodes the templates need.

## Security and privacy

- The Immich API key and provider keys stay on the server. They are never sent to the browser, logged, or returned by the settings API.
- Passcode login with a signed HTTP-only session cookie (30-day expiry) and rate-limited attempts.
- **Remote access is the user's job.** The app is built for a home network. To use it away from home, the user puts it behind their own VPN, such as Tailscale. The app ships no tunnel, public sharing or reverse proxy. The README points to Tailscale's setup and warns against forwarding the port to the internet.
- Each provider declares whether media leaves the network, and the UI shows that before every remix.
- Strip metadata from anything sent to a cloud backend: EXIF for photos, container metadata for videos. Restore the source's metadata only on the output saved to Immich.
- Never modify or delete existing Immich assets. The only writes are new uploads, metadata on those uploads, stacks, album membership and tags.

## Error handling and edge cases

| Case | Behavior |
| --- | --- |
| HEIC or HEIF photo | Convert to JPEG with pillow-heif before sending |
| RAW photo | Use Immich's preview JPEG as input |
| Very large photo | Resize to the provider's max long edge (default 2048 px), applying EXIF rotation first |
| Live photo | Treated as a photo, using the still image only |
| Video codec a backend can't take (HEVC, ProRes) | Transcode to H.264 with ffmpeg before sending |
| Video longer than the backend's limit | Trimmer opens preset to the first N seconds; segmented remix only for `segmentable` styles, with a warning |
| Backend returns a different frame rate or length | Conform to the original frame rate; keep the original audio aligned, trimming or padding by under 0.5 s |
| Portrait or rotated video | Respect the rotation metadata in the input and output |
| Provider refuses content | Show "This style couldn't be applied" plus the provider's reason if given; suggest another backend |
| Rate limit or timeout | One automatic retry with backoff, then a clear failure with Try again. Default timeouts: 180 s for cloud photos, 900 s for cloud videos, 1800 s for ComfyUI |
| Bad API key or ComfyUI unreachable | Provider marked unhealthy in Settings and hidden from the style sheet |
| Immich unreachable | Full-screen banner with the error and a retry; History stays viewable |
| Container restarts mid-job | Job marked failed with "Interrupted" and can be retried |
| Partial save failure | Keep the uploaded asset, show which step failed, retry only the remaining steps |

## Acceptance criteria

- [ ] On an iPhone and an Android phone, the app installs to the home screen and opens full screen.
- [ ] Library loads the first screen of thumbnails in under 2 seconds on LAN.
- [ ] Search finds photos and videos by text, by one or more people, by city or country, by date, and by any combination.
- [ ] All 44 built-in styles appear, grouped by category, each with its preview image; video-capable styles show a looping preview on videos.
- [ ] Long-pressing a style shows its full-screen before/after preview.
- [ ] Saving a custom style generates a preview, or accepts an uploaded one.
- [ ] A photo remix with Gemini completes and shows a before/after view, with progress visible while it runs.
- [ ] The same photo flow works with OpenAI, Stability and the user's own ComfyUI server, each enabled only by configuration.
- [ ] A video remix works with Runway, Luma and a ComfyUI video workflow, keeping the original's motion, frame rate and audio.
- [ ] Saving creates a new Immich asset with the original's date taken and location, stacked with the original (original primary), in the "Remixes" album, with the style in its description.
- [ ] The original asset is unchanged after a save.
- [ ] Closing the browser mid-job does not lose the job; it appears in History when finished.
- [ ] No API key appears in any browser network response or in the logs.
- [ ] A new provider can be added by implementing the interface in one file and registering it.
- [ ] A new style can be added by dropping a YAML file and its preview into `/data/styles/` without rebuilding.
- [ ] Unit tests cover prompt building, metadata copy for photos and videos, the write-back sequence (Immich mocked), clip trimming and segmenting, and each provider adapter (HTTP mocked).

## Open questions

- **More than one user:** one Immich API key means every save goes to that account. Should family members sign in with their own Immich accounts so remixes land in their own libraries?
- **Stack primary:** is keeping the original as primary the right default, or should a fresh remix be the visible one?
- **Output size:** cloud models often return about 1024 to 2048 px for photos and 720p to 1080p for video. Is that enough, or should there be an optional upscale step?
- **Cost display:** show an estimated cost per remix for cloud backends, or leave it out?
- **Long videos:** trim only, or allow segmented remixing with possible style drift at the joins?

## Sources

Style research, as of the date above:

- Google Photos Remix launch styles: [Google blog](https://blog.google/products-and-platforms/products/photos/photo-to-video-remix-create-tab/), [9to5Google](https://9to5google.com/2025/08/13/google-photos-remix-feature-how-to-use/)
- Remix expanded to 13 styles (8-bit, watercolor, stickers, enamel pins): [9to5Google](https://9to5google.com/2025/12/11/google-photos-remix-wide-rollout/)
- Remix template names (figurine, headshot, black and white, chibi sticker, art deco, vintage, film grain, instant film): [TechMitra](https://techmitra.in/google-photos-ai-remix-tool/)
- 20+ new Remix templates: [Google Photos on X](https://x.com/googlephotos/status/2049551137611956515)
- Red carpet, birthday card and photo booth templates: [Jetstream](https://jetstream.blog/en/google-photos-updates-september-2026/)
- Video Remix (relighting, background swap, watercolor, sketchbook, oil painting): [TechCrunch](https://techcrunch.com/2026/07/08/google-photos-adds-a-new-ai-video-remix-tool/), [Jetstream](https://jetstream.blog/?p=219562)
- Apple Image Playground styles: [TechCrunch](https://techcrunch.com/2025/06/11/apple-is-salvaging-image-playground-with-a-boost-from-chatgpt/), [App Store](https://apps.apple.com/app/image-playground/id6479176117)
- Samsung Galaxy AI styles: [Samsung Newsroom](https://news.samsung.com/sg/the-art-of-the-do-over-crafting-the-best-images-and-visuals-with-galaxy-ai), [Android Central](https://www.androidcentral.com/apps-software/how-to-use-portrait-studio-on-a-samsung-galaxy-phone)
- Meta Restyle presets: [AlternativeTo](https://alternativeto.net/news/2025/10/instagram-stories-get-new-generative-ai-features-to-restyle-your-photos-and-videos), [Metricool](https://metricool.com/instagram-restyle-ai/), [RetailBoss](https://retailboss.co/how-meta-ai-restyle-makes-every-instagram-story-uniquely-yours/)
- Google Whisk styles: [Whisk guide](https://thewhiskai.net/)
- Picsart avatar styles: [Picsart blog](https://picsart.com/blog/?p=175666)
- Prisma art filters: [MakeTechEasier](https://maketecheasier.com/photo-editors-use-artificial-intelligence), [Virgin Media community](https://community.virginmedia.com/t5/Digital-life/Prisma-the-photo-app-that-is-more-than-just-paint-by-numbers/ba-p/3169013)
- Pika presets and Gemini Omni styles: [Atlabs comparison](https://www.atlabs.ai/blog/runway-act-two-vs-luma-modify-video), [DEV Community](https://dev.to/alifar/google-photos-video-remix-brings-gemini-omni-video-styles-to-eligible-subscribers-4l6a)
- Adobe Firefly presets: [Adobe developer docs](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/concepts/style-presets/)
- Video backends (Runway Aleph, Luma Modify Video): [Atlabs comparison](https://www.atlabs.ai/blog/runway-aleph-vs-luma-modify-video), [Muapi](https://muapi.ai/ai-video-editing-api)
