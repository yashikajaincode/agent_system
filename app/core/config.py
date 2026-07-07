"""
Application configuration.

Loads settings from environment variables / .env file using pydantic-settings.
Single source of truth for anything configurable (API keys, model name, paths).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.3
    output_dir: str = "output"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
