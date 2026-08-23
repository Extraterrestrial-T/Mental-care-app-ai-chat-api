import os
from pydantic_settings import BaseSettings
from typing import List
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

current_dir = Path(__file__).parent

class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Firebase
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "")
    
    # OAuth
    GOOGLE_CLIENT_SECRETS_FILE: str = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")

    GOOGLE_SCOPES: List[str] = [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ]

    # Microsoft Graph / Outlook Calendar OAuth
    MICROSOFT_CLIENT_ID: str = os.getenv("MICROSOFT_CLIENT_ID", "")
    MICROSOFT_CLIENT_SECRET: str = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    MICROSOFT_TENANT_ID: str = os.getenv("MICROSOFT_TENANT_ID", "common")
    MICROSOFT_SCOPES: List[str] = [
        "offline_access",
        "User.Read",
        "Calendars.ReadWrite",
    ]
    
    # URLs - automatically detect localhost vs production
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8000")
    SESSION_COOKIE_NAME = "session_id"
    SESSION_MAX_AGE = 86400 * 7  # 7 days

    @property
    def REDIRECT_URI(self) -> str:
        """OAuth redirect URI"""
        return f"{self.BASE_URL}/auth/callback"

    @property
    def MICROSOFT_REDIRECT_URI(self) -> str:
        """Microsoft OAuth redirect URI"""
        return f"{self.BASE_URL}/auth/microsoft/callback"
    
    @property
    def IS_PRODUCTION(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT == "production"
    
    # Session
    SESSION_COOKIE_NAME: str = "cece_doctor_session"
    SESSION_MAX_AGE: int = 15552000  # 180 days
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]  # In production, specify exact origins
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        # Agent and deployment modules read additional environment variables directly.
        # Do not reject those variables when constructing the shared settings object.
        extra = "ignore"


# Singleton instance
settings = Settings()
