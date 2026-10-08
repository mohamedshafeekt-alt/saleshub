import json
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Either database_url, or the db_* parts (password is URL-encoded for you).
    database_url: str = ""
    db_name: str = ""
    db_username: str = ""
    db_password: str = ""
    db_host: str = ""
    db_port: int = 5432
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

    @model_validator(mode="after")
    def _build_database_url(self) -> "Settings":
        if not self.database_url:
            if not (self.db_name and self.db_host):
                raise ValueError("set database_url or db_name + db_host")
            self.database_url = URL.create(
                "postgresql+asyncpg",
                username=self.db_username,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
            ).render_as_string(hide_password=False)
        return self


load_dotenv()
settings = Settings(**json.loads(os.environ["APP_CONFIG"]))
