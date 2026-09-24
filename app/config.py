from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./mailveyra.db"
    gemini_api_key: str | None = None
    gemini_models: str = "gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-3-flash-preview"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"
    app_secret_key: str = "dev-only-change-me"
    upload_dir: str = "data/uploads"

    @property
    def gemini_model_list(self) -> list[str]:
        return [model.strip() for model in self.gemini_models.split(",") if model.strip()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

