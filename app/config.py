from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    api_base_url: str = "http://127.0.0.1:8000"
    data_file: str = ".local/bookings.json"
    app_secret_pepper: str = "dev-only-change-me"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
