"""Administrator-only configuration; chat content never changes these values."""
import ipaddress
import json
import os
from pathlib import Path
from typing import FrozenSet, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, root_validator, validator
from dotenv import dotenv_values


PRESET_ID = "erika-agent-chat-v1"
LEARNER_PRESET_ID = "erika-agent-chat-learner-v1"
GUARD_MODULE = "erika-agent-chat-dsh/guard.mjs"


class Config(BaseModel):
    agent_chat_enabled: bool = False
    agent_chat_groups: FrozenSet[int] = frozenset()
    agent_chat_private_users: FrozenSet[int] = frozenset()
    agent_chat_dsh_url: str = "http://127.0.0.1:3080"
    agent_chat_dsh_token: SecretStr = SecretStr("")
    agent_chat_dsh_cookie: SecretStr = SecretStr("")
    agent_chat_state_path: Path = Path("data/agent_chat/state.sqlite3")
    agent_chat_memory_enabled: bool = False
    agent_chat_memory_immediate_enabled: bool = True
    agent_chat_memory_background_enabled: bool = False
    agent_chat_memory_batch_threshold: int = Field(30, ge=1, le=200)
    agent_chat_memory_interval: int = Field(600, ge=60, le=86400)
    agent_chat_memory_min_interval: int = Field(300, ge=30, le=86400)
    agent_chat_slang_enabled: bool = False
    agent_chat_knowledge_token: SecretStr = SecretStr("")
    agent_chat_learning_max_per_hour: int = Field(12, ge=1, le=60)
    agent_chat_cooldown: float = Field(2, ge=0, le=3600)
    agent_chat_debounce: float = Field(1, ge=0, le=10)
    agent_chat_batch_limit: int = Field(8, ge=1, le=20)
    agent_chat_notice_after: float = Field(0, ge=0, le=120)
    agent_chat_timeout: float = Field(90, ge=5, le=300)
    agent_chat_queue_timeout: float = Field(600, ge=5, le=3600)
    agent_chat_max_reply_chars: int = Field(600, ge=20, le=4000)
    agent_chat_context_messages: int = Field(20, ge=1, le=80)
    agent_chat_max_message_chars: int = Field(1500, ge=100, le=8000)
    agent_chat_max_calls_per_hour: int = Field(60, ge=1, le=300)
    agent_chat_ambient_probability: float = Field(0, ge=0, le=0.2)
    agent_chat_max_concurrent: int = Field(2, ge=1, le=8)
    agent_chat_max_pending: int = Field(16, ge=1, le=64)
    agent_chat_takeover_mentions: bool = True
    agent_chat_forward_persona: bool = True
    agent_chat_reply_enabled: bool = True
    agent_chat_faces_enabled: bool = True
    agent_chat_mentions_enabled: bool = True
    agent_chat_reactions_enabled: bool = True
    agent_chat_poke_reply_enabled: bool = True
    agent_chat_poke_reply_probability: float = Field(0.3, ge=0, le=1)
    agent_chat_poke_reply_cooldown: float = Field(30, ge=0, le=3600)
    agent_chat_poke_enabled: bool = True
    agent_chat_reaction_cooldown: float = Field(30, ge=5, le=3600)
    agent_chat_poke_cooldown: float = Field(300, ge=30, le=86400)
    agent_chat_forwards_enabled: bool = True
    agent_chat_provider: str = ""
    agent_chat_model: str = ""
    agent_chat_search_enabled: bool = False
    agent_chat_search_ambient: bool = False
    agent_chat_search_proactive: bool = False
    agent_chat_search_max_per_hour: int = Field(6, ge=1, le=30)
    agent_chat_images_enabled: bool = False
    agent_chat_image_count: int = Field(2, ge=1, le=4)
    agent_chat_image_cache_ttl: int = Field(600, ge=0, le=3600)
    agent_chat_image_cache_bytes: int = Field(32_000_000, ge=0, le=128_000_000)
    agent_chat_image_max_bytes: int = Field(8_000_000, ge=100_000, le=20_000_000)
    agent_chat_image_max_pixels: int = Field(20_000_000, ge=100_000, le=40_000_000)
    agent_chat_image_cache_roots: Tuple[Path, ...] = ()
    agent_chat_proactive_enabled: bool = False
    agent_chat_proactive_groups: FrozenSet[int] = frozenset()
    agent_chat_proactive_idle: float = Field(900, ge=60, le=86400)
    agent_chat_proactive_daily_limit: int = Field(6, ge=1, le=24)
    agent_chat_proactive_recent_hours: int = Field(6, ge=1, le=24)
    agent_chat_observation_enabled: bool = False
    agent_chat_observation_seconds: int = Field(120, ge=30, le=900)
    agent_chat_observation_max_calls: int = Field(3, ge=1, le=10)
    agent_chat_ambient_quiet_enabled: bool = True
    agent_chat_quiet_start: int = Field(23, ge=0, le=23)
    agent_chat_quiet_end: int = Field(9, ge=0, le=23)
    agent_chat_utc_offset_hours: int = Field(8, ge=-12, le=14)

    class Config:
        extra = "ignore"

    @validator("agent_chat_groups", "agent_chat_private_users", "agent_chat_proactive_groups",
               "agent_chat_image_cache_roots", pre=True)
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

    @validator("agent_chat_groups", "agent_chat_private_users", "agent_chat_proactive_groups")
    def positive_ids(cls, values):
        if any(v <= 0 for v in values):
            raise ValueError("QQ identifiers must be positive")
        return values
    @root_validator
    def valid_enabled_config(cls, values):
        if not values.get("agent_chat_proactive_groups", frozenset()) <= values.get("agent_chat_groups", frozenset()):
            raise ValueError("Proactive groups must be inside the main group allowlist")
        if bool(values.get("agent_chat_model")) != bool(values.get("agent_chat_provider")):
            raise ValueError("Set provider and model together")
        if values.get("agent_chat_enabled"):
            if values.get('agent_chat_memory_enabled') or values.get('agent_chat_slang_enabled'):
                import re
                if not re.fullmatch(r'[a-f0-9]{64}',values.get('agent_chat_knowledge_token',SecretStr('')).get_secret_value()):
                    raise ValueError('Knowledge tools require the private loopback bridge credential')
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
