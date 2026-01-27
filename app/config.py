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


# Singleton instance
settings = Settings()