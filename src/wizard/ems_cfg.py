"""The cfg.customer.yml files the EMS containers mount from /opt/arcnode —
same paths and keys the cloud's UserData writes (cfn_resources.py)."""

from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

GATEWAY_CFG_FILE: Final[str] = "gateway-cfg.customer.yml"
HMI_CFG_FILE: Final[str] = "hmi-cfg.customer.yml"


class GatewayCfg(BaseModel):
    """industrial-gateway's overlay — only site_id today."""

    site_id: str


class HmiCfg(BaseModel):
    """The HMI SPA's runtime overlay; camelCase is its config.ts schema.
    Relative URIs: its nginx proxies same-origin to device-api + analyst."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    site_id: str
    deployment_name: str
    device_api_uri: str = "/api"
    chat_api_uri: str = ""
    mqtt_uri: str = ""  # empty → the SPA derives ws(s)://<host>/mqtt


class AnalystMarket(BaseModel):
    """Key stays wholesale_market — ems-analyst's contract, though the order
    field is market_region."""

    wholesale_market: str
    settlement_point: str


class AnalystOllamaSettings(BaseModel):
    """ems-analyst's ``settings:`` block for Ollama (its OllamaSettings,
    discriminated on llm_provider)."""

    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embedding_model: str


class AnalystCfg(BaseModel):
    """/opt/arcnode/analyst-cfg.customer.yml, merged over the analyst's
    defaults via CFG_CUSTOMER_PATH. Two pages write it — Ollama the
    ``settings:``, Site the rest — so each merges, never overwrites."""

    site_id: str | None = None
    market: AnalystMarket | None = None
    settings: AnalystOllamaSettings | None = None


def read_analyst_cfg(path: Path) -> AnalystCfg:
    """What's on disk now; empty when no page has written it yet."""
    if not path.exists():
        return AnalystCfg()
    return AnalystCfg.model_validate(yaml.safe_load(path.read_text()) or {})


def update_analyst_cfg(path: Path, update: AnalystCfg) -> None:
    """Set the fields ``update`` has, keep the rest."""
    merged = AnalystCfg.model_validate(
        read_analyst_cfg(path).model_dump(exclude_none=True)
        | update.model_dump(exclude_none=True)
    )
    write_yaml(path, merged)


def write_yaml(path: Path, cfg: BaseModel) -> None:
    """One cfg file, keys in model order, camelCase where the model says."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = cfg.model_dump(exclude_none=True, by_alias=True)
    path.write_text(yaml.safe_dump(body, sort_keys=False))
