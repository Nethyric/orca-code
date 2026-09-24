// Package agent implements the tool-use loop: prompt → stream → permissions
// → tools → results → repeat, with cost caps, undo grouping and trusted-only
// hooks.
package agent

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/Nethyric/orca/internal/config"
	"github.com/Nethyric/orca/internal/permissions"
	"github.com/Nethyric/orca/internal/provider"
	"github.com/Nethyric/orca/internal/session"
	"github.com/Nethyric/orca/internal/tools"
	"github.com/Nethyric/orca/internal/ui"
	"github.com/Nethyric/orca/internal/version"
)

const MaxTurns = 60

// costPerMTok maps model-name substrings to [input, output] USD per MTok.
// Unknown models cost 0 — and then a max_cost cap CANNOT be enforced, so we
// warn instead of silently ignoring the cap (a Python-version bug).
var costPerMTok = map[string][2]float64{
	"claude-opus": {15, 75}, "claude-sonnet": {3, 15}, "claude-haiku": {1, 5},
	"gpt-5": {1.25, 10}, "gpt-4o": {2.5, 10}, "o3": {2, 8},
	"deepseek-chat": {0.27, 1.1}, "deepseek-reasoner": {0.55, 2.19},
	"gemini-2.5-pro": {1.25, 10}, "gemini-2.5-flash": {0.3, 2.5},
	"grok-4": {3, 15}, "llama-3.3-70b": {0.59, 0.79}, "kimi-k2": {0.6, 2.5},
}

func modelCost(model string, in, out int) (float64, bool) {
	m := strings.ToLower(model)
	for needle, price := range costPerMTok {
		if strings.Contains(m, needle) {
			return float64(in)/1e6*price[0] + float64(out)/1e6*price[1], true
		}
	}
	return 0, false
}

type Agent struct {
	Provider provider.Provider
	Cfg      *config.Config
	Perms    *permissions.Permissions
	Tools    *tools.Context
	UI       *ui.UI
	Model    string
	Session  *session.Writer

	Messages   []provider.Message
	TotalIn    int
	TotalOut   int
	TotalCost  float64
	costKnown  bool
	warnedCost bool
}

func New(p provider.Provider, cfg *config.Config, perms *permissions.Permissions, tc *tools.Context, u *ui.UI, model string) *Agent {
	return &Agent{Provider: p, Cfg: cfg, Perms: perms, Tools: tc, UI: u, Model: model, costKnown: true}
}

func (a *Agent) systemPrompt() string {
	planNote := ""
	if a.Perms.Mode == permissions.Plan {
		planNote = "\n" + permissions.PlanNotice + "\n"
	}
	return fmt.Sprintf(`You are Orca Code v%s, an agentic coding assistant running in a terminal on %s.
Project root: %s

# Operating principles
- Be proactive and finish the job: explore, implement, verify. Don't stop halfway.
- Before editing a file you haven't seen this session, read the relevant part first.
- After code changes, run the project's tests/build/linter when present.
- Keep responses concise and technical; never claim actions you didn't perform via tools.

# Tools
- Paths are relative to the project root and confined to it — writes outside the root are blocked.
- edit_file old_string must match exactly and be unique; on mismatch you get a closest-match hint.
- Prefer grep/glob to locate code, then read only the relevant ranges.
- Use todo for multi-step work; keep exactly one item in_progress.

# Safety
- Never run destructive commands; suggest safer alternatives.
- Do not commit or push unless the user asks.%s`,
		version.Version, runtime.GOOS, a.Cfg.Root, planNote)
}

func toolSpecs() []provider.ToolSpec {
	regs := tools.Registry()
	out := make([]provider.ToolSpec, len(regs))
	for i, r := range regs {
		out[i] = provider.ToolSpec{Name: r.Name, Description: r.Description, InputSchema: r.Schema}
	}
	return out
}

// Run executes one user prompt to completion. Returns the final answer text.
func (a *Agent) Run(ctx context.Context, prompt string) (string, error) {
	a.Tools.Undo.BeginTurn()
	a.Session.Append("user", prompt)
	a.Messages = append(a.Messages, provider.Message{Role: "user", Content: []provider.Block{provider.TextBlock(prompt)}})

	for turn := 0; turn < MaxTurns; turn++ {
		a.maybeCompact(ctx)
		req := provider.Request{
			System: a.systemPrompt(), Messages: a.Messages,
			Tools: toolSpecs(), MaxTokens: a.Cfg.MaxTokens,
		}
		resp, err := a.Provider.Complete(ctx, req, a.UI.StreamText)
		a.UI.EndStream()
		if err != nil {
			return "", err
		}
		a.addUsage(resp.Usage)
		if err := a.checkCostCap(); err != nil {
			return "", err
		}
		if len(resp.Blocks) == 0 {
			resp.Blocks = append(resp.Blocks, provider.TextBlock("(empty response)"))
		}
		a.Messages = append(a.Messages, provider.Message{Role: "assistant", Content: resp.Blocks})

		uses := resp.ToolUses()
		if len(uses) == 0 {
			a.Session.Append("assistant", resp.Text())
			return resp.Text(), nil
		}
		results := make([]provider.Block, 0, len(uses))
		for _, use := range uses {
			results = append(results, a.execTool(use))
		}
		a.Messages = append(a.Messages, provider.Message{Role: "user", Content: results})
	}
	return "", fmt.Errorf("turn limit reached (%d) — stopping for safety", MaxTurns)
}

