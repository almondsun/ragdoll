"""Configuration with explicit project, user, environment, and CLI precedence."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    openai_model_fast: str = "gpt-5.6-luna"
    openai_model_quality: str = "gpt-5.6-terra"
    ollama_model: str = "qwen3:8b"
    ollama_url: str = "http://127.0.0.1:11434"
    openalex_mailto: str | None = None
    animate: bool = True
    paper_count: int = 12


def _read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("ragdoll", data)
    return section if isinstance(section, dict) else {}


def load_settings(project: Path | None = None, **overrides: object) -> Settings:
    settings = Settings()
    paths = [user_config_path("ragdoll") / "config.toml"]
    if project is not None:
        paths.append(project / ".ragdoll" / "config.toml")
    for path in paths:
        values = {key: value for key, value in _read_toml(path).items() if hasattr(settings, key)}
        settings = settings.model_copy(update=values)
    env = {
        "provider": os.getenv("RAGDOLL_PROVIDER"),
        "openai_model_fast": os.getenv("RAGDOLL_OPENAI_FAST_MODEL"),
        "openai_model_quality": os.getenv("RAGDOLL_OPENAI_QUALITY_MODEL"),
        "ollama_model": os.getenv("RAGDOLL_OLLAMA_MODEL"),
        "ollama_url": os.getenv("RAGDOLL_OLLAMA_URL"),
        "openalex_mailto": os.getenv("RAGDOLL_OPENALEX_MAILTO"),
    }
    settings = settings.model_copy(
        update={key: value for key, value in env.items() if value is not None}
    )
    clean = {key: value for key, value in overrides.items() if value is not None}
    return settings.model_copy(update=clean)
