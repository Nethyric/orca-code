"""Provider catalog: pure data, no behavior.

Endpoints are facts; behavior lives in the adapter. `kind` selects the
wire protocol; `local` providers need no key or account.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    kind: str                 # "openai" | "anthropic" | "mock"
    base_url: str
    key_env: Optional[str] = None
    local: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    context_limit: int = 128_000
    suggested: List[str] = field(default_factory=list)


SPECS: List[ProviderSpec] = [
    ProviderSpec("anthropic", "anthropic", "https://api.anthropic.com",
                 "ANTHROPIC_API_KEY", context_limit=200_000,
                 suggested=["claude-sonnet-4-5", "claude-opus-4-5",
                            "claude-haiku-4-5"]),
    ProviderSpec("openai", "openai", "https://api.openai.com/v1",
                 "OPENAI_API_KEY", suggested=["gpt-5.1", "gpt-5.1-codex",
                                              "gpt-5.1-mini"]),
    ProviderSpec("openrouter", "openai", "https://openrouter.ai/api/v1",
                 "OPENROUTER_API_KEY", context_limit=200_000,
                 headers={"HTTP-Referer": "https://github.com/Nethyric/orca-code",
                          "X-Title": "Orca Code"},
                 suggested=["anthropic/claude-sonnet-4.5", "openai/gpt-5.1",
                            "deepseek/deepseek-chat", "qwen/qwen3-coder"]),
    ProviderSpec("google", "openai",
                 "https://generativelanguage.googleapis.com/v1beta/openai",
                 "GEMINI_API_KEY", context_limit=1_000_000,
                 suggested=["gemini-3-pro", "gemini-2.5-pro",
                            "gemini-2.5-flash"]),
    ProviderSpec("xai", "openai", "https://api.x.ai/v1", "XAI_API_KEY",
                 suggested=["grok-4.1", "grok-4"]),
    ProviderSpec("groq", "openai", "https://api.groq.com/openai/v1",
                 "GROQ_API_KEY", suggested=["llama-3.3-70b-versatile",
                                            "openai/gpt-oss-120b"]),
    ProviderSpec("deepseek", "openai", "https://api.deepseek.com/v1",
                 "DEEPSEEK_API_KEY", suggested=["deepseek-chat",
                                                "deepseek-reasoner"]),
    ProviderSpec("mistral", "openai", "https://api.mistral.ai/v1",
                 "MISTRAL_API_KEY", suggested=["mistral-large-latest",
                                               "codestral-latest"]),
    ProviderSpec("together", "openai", "https://api.together.ai/v1",
                 "TOGETHER_API_KEY", suggested=["Qwen/Qwen3-Coder"]),
    ProviderSpec("moonshot", "openai", "https://api.moonshot.ai/v1",
                 "MOONSHOT_API_KEY", suggested=["kimi-k3", "kimi-latest"]),
    ProviderSpec("zai", "openai", "https://api.z.ai/api/paas/v4",
                 "ZAI_API_KEY", suggested=["glm-5.2", "glm-5.2[1m]"]),
    ProviderSpec("minimax", "openai", "https://api.minimax.io/v1",
                 "MINIMAX_API_KEY", suggested=["MiniMax-M2.7"]),
    ProviderSpec("dashscope", "openai",
                 "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                 "DASHSCOPE_API_KEY", suggested=["qwen3.7-max",
                                                 "qwen3-coder-plus"]),
    ProviderSpec("cerebras", "openai", "https://api.cerebras.ai/v1",
                 "CEREBRAS_API_KEY", suggested=["llama-3.3-70b",
                                                "qwen-3-32b"]),
    ProviderSpec("fireworks", "openai", "https://api.fireworks.ai/inference/v1",
                 "FIREWORKS_API_KEY"),
    ProviderSpec("perplexity", "openai", "https://api.perplexity.ai",
                 "PERPLEXITY_API_KEY", suggested=["sonar-pro", "sonar"]),
    ProviderSpec("cohere", "openai", "https://api.cohere.ai/compatibility/v1",
                 "COHERE_API_KEY", suggested=["command-a-03-2025"]),
    ProviderSpec("deepinfra", "openai", "https://api.deepinfra.com/v1/openai",
                 "DEEPINFRA_API_KEY"),
    ProviderSpec("sambanova", "openai", "https://api.sambanova.ai/v1",
                 "SAMBANOVA_API_KEY"),
    ProviderSpec("nebius", "openai", "https://api.studio.nebius.ai/v1",
                 "NEBIUS_API_KEY"),
    ProviderSpec("novita", "openai", "https://api.novita.ai/v3/openai",
                 "NOVITA_API_KEY"),
    ProviderSpec("siliconflow", "openai", "https://api.siliconflow.cn/v1",
                 "SILICONFLOW_API_KEY"),
    ProviderSpec("nvidia", "openai", "https://integrate.api.nvidia.com/v1",
                 "NVIDIA_API_KEY"),
    ProviderSpec("huggingface", "openai", "https://router.huggingface.co/v1",
                 "HF_TOKEN"),
    ProviderSpec("github", "openai", "https://models.github.ai/inference",
                 "GITHUB_TOKEN"),
    ProviderSpec("opencode", "openai", "https://opencode.ai/zen/v1",
                 "OPENCODE_API_KEY"),
    ProviderSpec("dahl", "openai", "https://inference.dahl.global/v1",
                 "DAHL_API_KEY", context_limit=200_000,
                 suggested=["MiniMaxAI/MiniMax-M2.7",
                            "deepseek-ai/DeepSeek-V4-Flash-0731",
                            "zai-org/GLM-5.3-Flash"]),
    ProviderSpec("ollama", "openai", "http://localhost:11434/v1",
                 None, local=True, context_limit=128_000,
                 suggested=["qwen3-coder:30b", "qwen2.5-coder:7b", "llama3.3"]),
    ProviderSpec("lmstudio", "openai", "http://localhost:1234/v1",
                 None, local=True),
    ProviderSpec("mock", "mock", "", None),
    ProviderSpec("custom", "openai", "", "ORCA_API_KEY"),
]

CATALOG: Dict[str, ProviderSpec] = {s.name: s for s in SPECS}

MODEL_ALIASES: Dict[str, str] = {
    "kimi": "moonshotai/Kimi-K2.6",
    "kimi-k2.6": "moonshotai/Kimi-K2.6",
    "minimax": "MiniMaxAI/MiniMax-M2.7",
    "m2.7": "MiniMaxAI/MiniMax-M2.7",
    "deepseek-flash": "deepseek-ai/DeepSeek-V4-Flash-0731",
    "glm": "zai-org/GLM-5.3-Flash",
    "glm-flash": "zai-org/GLM-5.3-Flash",
}


def expand_alias(model: str) -> str:
    return MODEL_ALIASES.get((model or "").strip().lower(), model)


def default_model(provider: str) -> str:
    spec = CATALOG.get(provider)
    if spec and spec.suggested:
        return spec.suggested[0]
    return ""
