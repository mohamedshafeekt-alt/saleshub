import json
import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_from_address: str
    log_level: str = "INFO"


load_dotenv()
settings = Settings(**json.loads(os.environ["APP_CONFIG"]))
