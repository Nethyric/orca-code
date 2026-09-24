// Package config implements layered configuration with a TRUST BOUNDARY:
// executable settings (hooks, verify_command) coming from a project's
// .orca/settings*.json are IGNORED unless the user explicitly ran
// `orca trust` in that project. This closes the "clone a malicious repo,
// run orca, attacker's hook executes" hole in the Python version.
//
// API keys live in a separate ~/.orca/keys.json written with 0600.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type Preset struct {
	Kind    string // "anthropic" | "openai"
	BaseURL string
	KeyEnv  string
}

var Presets = map[string]Preset{
	"anthropic":  {Kind: "anthropic", BaseURL: "https://api.anthropic.com", KeyEnv: "ANTHROPIC_API_KEY"},
	"openai":     {Kind: "openai", BaseURL: "https://api.openai.com/v1", KeyEnv: "OPENAI_API_KEY"},
	"openrouter": {Kind: "openai", BaseURL: "https://openrouter.ai/api/v1", KeyEnv: "OPENROUTER_API_KEY"},
	"groq":       {Kind: "openai", BaseURL: "https://api.groq.com/openai/v1", KeyEnv: "GROQ_API_KEY"},
	"deepseek":   {Kind: "openai", BaseURL: "https://api.deepseek.com/v1", KeyEnv: "DEEPSEEK_API_KEY"},
	"mistral":    {Kind: "openai", BaseURL: "https://api.mistral.ai/v1", KeyEnv: "MISTRAL_API_KEY"},
	"together":   {Kind: "openai", BaseURL: "https://api.together.xyz/v1", KeyEnv: "TOGETHER_API_KEY"},
	"xai":        {Kind: "openai", BaseURL: "https://api.x.ai/v1", KeyEnv: "XAI_API_KEY"},
	"google":     {Kind: "openai", BaseURL: "https://generativelanguage.googleapis.com/v1beta/openai", KeyEnv: "GEMINI_API_KEY"},
	"moonshot":   {Kind: "openai", BaseURL: "https://api.moonshot.ai/v1", KeyEnv: "MOONSHOT_API_KEY"},
	"ollama":     {Kind: "openai", BaseURL: "http://localhost:11434/v1", KeyEnv: ""},
}

// DefaultModels picked when the user selects a provider without a model.
var DefaultModels = map[string]string{
	"anthropic": "claude-sonnet-4-5", "openai": "gpt-5.2", "openrouter": "anthropic/claude-sonnet-4-5",
	"groq": "llama-3.3-70b-versatile", "deepseek": "deepseek-chat", "mistral": "mistral-large-latest",
	"together": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "xai": "grok-4", "google": "gemini-2.5-pro",
	"moonshot": "kimi-k2-0905-preview", "ollama": "qwen3:14b",
}

type fileConfig struct {
	Provider      string            `json:"provider,omitempty"`
	Model         string            `json:"model,omitempty"`
	MaxTokens     int               `json:"max_tokens,omitempty"`
	MaxCostUSD    float64           `json:"max_cost_usd,omitempty"`
	CompactChars  int               `json:"compact_chars,omitempty"` // -1 disables auto-compaction
	Mode          string            `json:"mode,omitempty"`
	Allow         []string          `json:"allow,omitempty"`
	Deny          []string          `json:"deny,omitempty"`
	Hooks         map[string]string `json:"hooks,omitempty"`
	VerifyCommand string            `json:"verify_command,omitempty"`
	BaseURLs      map[string]string `json:"base_urls,omitempty"`
}

type Config struct {
	Root          string
	Provider      string
	Model         string
	MaxTokens     int
	MaxCostUSD    float64
	CompactChars  int
	Mode          string
	Allow         []string
	Deny          []string
	Hooks         map[string]string
	VerifyCommand string
	BaseURLs      map[string]string
	APIKeys       map[string]string
	Trusted       bool
	Warnings      []string
}

// Home returns the Orca config dir (override with ORCA_HOME for tests).
func Home() string {
	if v := os.Getenv("ORCA_HOME"); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ".orca-home"
	}
	return filepath.Join(home, ".orca")
}

func readJSON(path string, v any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, v)
}

// Load builds the effective config: defaults < global < project < env.
func Load(root string) (*Config, error) {
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	cfg := &Config{
		Root: abs, Mode: "default",
		Hooks: map[string]string{}, BaseURLs: map[string]string{}, APIKeys: map[string]string{},
	}
	cfg.Trusted = IsTrusted(abs)

	// global layer
	var g fileConfig
	if err := readJSON(filepath.Join(Home(), "config.json"), &g); err == nil {
		cfg.apply(&g, true)
	}
	// project layers — executable fields gated on trust
	for _, name := range []string{"settings.json", "settings.local.json"} {
		var p fileConfig
		path := filepath.Join(abs, ".orca", name)
		if err := readJSON(path, &p); err == nil {
			if !cfg.Trusted && (len(p.Hooks) > 0 || p.VerifyCommand != "") {
				cfg.Warnings = append(cfg.Warnings, fmt.Sprintf(
					"%s defines hooks/verify_command but this project is NOT trusted — ignored. Run `orca trust` to enable.", path))
				p.Hooks, p.VerifyCommand = nil, ""
			}
			cfg.apply(&p, cfg.Trusted)
		}
	}
	// keys (separate file, 0600)
	var keys map[string]string
	if err := readJSON(filepath.Join(Home(), "keys.json"), &keys); err == nil {
		cfg.APIKeys = keys
	}
	// env overrides
	if v := os.Getenv("ORCA_PROVIDER"); v != "" {
		cfg.Provider = v
	}
	if v := os.Getenv("ORCA_MODEL"); v != "" {
		cfg.Model = v
	}
	if v := os.Getenv("ORCA_MODE"); v != "" {
		cfg.Mode = v
	}
	return cfg, nil
}

