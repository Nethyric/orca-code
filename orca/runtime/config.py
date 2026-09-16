"""Layered, versioned configuration.

defaults  <  ~/.config/orca/config.json  <  <root>/.orca/config.json  <  env
Keys never move between versions without a migration entry — config that
survives an upgrade is a feature.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigError(Exception):
    pass


CONFIG_VERSION = 2

DEFAULTS: Dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "provider": None,
    "model": None,
    "fast_model": None,
    "permissions": {"mode": "default"},
    "hooks": {},
    "output_style": None,
    "max_turns": 40,
    "max_task_turns": 12,
    "max_cost_usd": None,
    "max_session_tokens": None,
    "bash_timeout": 120,
    "auto_compact": True,
    "compact_threshold": 0.82,
    "keep_recent": 0.30,
    "base_urls": {},
    "api_keys": {},
}

ENV_MAP = {
    "ORCA_PROVIDER": "provider",
    "ORCA_MODEL": "model",
    "ORCA_MAX_COST": "max_cost_usd",
    "ORCA_OUTPUT_STYLE": "output_style",
}


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, root: Optional[Path] = None,
                 home: Optional[Path] = None):
        self.root = Path(root).resolve() if root else Path.cwd().resolve()
        home_dir = home or Path(os.environ.get("ORCA_HOME")
                                or Path.home() / ".config" / "orca")
        self.user_file = home_dir / "config.json"
        self.project_file = self.root / ".orca" / "config.json"
        data = dict(DEFAULTS)
        for path in (self.user_file, self.project_file):
            if path.is_file():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except ValueError as exc:
                    raise ConfigError(f"bad config {path}: {exc}")
                data = _deep_merge(data, loaded)
        self._data = data
        self._apply_env()

    # ------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save_user(self) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_text(
            json.dumps(self._data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    # ------------------------------------------------------------- env
    def _apply_env(self) -> None:
        for env_key, cfg_key in ENV_MAP.items():
            if os.environ.get(env_key):
                self.set(cfg_key, os.environ[env_key])

    # ------------------------------------------------------------- provider
    def detect_provider(self) -> str:
        explicit = self.get("provider")
        if explicit:
            return str(explicit)
        for name, key in (self.get("api_keys") or {}).items():
            if name in ("ollama", "lmstudio", "mock"):
                continue
            if key:
                return name
        for name in ("deepseek", "openai", "anthropic"):
            env = self._key_env(name)
            if env and os.environ.get(env):
                return name
        return "ollama"

    def _key_env(self, provider: str) -> Optional[str]:
        from ..providers.catalog import CATALOG
        spec = CATALOG.get(provider)
        return spec.key_env if spec else None

    def api_key(self, provider: str) -> str:
        """env beats stored keys; ORCA_API_KEY is the brand-neutral override."""
        for env in (self._key_env(provider), "ORCA_API_KEY"):
            if env and os.environ.get(env):
                return os.environ[env]
        return str((self.get("api_keys") or {}).get(provider) or "")

    def permission_mode(self) -> str:
        return str((self.get("permissions") or {}).get("mode") or "default")
