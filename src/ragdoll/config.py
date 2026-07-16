"""Configuration with explicit project, user, environment, and CLI precedence."""

from __future__ import annotations

import os
import tomllib
from contextlib import suppress
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    openai_model_fast: str = "gpt-5.6-luna"
    openai_model_quality: str = "gpt-5.6-terra"
    ollama_model: str = "qwen3:4b"
    ollama_url: str = "http://127.0.0.1:11434"
    allow_remote_ollama: bool = False
    ollama_timeout_seconds: int = Field(default=300, ge=1, le=600)
    openalex_mailto: str | None = None
    animate: bool = True
    paper_count: int = Field(default=12, ge=3, le=50)
    dossier_paper_limit: int = Field(default=6, ge=1, le=50)
    fulltext_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    fulltext_max_pages: int = Field(default=200, ge=1, le=1000)
    fulltext_timeout_seconds: int = Field(default=45, ge=1, le=600)
    extraction_timeout_seconds: int = Field(default=45, ge=1, le=600)
    extraction_max_memory_mib: int = Field(default=768, ge=128, le=8192)
    extraction_max_cpu_seconds: int = Field(default=40, ge=1, le=600)
    extraction_max_output_bytes: int = Field(default=32 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)

    @field_validator("ollama_url")
    @classmethod
    def ollama_transport_is_safe(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama URL must be an unauthenticated HTTP(S) base URL")
        if parsed.scheme == "https":
            return value.rstrip("/")
        loopback = parsed.hostname == "localhost"
        with suppress(ValueError):
            loopback = loopback or ip_address(parsed.hostname).is_loopback
        if parsed.scheme != "http" or not loopback:
            raise ValueError("Ollama URL may use HTTP only for a loopback host")
        return value.rstrip("/")

    @model_validator(mode="after")
    def remote_ollama_requires_opt_in(self) -> Settings:
        if not self.ollama_is_local and not self.allow_remote_ollama:
            raise ValueError("remote Ollama requires explicit allow_remote_ollama opt-in")
        return self

    @property
    def ollama_is_local(self) -> bool:
        hostname = urlsplit(self.ollama_url).hostname
        if hostname == "localhost":
            return True
        if hostname is None:
            return False
        with suppress(ValueError):
            return ip_address(hostname).is_loopback
        return False


def _read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("ragdoll", data)
    return section if isinstance(section, dict) else {}


def load_settings(project: Path | None = None, **overrides: object) -> Settings:
    settings = Settings()
    user_path = user_config_path("ragdoll") / "config.toml"
    for path in [user_path]:
        values = {key: value for key, value in _read_toml(path).items() if hasattr(settings, key)}
        settings = Settings.model_validate(settings.model_dump() | values)
    if project is not None:
        project_values = _read_toml(project / ".ragdoll" / "config.toml")
        forbidden = {"ollama_url", "allow_remote_ollama"} & project_values.keys()
        if forbidden:
            raise ValueError(
                "project config cannot set security-sensitive Ollama options: "
                + ", ".join(sorted(forbidden))
            )
        values = {key: value for key, value in project_values.items() if hasattr(settings, key)}
        settings = Settings.model_validate(settings.model_dump() | values)
    env = {
        "provider": os.getenv("RAGDOLL_PROVIDER"),
        "openai_model_fast": os.getenv("RAGDOLL_OPENAI_FAST_MODEL"),
        "openai_model_quality": os.getenv("RAGDOLL_OPENAI_QUALITY_MODEL"),
        "ollama_model": os.getenv("RAGDOLL_OLLAMA_MODEL"),
        "ollama_url": os.getenv("RAGDOLL_OLLAMA_URL"),
        "allow_remote_ollama": os.getenv("RAGDOLL_ALLOW_REMOTE_OLLAMA"),
        "ollama_timeout_seconds": os.getenv("RAGDOLL_OLLAMA_TIMEOUT_SECONDS"),
        "openalex_mailto": os.getenv("RAGDOLL_OPENALEX_MAILTO"),
        "dossier_paper_limit": os.getenv("RAGDOLL_DOSSIER_PAPER_LIMIT"),
    }
    settings = Settings.model_validate(
        settings.model_dump() | {key: value for key, value in env.items() if value is not None}
    )
    clean = {key: value for key, value in overrides.items() if value is not None}
    return Settings.model_validate(settings.model_dump() | clean)
