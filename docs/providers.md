# Providers

Orca Code talks to **31 providers** out of the box — every major AI company,
plus local runtimes and any OpenAI-compatible endpoint. There is no vendor
lock, no "preferred partner", and no telemetry back to anyone.

- [Adding a key: `orca auth login`](#adding-a-key-orca-auth-login)
- [Cloud providers](#cloud-providers)
- [Aggregators](#aggregators)
- [Local runtimes](#local-runtimes)
- [Any other endpoint: `custom`](#any-other-endpoint-custom)
- [Key resolution order](#key-resolution-order)
- [Switching providers and models](#switching-providers-and-models)
- [Reasoning models](#reasoning-models)
- [Verifying a provider works](#verifying-a-provider-works)

## Adding a key: `orca auth login`

The quickest path — interactive, and the key is **validated against the
provider's live model list before it's stored**:

```bash
orca auth login          # numbered picker → paste key (hidden) → live check
```

```
  1. anthropic       key: ANTHROPIC_API_KEY
  2. deepseek        key: DEEPSEEK_API_KEY
  3. google          key: GEMINI_API_KEY
  ...
Login to which provider? [number] 3
API key for google (input hidden): ••••••••••••••••
✓ key works — 42 models available
✓ key stored for 'google' in ~/.config/orca/config.json
Make google your default provider? [Y/n]
```

Non-interactive (scripts, CI):

```bash
orca auth login groq -t gsk_... --no-default
```

Related commands:

| Command | Effect |
| --- | --- |
| `orca auth login` | add a key (validated live, hidden input) |
| `orca auth list` (`ls`) | show which providers have keys, and from where |
| `orca auth logout <provider>` | remove a stored key |

A rejected key is **never saved** — if the provider answers 401/403, `login`
exits non-zero and your config is untouched. If the provider's `/models`
endpoint can't be reached (some don't expose one), the key is stored with a
visible `? could not validate` warning rather than silently accepted.

Keys live in `~/.config/orca/config.json` (`api_keys` section). Environment
variables always win over stored keys (see
[resolution order](#key-resolution-order)).

## Cloud providers

| Provider | Key env var | Endpoint | Suggested models |
| --- | --- | --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` | api.anthropic.com | claude-sonnet-4-5, claude-opus-4-5 |
| OpenAI | `OPENAI_API_KEY` | api.openai.com/v1 | gpt-5.1, gpt-5.1-codex |
| Google | `GEMINI_API_KEY` | generativelanguage.googleapis.com/v1beta/openai | gemini-3-pro, gemini-2.5-pro |
| xAI | `XAI_API_KEY` | api.x.ai/v1 | grok-4.1, grok-4 |
| DeepSeek | `DEEPSEEK_API_KEY` | api.deepseek.com/v1 | deepseek-chat, deepseek-reasoner |
| Moonshot (Kimi) | `MOONSHOT_API_KEY` | api.moonshot.ai/v1 | kimi-k3, kimi-latest |
| Z.ai (GLM) | `ZAI_API_KEY` | api.z.ai/api/paas/v4 | glm-5.2, glm-5.2[1m] (1M ctx) |
| MiniMax | `MINIMAX_API_KEY` | api.minimax.io/v1 | MiniMax-M2.7 |
| Mistral | `MISTRAL_API_KEY` | api.mistral.ai/v1 | mistral-large-latest, codestral-latest |
| Cohere | `COHERE_API_KEY` | api.cohere.ai/compatibility/v1 | command-a-03-2025 |
| Perplexity | `PERPLEXITY_API_KEY` | api.perplexity.ai | sonar-pro, sonar |
| Dahl | `DAHL_API_KEY` | inference.dahl.global/v1 | MiniMax-M2.7, DeepSeek-V4-Flash |
| DashScope (Alibaba) | `DASHSCOPE_API_KEY` | dashscope-intl.aliyuncs.com/compatible-mode/v1 | qwen3.7-max, qwen3-coder-plus |

## Aggregators

One key, many models — useful for trying providers before committing:

| Provider | Key env var | Endpoint | Suggested models |
| --- | --- | --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` | openrouter.ai/api/v1 | anthropic/claude-sonnet-4.5, openai/gpt-5.1 |
| Groq | `GROQ_API_KEY` | api.groq.com/openai/v1 | llama-3.3-70b-versatile, openai/gpt-oss-120b |
| Together | `TOGETHER_API_KEY` | api.together.ai/v1 | Qwen/Qwen3-Coder |
| Fireworks | `FIREWORKS_API_KEY` | api.fireworks.ai/inference/v1 | kimi-k2-instruct |
| Cerebras | `CEREBRAS_API_KEY` | api.cerebras.ai/v1 | llama-3.3-70b, qwen-3-32b |
| SambaNova | `SAMBANOVA_API_KEY` | api.sambanova.ai/v1 | Meta-Llama-4-Maverick-17B |
| DeepInfra | `DEEPINFRA_API_KEY` | api.deepinfra.com/v1/openai | Llama-4-Maverick-17B |
| Novita | `NOVITA_API_KEY` | api.novita.ai/v3/openai | deepseek-v3-turbo |
| SiliconFlow | `SILICONFLOW_API_KEY` | api.siliconflow.cn/v1 | DeepSeek-V3.1 |
| Nebius | `NEBIUS_API_KEY` | api.studio.nebius.ai/v1 | deepseek-ai/deepseek-v3 |
| NVIDIA | `NVIDIA_API_KEY` | integrate.api.nvidia.com/v1 | meta/llama-4-maverick-17b |
| Hugging Face Router | `HF_TOKEN` | router.huggingface.co/v1 | Qwen3-Coder-480B |
| GitHub Models | `GITHUB_TOKEN` | models.github.ai/inference | openai/gpt-4.1 |
| OpenCode Zen | `OPENCODE_API_KEY` | opencode.ai/zen/v1 | grok-code-fast |

> **Note on GitHub Models:** GitHub has announced the retirement of the
> Models inference service; it may be unavailable or return errors during the
> retirement window. Treat it as best-effort.

## Local runtimes

No key, no account, no internet — ideal for private codebases:

| Provider | Endpoint | Notes |
| --- | --- | --- |
| Ollama | http://localhost:11434/v1 | `ollama pull qwen3-coder:30b` first |
| LM Studio | http://localhost:1234/v1 | start the local server in the app |

```bash
ollama serve &
orca config        # provider: ollama
```

## Any other endpoint: `custom`

Every OpenAI-compatible server in the wild — vLLM, llama.cpp, LiteLLM,
corporate gateways, OpenRouter-style proxies — works through `custom`:

```bash
export ORCA_BASE_URL="https://your-gateway.example.com/v1"
export ORCA_API_KEY="your-token"          # brand-neutral: one var, any provider
orca
```

Or persist it: `orca config` → provider `custom`, and set the key with
`orca auth login custom -t <token>`.

## Key resolution order

For each provider, Orca checks, in order:

1. the provider's own env var (`GROQ_API_KEY`, `DEEPSEEK_API_KEY`, …)
2. `ORCA_API_KEY` (brand-neutral generic)
3. the key stored by `orca auth login` in `config.json`
4. `ORCA_BASE_URL` overrides any provider's endpoint

So a key in the environment always beats a stored one — copy a colleague's
`.env` and you're running their provider instantly.

## Switching providers and models

Inside the REPL:

```
/models          # the provider's LIVE model list, fetched from its API
/model glm-5.2   # switch model
/provider groq   # switch provider entirely
```

`/models` hits the provider's real catalog, so what you see is what exists —
not a static list that ages badly.

## Reasoning models

Models that expose reasoning (DeepSeek-R, Kimi, GLM, gpt-oss and other
reasoning-tuned models) stream their thinking as a dim, italic `⌁ thinking` lane
while they work. Reasoning is **displayed but never stored** — it doesn't eat
your context window on later turns.

## Verifying a provider works

```bash
orca doctor                 # config + connectivity + auth diagnosis
orca -p "say hi"            # one-shot through your default provider
```
