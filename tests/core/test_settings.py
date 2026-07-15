from app.core.config import Settings


def test_settings_round_trips_all_fields() -> None:
    data = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/db",
        "secret_key": "test-secret",
        "jwt_algorithm": "HS256",
        "jwt_expire_minutes": 60,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "user@example.com",
        "smtp_password": "app-password",
        "smtp_from_address": "noreply@example.com",
        "log_level": "INFO",
    }

    settings = Settings(**data)

    for key, value in data.items():
        assert getattr(settings, key) == value