func (a *Agent) execTool(use provider.Block) provider.Block {
	spec, ok := tools.Lookup(use.Name)
	if !ok {
		return provider.ToolResultBlock(use.ID, fmt.Sprintf("unknown tool %q", use.Name), true)
	}
	label, detail := describe(use.Name, use.Input)
	a.UI.ToolCall(label, detail)

	dec := a.Perms.Check(a.Cfg.Root, use.Name, spec.Perm, use.Input)
	switch dec.Verdict {
	case permissions.Deny:
		a.UI.ToolResult("denied: "+dec.Reason, true)
		return provider.ToolResultBlock(use.ID, "Permission denied: "+dec.Reason, true)
	case permissions.Ask:
		switch a.UI.AskPermission(label, detail) {
		case "y":
		case "a":
			a.Perms.AllowSession(sessionRule(use.Name, use.Input))
		default:
			a.UI.ToolResult("denied by user", true)
			return provider.ToolResultBlock(use.ID, "The user declined this action. Ask before retrying or propose an alternative.", true)
		}
	}

	out, err := tools.Run(a.Tools, use.Name, use.Input)
	if err != nil {
		a.UI.ToolResult(err.Error(), true)
		return provider.ToolResultBlock(use.ID, "Error: "+err.Error(), true)
	}
	a.UI.ToolResult(firstLine(out), false)

	// trusted-only verify gate after successful writes
	if (use.Name == "write_file" || use.Name == "edit_file") && a.Cfg.VerifyCommand != "" {
		if vout, verr := a.runHook(a.Cfg.VerifyCommand, use.Input); verr != nil {
			out += "\n\n[verify_command FAILED]\n" + vout + "\nFix the problem before continuing."
		}
	}
	return provider.ToolResultBlock(use.ID, out, false)
}

// runHook executes a trusted hook/verify command with %file substitution.
func (a *Agent) runHook(command string, args map[string]any) (string, error) {
	if path, ok := args["path"].(string); ok {
		command = strings.ReplaceAll(command, "%file", path)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	shell, flag := "bash", "-c"
	if runtime.GOOS == "windows" {
		shell, flag = "cmd", "/c"
	}
	cmd := exec.CommandContext(ctx, shell, flag, command)
	cmd.Dir = a.Cfg.Root
	out, err := cmd.CombinedOutput()
	text := string(out)
	if len(text) > 4000 {
		text = text[:4000] + "…"
	}
	return text, err
}

func (a *Agent) addUsage(u provider.Usage) {
	a.TotalIn += u.In
	a.TotalOut += u.Out
	cost, known := modelCost(a.Model, u.In, u.Out)
	a.TotalCost += cost
	if !known {
		a.costKnown = false
	}
	a.UI.Meter(a.TotalIn, a.TotalOut, a.TotalCost, a.Cfg.MaxCostUSD)
}

func (a *Agent) checkCostCap() error {
	if a.Cfg.MaxCostUSD <= 0 {
		return nil
	}
	if !a.costKnown && !a.warnedCost {
		a.warnedCost = true
		a.UI.Warn(fmt.Sprintf("max_cost_usd is set but pricing for %q is unknown — the cap cannot be enforced accurately", a.Model))
	}
	if a.TotalCost >= a.Cfg.MaxCostUSD {
		return fmt.Errorf("session cost cap reached: $%.4f ≥ $%.2f", a.TotalCost, a.Cfg.MaxCostUSD)
	}
	return nil
}

func sessionRule(tool string, args map[string]any) string {
	if tool == "bash" {
		if cmd, _ := args["command"].(string); cmd != "" {
			fields := strings.Fields(cmd)
			if len(fields) > 0 {
				return fmt.Sprintf("bash(%s *)", fields[0])
			}
		}
	}
	return tool
}

func describe(tool string, args map[string]any) (string, string) {
	get := func(k string) string { v, _ := args[k].(string); return v }
	switch tool {
	case "bash":
		return "bash", get("command")
	case "write_file":
		return "write_file", fmt.Sprintf("path: %s (%d chars)", get("path"), len(get("content")))
	case "edit_file":
		o, n := get("old_string"), get("new_string")
		if len(o) > 160 {
			o = o[:160] + "…"
		}
		if len(n) > 160 {
			n = n[:160] + "…"
		}
		return "edit_file", fmt.Sprintf("path: %s\n- %s\n+ %s", get("path"), o, n)
	case "grep":
		return "grep", get("pattern")
	case "web_search":
		return "web_search", get("query")
	case "web_fetch":
		return "web_fetch", get("url")
	case "todo":
		if items, ok := args["todos"].([]any); ok {
			return "todo", fmt.Sprintf("%d items", len(items))
		}
		return "todo", ""
	default:
		p := get("path")
		if p == "" {
			p = get("pattern")
		}
		if p == "" {
			p = "."
		}
		return tool, p
	}
}

func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i]
	}
	return s
}
