from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # CarFINDa/


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    TAVILY_API_KEY: str = ""

    SIDECAR_URL: str = "http://localhost:3000"
    SIDECAR_TOKEN: str = ""

    CAPTCHA_SOLVER_PROVIDER: str = "capsolver"
    CAPTCHA_SOLVER_API_KEY: str = ""
    CAPTCHA_SOLVER_TIMEOUT_SECONDS: int = 120

    DATABASE_URL: str = ""

    ENVIRONMENT: str = "development"

    model_config = {
        "env_file": [".env", str(_PROJECT_ROOT / ".env")],
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
