import json
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_from_address: str
    log_level: str = "INFO"
    frontend_base_url: str = "http://localhost:40843"
    storage_backend: Literal["local", "s3"] = "local"
    aws_region: str = ""
    s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""


load_dotenv()
settings = Settings(**json.loads(os.environ["APP_CONFIG"]))
