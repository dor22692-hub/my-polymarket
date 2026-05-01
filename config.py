from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Polymarket
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    polymarket_private_key: str = ""

    # Polygon
    polygon_rpc_url: str = "https://polygon-rpc.com"
    polygon_ws_url: str = "wss://polygon-bor-rpc.publicnode.com"

    # News
    newsapi_key: str = ""
    tavily_api_key: str = ""

    # Database
    database_url: str = "sqlite:///./polymarket.db"

    # Thresholds
    whale_win_rate_threshold: float = 0.80
    whale_min_trades: int = 10
    confidence_threshold: float = 0.80
    log_level: str = "INFO"


settings = Settings()
