from pydantic import BaseModel


class Env(BaseModel):
    IMMICH_URL: str
    IMMICH_API_KEY: str
    IMMICH_PUBLIC_URL: str | None = None
    APP_PASSWORD: str | None = None
    GEMINI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    STABILITY_API_KEY: str | None = None
    RUNWAY_API_KEY: str | None = None
    LUMA_API_KEY: str | None = None
    COMFYUI_URL: str | None = None
    MAX_PHOTO_JOBS: int = 2
    MAX_VIDEO_JOBS: int = 1
    TZ: str | None = None
    DATA_DIR: str = "/data"
