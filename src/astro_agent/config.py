from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class Settings:
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    timeout_sec: int
    default_use_llm: bool
    default_targets: list[str]
    default_targets_file: str | None
    default_dotenv_path: str | None
    default_output_dir: str
    default_output_format: str
    default_gaia_cone_radius_arcsec: float
    default_mast_radius_deg: float
    default_simbad_reference_time_range: str
    default_literature_min_obj_freq: int


DEFAULT_DOTENV = Path(".env")
DEFAULT_CONFIG_YAML = Path("config.yaml")


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists() or config_path.is_dir():
        return {}
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read config.yaml. "
            "Install dependencies with: pip install -r requirements.txt")

    content = config_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(content)
    return loaded if isinstance(loaded, dict) else {}


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_targets(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _yaml_get(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def load_settings(
    dotenv_path: str | None = None,
    config_path: str | None = None,
) -> Settings:
    yaml_path = Path(config_path) if config_path else DEFAULT_CONFIG_YAML
    yaml_config = _read_yaml_config(yaml_path)

    configured_dotenv = _yaml_get(yaml_config, "run", "dotenv_path")
    resolved_dotenv_path = dotenv_path
    if resolved_dotenv_path is None and isinstance(configured_dotenv, str):
        configured_text = configured_dotenv.strip()
        if configured_text:
            resolved_dotenv_path = configured_text

    if resolved_dotenv_path:
        load_dotenv(resolved_dotenv_path)
    else:
        load_dotenv(DEFAULT_DOTENV)

    deepseek_api_key = _yaml_get(yaml_config, "deepseek",
                                 "api_key") or os.getenv("DEEPSEEK_API_KEY")
    raw_deepseek_base_url = _yaml_get(yaml_config, "deepseek", "base_url")
    if raw_deepseek_base_url is None:
        raw_deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL")
    deepseek_base_url = _as_str(raw_deepseek_base_url,
                                "https://api.deepseek.com/v1").rstrip("/")
    raw_deepseek_model = _yaml_get(yaml_config, "deepseek", "model")
    if raw_deepseek_model is None:
        raw_deepseek_model = os.getenv("DEEPSEEK_MODEL")
    deepseek_model = _as_str(raw_deepseek_model, "deepseek-chat")

    raw_timeout_sec = _yaml_get(yaml_config, "http", "timeout_sec")
    if raw_timeout_sec is None:
        raw_timeout_sec = os.getenv("HTTP_TIMEOUT_SEC")
    timeout_sec = _as_int(raw_timeout_sec, 45)

    default_use_llm = _as_bool(
        _yaml_get(yaml_config, "run", "use_llm"),
        True,
    )
    default_targets = _as_targets(_yaml_get(yaml_config, "run", "targets"))

    default_targets_file_raw = _yaml_get(yaml_config, "run", "targets_file")
    default_targets_file = None
    if default_targets_file_raw is not None:
        text = str(default_targets_file_raw).strip()
        if text:
            default_targets_file = text

    default_dotenv_path = None
    if isinstance(configured_dotenv, str):
        text = configured_dotenv.strip()
        if text:
            default_dotenv_path = text

    default_output_dir = _as_str(
        _yaml_get(yaml_config, "output", "dir"),
        "results",
    )
    default_output_format = _as_str(
        _yaml_get(yaml_config, "output", "format"),
        "both",
    )
    if default_output_format not in {"json", "md", "txt", "both", "all"}:
        default_output_format = "both"

    default_simbad_reference_time_range = _as_str(
        _yaml_get(yaml_config, "agent", "simbad_reference_time_range"),
        "all",
    )
    if default_simbad_reference_time_range not in {"all", "recent10"}:
        default_simbad_reference_time_range = "all"

    return Settings(
        deepseek_api_key=_as_optional_str(deepseek_api_key),
        deepseek_base_url=deepseek_base_url,
        deepseek_model=deepseek_model,
        timeout_sec=timeout_sec,
        default_use_llm=default_use_llm,
        default_targets=default_targets,
        default_targets_file=default_targets_file,
        default_dotenv_path=default_dotenv_path,
        default_output_dir=default_output_dir,
        default_output_format=default_output_format,
        default_gaia_cone_radius_arcsec=_as_float(
            _yaml_get(yaml_config, "agent", "gaia_cone_radius_arcsec"),
            5.0,
        ),
        default_mast_radius_deg=_as_float(
            _yaml_get(yaml_config, "agent", "mast_radius_deg"),
            0.02,
        ),
        default_simbad_reference_time_range=default_simbad_reference_time_range,
        default_literature_min_obj_freq=_as_int(
            _yaml_get(yaml_config, "agent", "literature_min_obj_freq"),
            3,
        ),
    )
