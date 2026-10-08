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


def test_settings_builds_database_url_from_parts() -> None:
    settings = Settings(
        db_name="sales_crm_prod",
        db_username="sales_crm_prod_user",
        db_password="5Ck9)1V(sJP}Qk4w",
        db_host="35.244.13.190",
        db_port=5432,
        secret_key="s",
        smtp_host="h",
        smtp_username="u",
        smtp_password="p",
        smtp_from_address="a@b.c",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://sales_crm_prod_user:5Ck9%291V%28sJP%7DQk4w"
        "@35.244.13.190:5432/sales_crm_prod"
    )
