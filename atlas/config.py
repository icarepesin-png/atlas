"""Central configuration: YAML file + environment variables (.env).

Usage:
    from atlas.config import get_config, get_settings
    cfg = get_config()            # parsed config.yaml (dict-like, validated)
    settings = get_settings()     # secrets / env vars
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class Settings(BaseSettings):
    """Secrets and environment-dependent values. Never stored in YAML."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    fred_api_key: str = ""
    polygon_api_key: str = ""
    fmp_api_key: str = ""
    alpha_vantage_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    database_url: str = "sqlite:///atlas.db"
    atlas_cloud_db: str = ""          # base Postgres cloud (synchro dashboard)
    live_trading_ack: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def live_trading_enabled(self) -> bool:
        return self.live_trading_ack == "I_UNDERSTAND_THE_RISKS"


class ScoringWeights(BaseModel):
    fundamental: float = 0.35
    technical: float = 0.25
    macro: float = 0.15
    sector: float = 0.15
    sentiment: float = 0.10

    def normalized(self) -> dict[str, float]:
        total = sum(self.model_dump().values())
        return {k: v / total for k, v in self.model_dump().items()}


class Config(BaseModel):
    """Validated view over config.yaml. Unknown keys are kept in `raw`."""

    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def universe(self) -> dict[str, Any]:
        return self.raw.get("universe", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.raw.get("data", {})

    @property
    def scoring_weights(self) -> ScoringWeights:
        return ScoringWeights(**self.raw.get("scoring", {}).get("weights", {}))

    @property
    def scoring(self) -> dict[str, Any]:
        return self.raw.get("scoring", {})

    @property
    def signals(self) -> dict[str, Any]:
        return self.raw.get("signals", {})

    @property
    def portfolio(self) -> dict[str, Any]:
        return self.raw.get("portfolio", {})

    @property
    def risk(self) -> dict[str, Any]:
        return self.raw.get("risk", {})

    @property
    def backtest(self) -> dict[str, Any]:
        return self.raw.get("backtest", {})

    @property
    def validation(self) -> dict[str, Any]:
        return self.raw.get("validation", {})

    @property
    def macro(self) -> dict[str, Any]:
        return self.raw.get("macro", {})

    @property
    def sectors(self) -> dict[str, Any]:
        return self.raw.get("sectors", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self.raw.get("execution", {})

    @property
    def cache_dir(self) -> Path:
        p = PROJECT_ROOT / self.data.get("cache_dir", "data/cache")
        p.mkdir(parents=True, exist_ok=True)
        return p


@functools.lru_cache(maxsize=1)
def get_config(path: Path | None = None) -> Config:
    with open(path or CONFIG_PATH, encoding="utf-8") as f:
        return Config(raw=yaml.safe_load(f))


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
