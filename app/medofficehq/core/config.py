from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Athena Health API Integration"
    
    # Athena Health API Settings (Legacy - for backward compatibility)
    # For multi-environment support, use environment-specific variables:
    # - ATHENA_SANDBOX_CLIENT_ID, ATHENA_SANDBOX_CLIENT_SECRET, ATHENA_SANDBOX_PRACTICE_ID, ATHENA_SANDBOX_API_BASE_URL
    # - ATHENA_PRODUCTION_CLIENT_ID, ATHENA_PRODUCTION_CLIENT_SECRET, ATHENA_PRODUCTION_PRACTICE_ID, ATHENA_PRODUCTION_API_BASE_URL
    ATHENA_Client_ID: Optional[str] = None
    ATHENA_Client_Secret: Optional[str] = None
    ATHENA_PRACTICE_ID: Optional[str] = None
    ATHENA_API_BASE_URL: str = "https://api.preview.platform.athenahealth.com/v1"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings() 