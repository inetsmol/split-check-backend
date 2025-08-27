import json
from pathlib import Path

from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent  # путь до корня проекта


class ConfigBase(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


class AppConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="APP_")

    base_url: str = "https://biggarik.ru"
    admin_emails: list[str]  = ["eduard.demerchyan@gmail.com", "inetsmol@gmail.com", "smolinet@yandex.ru"]
    environment: str = "dev"
    log_level: str = "DEBUG"
    service_name: str = "scannsplit-app"
    upload_directory: str = "images"
    deep_link_url: str = "sscannsplit://scannsplit.com/shared/"
    enable_docs: bool = True
    allowed_ips: list[str] = ["127.0.0.1", "192.168.0.1"]
    max_processes: int = 4
    host: str = "0.0.0.0"
    port: int = 8080

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def is_development(self) -> bool:
        return self.environment in ["dev", "local"]

    @field_validator('admin_emails', 'allowed_ips', mode='before')
    def parse_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return v


class DatabaseConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = "postgres"
    database: str = "scannsplit"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"


class RedisConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    expiration: int = 3600



class TelegramConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr = "default"


class EmailConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="MAIL_")

    username: str = "your-email@example.com"
    password: SecretStr = "your-password"
    from_email: str = "your-email@example.com"
    port: int = 587
    server: str = "smtp.gmail.com"
    ssl_tls: bool = False
    starttls: bool = True
    use_credentials: bool = True


class AiConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="AI_")

    anthropic_api_key: SecretStr = "sk-ant-api03-jAR5EFlJrpkjw4QeQ69NGzVo"
    anthropic_model_name: str = "claude-sonnet-4-0"

    openai_api_key: SecretStr = "sk-proj-VdvIppc7mktetmIrN30kZIgb5iPKW5JfktSCNBJ4m4ygfSHuGZ"
    openai_model_name: str = "gpt-4o"


class AuthConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="AUTH_")

    access_secret_key: SecretStr = "jAR5EFlJrpkjw4QeQ69NGz"
    refresh_secret_key: SecretStr = "cw0VRathl089NGzVoypmDcC3"

    algorithm: str = "HS256"
    # Время действия токенов
    access_token_expire_minutes: int = 600
    refresh_token_expire_days: int = 365
    refresh_token_expire_minutes: int = 525600


class LoggingConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="LOG_")

    # Настройки для Syslog
    syslog_host: str = "localhost"
    syslog_port: int = 1514
    syslog_enabled: bool = False

    # GRAYLOG
    graylog_host: str = "192.168.67.101"
    graylog_port: int = 12201
    graylog_enabled: bool = True


class ExchangeConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="EXCHANGE_")

    open_exchange_rates_api_key: SecretStr = "64878c982e8e42e089b8fae75496740a"


class SupabaseConfig(ConfigBase):
    model_config = SettingsConfigDict(env_prefix="SUPABASE_")

    jwt_secret: SecretStr = "sb_secret_ZATo4WWzF_c41H7rKi0E_A_ZXK-7awQ"

    algorithm: str = "HS256"


class Config(BaseSettings):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)

    @classmethod
    def load(cls) -> "Config":
        return cls()


config = Config.load()