"""YAML config loader with environment variable resolution."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AppConfig:
    name: str
    package: str
    platform: str


@dataclass
class SourceConfig:
    root: str
    layouts_dir: str
    strings_file: str
    manifest: str


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"


@dataclass
class Config:
    app: AppConfig
    source: SourceConfig
    llm: LLMConfig = field(default_factory=LLMConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} references with their values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            raise ValueError(f"Environment variable '{var_name}' is not set")
        return env_val

    return _ENV_VAR_PATTERN.sub(replacer, value)


def _resolve_env_vars_recursive(obj: object) -> object:
    """Recursively resolve env vars in a nested dict/list structure."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars_recursive(item) for item in obj]
    return obj


def load_config(config_path: str | Path) -> Config:
    """Load and validate config from a YAML file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping")

    raw = _resolve_env_vars_recursive(raw)

    # Validate required sections
    for section in ("app", "source"):
        if section not in raw:
            raise ValueError(f"Missing required config section: '{section}'")

    app_raw = raw["app"]
    for key in ("name", "package", "platform"):
        if key not in app_raw:
            raise ValueError(f"Missing required app config field: '{key}'")

    source_raw = raw["source"]
    for key in ("root", "layouts_dir", "strings_file", "manifest"):
        if key not in source_raw:
            raise ValueError(f"Missing required source config field: '{key}'")

    return Config(
        app=AppConfig(
            name=app_raw["name"],
            package=app_raw["package"],
            platform=app_raw["platform"],
        ),
        source=SourceConfig(
            root=source_raw["root"],
            layouts_dir=source_raw["layouts_dir"],
            strings_file=source_raw["strings_file"],
            manifest=source_raw["manifest"],
        ),
        llm=LLMConfig(
            provider=raw.get("llm", {}).get("provider", "anthropic"),
            model=raw.get("llm", {}).get("model", "claude-sonnet-4-20250514"),
        ),
    )
