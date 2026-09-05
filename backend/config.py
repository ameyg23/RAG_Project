"""Environment configuration loading. See docs/ENVIRONMENT.md for the full variable list."""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    GROQ_API_KEY: str | None = os.environ.get("GROQ_API_KEY")
    QDRANT_URL: str | None = os.environ.get("QDRANT_URL")
    QDRANT_API_KEY: str | None = os.environ.get("QDRANT_API_KEY")
    CORS_ALLOWED_ORIGIN: str = os.environ.get("CORS_ALLOWED_ORIGIN", "http://localhost:5173")
    EMBEDDING_MODEL_NAME: str = os.environ.get(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")


settings = Settings()
