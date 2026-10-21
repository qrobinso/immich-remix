from pydantic import BaseModel, ConfigDict, Field


class Env(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)  # errors would otherwise print the env dict, keys included

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
    MAX_PHOTO_JOBS: int = Field(2, ge=1)
    MAX_VIDEO_JOBS: int = Field(1, ge=1)
    TZ: str | None = None
    DATA_DIR: str = "/data"