func (c *Config) apply(f *fileConfig, allowExec bool) {
	if f.Provider != "" {
		c.Provider = f.Provider
	}
	if f.Model != "" {
		c.Model = f.Model
	}
	if f.MaxTokens > 0 {
		c.MaxTokens = f.MaxTokens
	}
	if f.MaxCostUSD > 0 {
		c.MaxCostUSD = f.MaxCostUSD
	}
	if f.CompactChars != 0 {
		c.CompactChars = f.CompactChars
	}
	if f.Mode != "" {
		c.Mode = f.Mode
	}
	c.Allow = append(c.Allow, f.Allow...)
	c.Deny = append(c.Deny, f.Deny...)
	for k, v := range f.BaseURLs {
		c.BaseURLs[k] = v
	}
	if allowExec {
		for k, v := range f.Hooks {
			c.Hooks[k] = v
		}
		if f.VerifyCommand != "" {
			c.VerifyCommand = f.VerifyCommand
		}
	}
}

// ProviderSettings is a fully resolved provider connection.
type ProviderSettings struct {
	Name, Kind, BaseURL, APIKey, Model string
}

// ResolveProvider picks a provider (explicit > config > first env key > ollama)
// and resolves its base URL, key and model.
func (c *Config) ResolveProvider(name string) (ProviderSettings, error) {
	if name == "" {
		name = c.Provider
	}
	if name == "" {
		for _, cand := range []string{"anthropic", "openrouter", "openai", "groq", "deepseek", "mistral", "together", "xai", "google"} {
			p := Presets[cand]
			if (p.KeyEnv != "" && os.Getenv(p.KeyEnv) != "") || c.APIKeys[cand] != "" {
				name = cand
				break
			}
		}
	}
	if name == "" {
		name = "ollama"
	}
	name = strings.ToLower(name)
	preset, ok := Presets[name]
	if !ok {
		return ProviderSettings{}, fmt.Errorf("unknown provider %q (valid: %s)", name, strings.Join(presetNames(), ", "))
	}
	base := preset.BaseURL
	if v := c.BaseURLs[name]; v != "" {
		base = v
	}
	if v := os.Getenv("ORCA_BASE_URL"); v != "" {
		base = v
	}
	key := c.APIKeys[name]
	if preset.KeyEnv != "" && os.Getenv(preset.KeyEnv) != "" {
		key = os.Getenv(preset.KeyEnv)
	}
	if key == "" {
		key = os.Getenv("ORCA_API_KEY")
	}
	model := c.Model
	if model == "" {
		model = DefaultModels[name]
	}
	return ProviderSettings{Name: name, Kind: preset.Kind, BaseURL: strings.TrimRight(base, "/"), APIKey: key, Model: model}, nil
}

func presetNames() []string {
	out := make([]string, 0, len(Presets))
	for k := range Presets {
		out = append(out, k)
	}
	return out
}

// ---- trust ----------------------------------------------------------------

func trustPath() string { return filepath.Join(Home(), "trusted.json") }

func trustedList() []string {
	var list []string
	_ = readJSON(trustPath(), &list)
	return list
}

// IsTrusted reports whether the user ran `orca trust` in root.
func IsTrusted(root string) bool {
	abs, _ := filepath.Abs(root)
	for _, p := range trustedList() {
		if p == abs {
			return true
		}
	}
	return false
}

// TrustProject records root as trusted (enables project hooks/verify).
func TrustProject(root string) error {
	abs, err := filepath.Abs(root)
	if err != nil {
		return err
	}
	list := trustedList()
	for _, p := range list {
		if p == abs {
			return nil
		}
	}
	list = append(list, abs)
	if err := os.MkdirAll(Home(), 0o700); err != nil {
		return err
	}
	data, _ := json.MarshalIndent(list, "", "  ")
	return os.WriteFile(trustPath(), data, 0o600)
}

// ---- keys -----------------------------------------------------------------

// SaveKey stores an API key in ~/.orca/keys.json with 0600 permissions.
func SaveKey(provider, key string) error {
	if _, ok := Presets[provider]; !ok {
		return fmt.Errorf("unknown provider %q", provider)
	}
	if err := os.MkdirAll(Home(), 0o700); err != nil {
		return err
	}
	keys := map[string]string{}
	_ = readJSON(filepath.Join(Home(), "keys.json"), &keys)
	keys[provider] = key
	data, _ := json.MarshalIndent(keys, "", "  ")
	return os.WriteFile(filepath.Join(Home(), "keys.json"), data, 0o600)
}
