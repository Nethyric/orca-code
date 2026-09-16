"""Configuration, provider presets and the model catalog for Orca Code."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "0.0.2"
APP = "orca-code"


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def orca_home() -> Path:
    override = os.environ.get("ORCA_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".orca"


def config_path() -> Path:
    return orca_home() / "config.json"


def sessions_dir() -> Path:
    return orca_home() / "sessions"


def global_memory_path() -> Path:
    return orca_home() / "ORCA.md"


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------
# Provider presets
# --------------------------------------------------------------------------

PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "headers": {"HTTP-Referer": "https://github.com/orca-code/orca", "X-Title": "Orca Code"},
    },
    "google": {
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
    },
    "xai": {
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
    },
    "moonshot": {
        "kind": "openai",
        "base_url": "https://api.moonshot.ai/v1",
        "key_env": "MOONSHOT_API_KEY",
    },
    "zai": {
        "kind": "openai",
        "base_url": "https://api.z.ai/api/paas/v4",
        "key_env": "ZAI_API_KEY",
    },
    "minimax": {
        "kind": "openai",
        "base_url": "https://api.minimax.io/v1",
        "key_env": "MINIMAX_API_KEY",
    },
    "dashscope": {
        "kind": "openai",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "cerebras": {
        "kind": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "key_env": "CEREBRAS_API_KEY",
    },
    "fireworks": {
        "kind": "openai",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "key_env": "FIREWORKS_API_KEY",
    },
    "perplexity": {
        "kind": "openai",
        "base_url": "https://api.perplexity.ai",
        "key_env": "PERPLEXITY_API_KEY",
    },
    "cohere": {
        "kind": "openai",
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "key_env": "COHERE_API_KEY",
    },
    "deepinfra": {
        "kind": "openai",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "key_env": "DEEPINFRA_API_KEY",
    },
    "sambanova": {
        "kind": "openai",
        "base_url": "https://api.sambanova.ai/v1",
        "key_env": "SAMBANOVA_API_KEY",
    },
    "nebius": {
        "kind": "openai",
        "base_url": "https://api.studio.nebius.ai/v1",
        "key_env": "NEBIUS_API_KEY",
    },
    "novita": {
        "kind": "openai",
        "base_url": "https://api.novita.ai/v3/openai",
        "key_env": "NOVITA_API_KEY",
    },
    "siliconflow": {
        "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "key_env": "SILICONFLOW_API_KEY",
    },
    "nvidia": {
        "kind": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
    },
    "huggingface": {
        "kind": "openai",
        "base_url": "https://router.huggingface.co/v1",
        "key_env": "HF_TOKEN",
    },
    "github": {
        "kind": "openai",
        "base_url": "https://models.github.ai/inference",
        "key_env": "GITHUB_TOKEN",
    },
    "opencode": {
        "kind": "openai",
        "base_url": "https://opencode.ai/zen/v1",
        "key_env": "OPENCODE_API_KEY",
    },
    "dahl": {
        "kind": "openai",
        "base_url": "https://inference.dahl.global/v1",
        "key_env": "DAHL_API_KEY",
    },
    "groq": {
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
    },
    "deepseek": {
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "mistral": {
        "kind": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
    },
    "together": {
        "kind": "openai",
        "base_url": "https://api.together.ai/v1",
        "key_env": "TOGETHER_API_KEY",
    },
    "ollama": {
        "kind": "openai",
        "base_url": "http://localhost:11434/v1",
        "key_env": None,
    },
    "lmstudio": {
        "kind": "openai",
        "base_url": "http://localhost:1234/v1",
        "key_env": None,
    },
    "mock": {
        "kind": "mock",
        "base_url": "",
        "key_env": None,
        "headers": {},
    },
    "custom": {
        "kind": "openai",
        "base_url": "",
        "key_env": "ORCA_API_KEY",
    },
}

# Models suggested by `orca config` / /models for each provider.
SUGGESTED_MODELS: Dict[str, List[str]] = {
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"],
    "openai": ["gpt-5.1", "gpt-5.1-codex", "gpt-5.1-mini"],
    "openrouter": [
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-5.1",
        "deepseek/deepseek-chat",
        "qwen/qwen3-coder",
        "meta-llama/llama-4-maverick",
    ],
    "groq": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "mistral": ["mistral-large-latest", "codestral-latest"],
    "together": ["Qwen/Qwen3-Coder"],
    "ollama": ["qwen3-coder:30b", "qwen2.5-coder:7b", "llama3.3"],
    "lmstudio": [],
    "google": ["gemini-3-pro", "gemini-2.5-pro", "gemini-2.5-flash"],
    "xai": ["grok-4.1", "grok-4"],
    "moonshot": ["kimi-k3", "kimi-latest"],
    "zai": ["glm-5.2", "glm-5.2[1m]"],
    "minimax": ["MiniMax-M2.7"],
    "dashscope": ["qwen3.7-max", "qwen3-coder-plus"],
    "cerebras": ["llama-3.3-70b", "qwen-3-32b", "gpt-oss-120b"],
    "fireworks": ["accounts/fireworks/models/kimi-k2-instruct"],
    "perplexity": ["sonar-pro", "sonar", "sonar-reasoning-pro"],
    "cohere": ["command-a-03-2025"],
    "deepinfra": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"],
    "sambanova": ["Meta-Llama-4-Maverick-17B-128E-Instruct"],
    "nebius": ["deepseek-ai/deepseek-v3"],
    "novita": ["deepseek/deepseek-v3-turbo"],
    "siliconflow": ["deepseek-ai/DeepSeek-V3.1"],
    "nvidia": ["meta/llama-4-maverick-17b-128e-instruct"],
    "huggingface": ["Qwen/Qwen3-Coder-480B-A35B-Instruct"],
    "github": ["openai/gpt-4.1"],
    "opencode": ["grok-code-fast"],
    "dahl": [
        "MiniMaxAI/MiniMax-M2.7",
        "deepseek-ai/DeepSeek-V4-Flash-0731",
        "zai-org/GLM-5.3-Flash",
    ],
    "mock": ["mock-1"],
    "custom": [],
}

# Friendly short names for long model ids (applied by /model and orca -m).
MODEL_ALIASES = {
    "kimi": "moonshotai/Kimi-K2.6",
    "kimi-k2.6": "moonshotai/Kimi-K2.6",
    "minimax": "MiniMaxAI/MiniMax-M2.7",
    "minimax-m2.7": "MiniMaxAI/MiniMax-M2.7",
    "m2.7": "MiniMaxAI/MiniMax-M2.7",
    "deepseek-flash": "deepseek-ai/DeepSeek-V4-Flash-0731",
    "glm": "zai-org/GLM-5.3-Flash",
    "glm-flash": "zai-org/GLM-5.3-Flash",
    "glm-5.3": "zai-org/GLM-5.3-Flash",
}


def expand_model_alias(name: str) -> str:
    return MODEL_ALIASES.get((name or "").strip().lower(), name)

# --------------------------------------------------------------------------
# Model catalog: context windows and approximate USD prices per 1M tokens.
# Approximate & overridable — `orca /cost` marks estimates with ~.
# --------------------------------------------------------------------------

MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "claude-opus-4-5": {"context": 200_000, "in": 5.00, "out": 25.00},
    "claude-sonnet-4-5": {"context": 200_000, "in": 3.00, "out": 15.00},
    "claude-haiku-4-5": {"context": 200_000, "in": 1.00, "out": 5.00},
    "gpt-5.1": {"context": 400_000, "in": 1.25, "out": 10.00},
    "gpt-5.1-codex": {"context": 400_000, "in": 1.25, "out": 10.00},
    "gpt-5.1-codex-max": {"context": 400_000, "in": 1.25, "out": 10.00},
    "gpt-5.1-mini": {"context": 400_000, "in": 0.25, "out": 2.00},
    "gpt-5": {"context": 400_000, "in": 1.25, "out": 10.00},
    "gpt-5-mini": {"context": 400_000, "in": 0.25, "out": 2.00},
    "deepseek-chat": {"context": 131_072, "in": 0.27, "out": 1.10},
    "deepseek-reasoner": {"context": 131_072, "in": 0.55, "out": 2.18},
    "llama-3.3-70b-versatile": {"context": 131_072, "in": 0.59, "out": 0.79},
    "openai/gpt-oss-120b": {"context": 131_072, "in": 0.10, "out": 0.50},
    "openai/gpt-oss-20b": {"context": 131_072, "in": 0.04, "out": 0.15},
    "mistral-large-latest": {"context": 131_072, "in": 2.00, "out": 6.00},
    "gemini-3-pro": {"context": 1_000_000, "in": 2.00, "out": 12.00},
    "gemini-3-flash": {"context": 1_000_000, "in": 0.15, "out": 0.60},
}

_CONTEXT_HEURISTICS = [
    ("claude", 200_000),
    ("gpt-5", 400_000),
    ("gpt-4", 128_000),
    ("gemini", 1_000_000),
    ("deepseek", 131_072),
    ("llama", 131_072),
    ("qwen", 131_072),
    ("codestral", 262_144),
]


def model_info(model: str) -> Dict[str, Any]:
    """Look up context window + pricing. Falls back to heuristics/defaults."""
    key = (model or "").lower()
    for candidate in (key, key.split("/")[-1]):
        if candidate in MODEL_CATALOG:
            return dict(MODEL_CATALOG[candidate])
    context = 128_000
    for needle, ctx in _CONTEXT_HEURISTICS:
        if needle in key:
            context = ctx
            break
    return {"context": context, "in": None, "out": None}


# --------------------------------------------------------------------------
# Config object
# --------------------------------------------------------------------------

DEFAULTS: Dict[str, Any] = {
    "provider": None,
    "model": None,
    "fast_model": None,          # cheaper model for compaction summaries (optional)
    "fallbacks": [],             # e.g. ["groq:llama-3.3-70b-versatile", "deepseek-chat"]
                                 # tried in order when the active provider fails
    "verify_command": None,      # e.g. "python3 -m pytest -x -q" — a deterministic
                                 # gate: runs after every file edit; failure is fed
                                 # straight back to the model
    "max_session_tokens": None,  # hard token budget for one session (runaway guard)
    "max_tokens": None,          # provider default when None
    "auto_compact": True,
    "compact_threshold": 0.82,   # fraction of context window that triggers compaction
    "keep_recent": 0.30,         # fraction of recent messages kept intact
    "max_cost_usd": None,        # hard session cost cap (safety stop)
    "prompt_caching": True,      # Anthropic cache_control on system+tools
    "permissions": {"mode": "default", "allow": [], "deny": []},
    "hooks": {},                  # e.g. {"after_edit": "black %file", "before_bash": "make lint %command"}
    "output_style": None,         # "concise" | "verbose" | "code" | None
    "max_task_turns": 12,         # turn budget per subagent (task tool)
    "api_keys": {},
    "base_urls": {},
}


class Config:
    """Layered config: defaults < ~/.orca/config.json < project .orca/*.json < env."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root).resolve() if root else Path.cwd().resolve()
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    # -- loading ------------------------------------------------------------

    def load(self) -> None:
        layers: List[Path] = [config_path()]
        for rel in (".orca/settings.json", ".orca/settings.local.json"):
            p = self.root / rel
            if p.is_file():
                layers.append(p)
        for path in layers:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ConfigError(f"Cannot parse config {path}: {exc}") from exc
            for key, value in data.items():
                if key == "permissions" and isinstance(value, dict):
                    merged = dict(self._data.get("permissions") or {})
                    for sub, subval in value.items():
                        if isinstance(subval, list) and isinstance(merged.get(sub), list):
                            merged[sub] = merged[sub] + [x for x in subval if x not in merged[sub]]
                        else:
                            merged[sub] = subval
                    self._data["permissions"] = merged
                else:
                    self._data[key] = value
        self._apply_env()

    def _apply_env(self) -> None:
        env = os.environ
        if env.get("ORCA_PROVIDER"):
            self._data["provider"] = env["ORCA_PROVIDER"]
        if env.get("ORCA_MODEL"):
            self._data["model"] = env["ORCA_MODEL"]
        if env.get("ORCA_FAST_MODEL"):
            self._data["fast_model"] = env["ORCA_FAST_MODEL"]
        if env.get("ORCA_MAX_COST"):
            try:
                self._data["max_cost_usd"] = float(env["ORCA_MAX_COST"])
            except ValueError:
                pass

    # -- accessors ----------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["_data"][name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in self._data.items() if v is not None or k == "provider"}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # -- provider resolution -------------------------------------------------

    def detect_provider(self) -> str:
        """Best provider given config + env keys."""
        if self._data.get("provider"):
            return self._data["provider"]
        for name in ("anthropic", "openrouter", "openai", "groq", "deepseek", "mistral", "together"):
            preset = PROVIDER_PRESETS[name]
            env_var = preset.get("key_env")
            if env_var and os.environ.get(env_var):
                return name
            if self._data.get("api_keys", {}).get(name):
                return name
        return "ollama"

    def resolve_provider(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Return a fully-resolved provider connection dict."""
        name = (name or self.detect_provider()).lower()
        if name not in PROVIDER_PRESETS:
            raise ConfigError(
                f"Unknown provider '{name}'. Valid: {', '.join(sorted(PROVIDER_PRESETS))}"
            )
        preset = PROVIDER_PRESETS[name]
        base_url = (
            os.environ.get("ORCA_BASE_URL")
            or self._data.get("base_urls", {}).get(name)
            or preset["base_url"]
        )
        if not base_url and name != "mock":
            raise ConfigError(
                f"Provider '{name}' needs a base URL. Run `orca config` or set ORCA_BASE_URL."
            )
        api_key = self._data.get("api_keys", {}).get(name)
        env_var = preset.get("key_env")
        if env_var and os.environ.get(env_var):
            api_key = os.environ[env_var] or api_key
        if not api_key and os.environ.get("ORCA_API_KEY"):
            # brand-neutral fallback: one key, any provider
            api_key = os.environ["ORCA_API_KEY"]
        headers = dict(preset.get("headers") or {})
        return {
            "name": name,
            "kind": preset["kind"],
            "base_url": (base_url or "").rstrip("/"),
            "api_key": api_key,
            "headers": headers,
        }

    # -- project settings ----------------------------------------------------

    def project_settings_path(self, local: bool = False) -> Path:
        fname = "settings.local.json" if local else "settings.json"
        return self.root / ".orca" / fname

    def add_permission_rule(self, rule: str, allow: bool = True, local: bool = True) -> None:
        """Persist an allow/deny rule into the project settings file."""
        path = self.project_settings_path(local=local)
        data: Dict[str, Any] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
        perms = data.setdefault("permissions", {})
        bucket = perms.setdefault("allow" if allow else "deny", [])
        if rule not in bucket:
            bucket.append(rule)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # keep runtime view in sync
        runtime = self._data.setdefault("permissions", {}).setdefault("allow" if allow else "deny", [])
        if rule not in runtime:
            runtime.append(rule)
