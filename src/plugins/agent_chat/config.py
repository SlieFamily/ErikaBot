"""Administrator-only configuration; chat content never changes these values."""
import ipaddress
import json
import os
from pathlib import Path
from typing import FrozenSet
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, root_validator, validator
from dotenv import dotenv_values


PRESET_ID = "erika-agent-chat-v1"
GUARD_MODULE = "erika-agent-chat-dsh/guard.mjs"


class Config(BaseModel):
    agent_chat_enabled: bool = False
    agent_chat_groups: FrozenSet[int] = frozenset()
    agent_chat_private_users: FrozenSet[int] = frozenset()
    agent_chat_dsh_url: str = "http://127.0.0.1:3080"
    agent_chat_dsh_token: SecretStr = SecretStr("")
    agent_chat_dsh_cookie: SecretStr = SecretStr("")
    agent_chat_state_path: Path = Path("data/agent_chat/state.sqlite3")
    agent_chat_cooldown: float = Field(8, ge=0, le=3600)
    agent_chat_debounce: float = Field(2, ge=0, le=10)
    agent_chat_timeout: float = Field(90, ge=5, le=300)
    agent_chat_max_reply_chars: int = Field(600, ge=20, le=4000)
    agent_chat_context_messages: int = Field(20, ge=1, le=80)
    agent_chat_max_message_chars: int = Field(1500, ge=100, le=8000)
    agent_chat_max_calls_per_hour: int = Field(30, ge=1, le=300)
    agent_chat_ambient_probability: float = Field(0, ge=0, le=0.2)
    agent_chat_max_concurrent: int = Field(2, ge=1, le=8)
    agent_chat_max_pending: int = Field(16, ge=1, le=64)
    agent_chat_takeover_mentions: bool = True
    agent_chat_provider: str = ""
    agent_chat_model: str = ""

    class Config:
        extra = "ignore"

    @validator("agent_chat_groups", "agent_chat_private_users", pre=True)
    def parse_ids(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    @validator("agent_chat_dsh_url")
    def loopback_only(cls, value):
        u = urlsplit(value)
        # Use an SSH tunnel for remote DSH. Never forward privileged cookies to DNS names.
        if u.scheme not in {"http", "https"} or u.username or u.password or u.query or u.fragment:
            raise ValueError("DSH URL must be a loopback HTTP(S) origin without credentials")
        try:
            local = ipaddress.ip_address(u.hostname or "").is_loopback
            _ = u.port
        except ValueError:
            local = False
        if not local or u.path not in {"", "/"}:
            raise ValueError("Use http://127.0.0.1:3080 (SSH tunnel for a remote server)")
        return value.rstrip("/")

    @validator("agent_chat_groups", "agent_chat_private_users")
    def positive_ids(cls, values):
        if any(v <= 0 for v in values):
            raise ValueError("QQ identifiers must be positive")
        return values
    @root_validator
    def valid_enabled_config(cls, values):
        if bool(values.get("agent_chat_model")) != bool(values.get("agent_chat_provider")):
            raise ValueError("Set provider and model together")
        if values.get("agent_chat_enabled"):
            if not (values.get("agent_chat_groups") or values.get("agent_chat_private_users")):
                raise ValueError("Enabled agent_chat requires an explicit allowlist")
            token = values.get("agent_chat_dsh_token", SecretStr("")).get_secret_value()
            cookie = values.get("agent_chat_dsh_cookie", SecretStr("")).get_secret_value()
            if not (token or cookie):
                raise ValueError("Set DSH token or cookie outside Git")
            if any(c in token + cookie for c in "\r\n"):
                raise ValueError("Invalid credential characters")
        return values


def load_config(driver_values=None, private_file=".env.agent_chat", environ=None):
    """Process environment > private file > NoneBot config > defaults.

    Do not export private values to os.environ or the global NoneBot config.
    Disable dotenv interpolation so secrets containing ${...} remain literal.
    """
    values = {}
    sources = (driver_values or {}, dotenv_values(private_file, interpolate=False),
               os.environ if environ is None else environ)
    for source in sources:
        values.update({key.lower(): value for key, value in source.items()
                       if key.lower().startswith("agent_chat_") and value is not None})
    return Config.parse_obj(values)
