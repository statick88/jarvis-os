"""
JARVIS-OS Configuration Management
===================================
Centralized configuration using pydantic-settings with environment variable support.
All settings are validated at startup.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoicePipelineSettings(BaseSettings):
    """Voice Pipeline (STT/TTS) service configuration."""

    model_config = SettingsConfigDict(env_prefix="VOICE_", case_sensitive=False)

    # gRPC endpoint
    grpc_host: str = "voice-pipeline"
    grpc_port: int = 8080

    # REST fallback endpoint
    rest_host: str = "voice-pipeline"
    rest_port: int = 8080

    # Default models
    default_stt_model: str = "whisper-base"
    default_tts_voice: str = "es_ES-pacifico"
    default_language: str = "es"
    default_sample_rate: int = 22050

    # Timeouts
    grpc_timeout_seconds: float = 30.0
    rest_timeout_seconds: float = 30.0

    # Retry settings
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    @property
    def grpc_endpoint(self) -> str:
        return f"{self.grpc_host}:{self.grpc_port}"

    @property
    def rest_base_url(self) -> str:
        return f"http://{self.rest_host}:{self.rest_port}"


class OpenCodeAdapterSettings(BaseSettings):
    """OpenCode/Kilo Code adapter configuration."""

    model_config = SettingsConfigDict(env_prefix="OPENCODE_", case_sensitive=False)

    # Host endpoints (from Docker: host.docker.internal)
    host: str = "host.docker.internal"
    opencode_port: int = 8081
    kilo_port: int = 8082

    # Transport preference
    transport: Literal["websocket", "http"] = "websocket"

    # Authentication
    token: str = Field(default="changeme-secure-token", description="Shared secret for X-Jarvis-Token header")

    # Connection settings
    websocket_path: str = "/jarvis/adapter"
    http_path: str = "/jarvis/adapter"
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 60.0

    # Heartbeat
    heartbeat_interval_seconds: int = 30
    max_missed_heartbeats: int = 3

    # Reconnection
    auto_reconnect: bool = True
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 60.0
    reconnect_max_attempts: int = 10

    @property
    def opencode_ws_url(self) -> str:
        return f"ws://{self.host}:{self.opencode_port}{self.websocket_path}"

    @property
    def opencode_http_url(self) -> str:
        return f"http://{self.host}:{self.opencode_port}{self.http_path}"

    @property
    def kilo_ws_url(self) -> str:
        return f"ws://{self.host}:{self.kilo_port}{self.websocket_path}"

    @property
    def kilo_http_url(self) -> str:
        return f"http://{self.host}:{self.kilo_port}{self.http_path}"


class FlociClientSettings(BaseSettings):
    """Floci/LocalStack (S3/SQS) client configuration."""

    model_config = SettingsConfigDict(env_prefix="AWS_", case_sensitive=False)

    # LocalStack endpoint
    endpoint_url: str = "http://floci-localstack:4566"

    # Credentials (test/test for LocalStack)
    access_key_id: str = "test"
    secret_access_key: str = "test"
    default_region: str = "us-east-1"

    # SQS
    async_tasks_queue: str = "jarvis-async-tasks"
    sqs_max_messages: int = 10
    sqs_wait_time_seconds: int = 20
    sqs_visibility_timeout_seconds: int = 300

    # S3
    vault_backups_bucket: str = "jarvis-vault-backups"
    s3_max_retries: int = 3

    # Timeouts
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0


class VaultSettings(BaseSettings):
    """Vault/Zettelkasten configuration."""

    model_config = SettingsConfigDict(env_prefix="VAULT_", case_sensitive=False)

    # Paths (relative to container /app/vault)
    vault_root: Path = Path("/app/vault")
    wiki_dir: str = "wiki"
    raw_dir: str = "raw"
    outputs_dir: str = "outputs"
    archive_dir: str = "archive"

    # Index file
    index_file: str = ".boveda_index.json"
    master_index_file: str = "index.md"

    # Graph export formats
    graph_formats: list[str] = ["json", "graphml", "markdown"]

    # Search
    search_max_results: int = 50
    search_snippet_chars: int = 100

    # Validation
    required_frontmatter_fields: list[str] = ["id", "title", "created", "modified"]

    @property
    def wiki_path(self) -> Path:
        return self.vault_root / self.wiki_dir

    @property
    def raw_path(self) -> Path:
        return self.vault_root / self.raw_dir

    @property
    def outputs_path(self) -> Path:
        return self.vault_root / self.outputs_dir

    @property
    def archive_path(self) -> Path:
        return self.vault_root / self.archive_dir

    @property
    def index_path(self) -> Path:
        return self.vault_root / self.wiki_dir / self.index_file

    @property
    def master_index_path(self) -> Path:
        return self.vault_root / self.wiki_dir / self.master_index_file


class SkillsSettings(BaseSettings):
    """Skills loader/executor configuration."""

    model_config = SettingsConfigDict(env_prefix="SKILLS_", case_sensitive=False)

    # Paths
    skills_dir: Path = Path("/app/.skills")
    schema_path: Path = Path("/app/spec/contracts/skill_schema.yaml")

    # Execution defaults
    default_timeout_seconds: int = 30
    default_memory_limit_mb: int = 256
    default_cpu_limit_percent: int = 50
    default_sandbox: bool = True
    default_retries: int = 0
    default_retry_backoff_ms: int = 1000

    # Sandbox
    use_cgroups: bool = False  # Requires privileged container
    allowed_commands: list[str] = ["python", "bash", "sh", "node", "npm", "curl", "wget", "jq", "awk", "sed", "grep", "cat", "ls", "find"]

    # Validation
    strict_schema_validation: bool = True


class HudSettings(BaseSettings):
    """HUD (TUI + WebSocket) configuration."""

    model_config = SettingsConfigDict(env_prefix="HUD_", case_sensitive=False)

    # TUI
    tui_refresh_interval_seconds: float = 1.0
    tui_theme: str = "dark"

    # WebSocket server (for voice capture from host)
    ws_host: str = "0.0.0.0"
    ws_port: int = 8083
    ws_path: str = "/voice"
    ws_max_message_size: int = 10 * 1024 * 1024  # 10MB
    ws_ping_interval_seconds: int = 20
    ws_ping_timeout_seconds: int = 10

    # Audio
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_chunk_ms: int = 100


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(env_prefix="LOG_", case_sensitive=False)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "console"] = "json"
    include_timestamp: bool = True
    include_level: bool = True
    include_module: bool = True
    structured_fields: list[str] = ["session_id", "trace_id", "skill", "action"]


class Settings(BaseSettings):
    """Main JARVIS-OS settings aggregator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identification
    service_name: str = "jarvis-os"
    service_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "production"

    # Sub-settings (auto-loaded from env with prefixes)
    voice: VoicePipelineSettings = Field(default_factory=VoicePipelineSettings)
    opencode: OpenCodeAdapterSettings = Field(default_factory=OpenCodeAdapterSettings)
    floci: FlociClientSettings = Field(default_factory=FlociClientSettings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    hud: HudSettings = Field(default_factory=HudSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Global token (used by multiple services)
    jarvis_token: str = Field(default="changeme-secure-token", alias="JARVIS_TOKEN")

    # Paths
    base_path: Path = Path("/app")
    specs_path: Path = Path("/app/spec/contracts")

    @model_validator(mode="after")
    def validate_critical_settings(self) -> Settings:
        """Validate critical settings that would cause startup failure."""
        if self.jarvis_token == "changeme-secure-token" and self.environment == "production":
            import warnings
            warnings.warn(
                "JARVIS_TOKEN is using default insecure value in production! "
                "Set a secure token via JARVIS_TOKEN environment variable.",
                UserWarning,
                stacklevel=2,
            )
        return self

    @field_validator("base_path", "vault.vault_root", "skills.skills_dir", check_fields=False, mode="before")
    @classmethod
    def expand_paths(cls, v: str | Path) -> Path:
        if isinstance(v, str):
            return Path(v).expanduser().resolve()
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance. Use this for dependency injection."""
    return Settings()


def validate_config() -> bool:
    """Validate configuration at startup. Returns True if valid, raises on critical errors."""
    settings = get_settings()

    # Check required directories exist
    required_dirs = [
        settings.vault.vault_root,
        settings.vault.wiki_path,
        settings.vault.raw_path,
        settings.vault.outputs_path,
        settings.skills.skills_dir,
        settings.specs_path,
    ]

    for dir_path in required_dirs:
        if not dir_path.exists():
            raise RuntimeError(f"Required directory does not exist: {dir_path}")

    # Check skills directory has at least one skill
    skill_files = list(settings.skills.skills_dir.glob("*.md"))
    if not skill_files:
        raise RuntimeError(f"No skill files found in {settings.skills.skills_dir}")

    # Validate skill schema exists
    if not settings.skills.schema_path.exists():
        raise RuntimeError(f"Skill schema not found: {settings.skills.schema_path}")

    return True


# Convenience function for testing
def reset_settings_cache() -> None:
    """Reset the settings cache (useful for testing)."""
    get_settings.cache_clear()