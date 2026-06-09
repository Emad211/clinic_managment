"""ai_service configuration (env-driven, prefix AI_).

The knowledge pipeline talks to LLMs through AvalAI (OpenAI-compatible). Each
pipeline layer can use a different/cheaper model — model tiering keeps cost down
(cheap for routing/classification, strong for extraction/verification).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///ai_service.db"

    # Model Gateway → AvalAI (OpenAI-compatible). Empty key → NullModel (dev).
    avalai_api_key: str = ""
    avalai_base_url: str = "https://api.avalai.ir/v1"

    # per-layer model tiering
    model_routing: str = "gpt-4o-mini"
    model_extraction: str = "gpt-4o"
    model_verification: str = "gpt-4o"


settings = Settings()

# layer -> configured model name
LAYER_MODELS = {
    "routing": settings.model_routing,
    "chunking": settings.model_routing,
    "extraction": settings.model_extraction,
    "verification": settings.model_verification,
}
