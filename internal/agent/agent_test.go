package agent

import (
	"bufio"
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Nethyric/orca/internal/config"
	"github.com/Nethyric/orca/internal/permissions"
	"github.com/Nethyric/orca/internal/provider"
	"github.com/Nethyric/orca/internal/tools"
	"github.com/Nethyric/orca/internal/ui"
)

// fake provider scripting a tool call then a final answer.
type fake struct {
	turns []*provider.Response
	i     int
	seen  []provider.Request
}

func (f *fake) Label() string { return "fake/model" }
func (f *fake) Complete(_ context.Context, req provider.Request, onText func(string)) (*provider.Response, error) {
	f.seen = append(f.seen, req)
	r := f.turns[f.i]
	f.i++
	if onText != nil {
		for _, b := range r.Blocks {
			if b.Type == "text" {
				onText(b.Text)
			}
		}
	}
	return r, nil
}

func newTestAgent(t *testing.T, f *fake, mode permissions.Mode) (*Agent, *bytes.Buffer) {
	t.Helper()
	t.Setenv("ORCA_HOME", t.TempDir())
	root := t.TempDir()
	cfg, err := config.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	u := &ui.UI{Out: &out, In: bufio.NewReader(strings.NewReader("")), Color: false, IsTTY: false}
	tc := tools.NewContext(root)
	ag := New(f, cfg, permissions.New(mode, nil, nil), tc, u, "claude-sonnet-4-5")
	return ag, &out
}

func TestAgentLoopExecutesToolsAndFinishes(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		{Blocks: []provider.Block{
			provider.TextBlock("creating"),
			{Type: "tool_use", ID: "t1", Name: "write_file", Input: map[string]any{"path": "hello.txt", "content": "hi\n"}},
		}, StopReason: "tool_use", Usage: provider.Usage{In: 100, Out: 20}},
		{Blocks: []provider.Block{provider.TextBlock("done")}, StopReason: "end_turn", Usage: provider.Usage{In: 150, Out: 5}},
	}}
	ag, _ := newTestAgent(t, f, permissions.AcceptEdits)
	final, err := ag.Run(context.Background(), "make hello.txt")
	if err != nil {
		t.Fatal(err)
	}
	if final != "done" {
		t.Errorf("final = %q", final)
	}
	data, err := os.ReadFile(filepath.Join(ag.Cfg.Root, "hello.txt"))
	if err != nil || string(data) != "hi\n" {
		t.Errorf("tool did not run: %v %q", err, data)
	}
	// second request must contain the tool result
	if len(f.seen) != 2 {
		t.Fatalf("provider calls = %d", len(f.seen))
	}
	last := f.seen[1].Messages[len(f.seen[1].Messages)-1]
	if last.Role != "user" || last.Content[0].Type != "tool_result" || last.Content[0].ToolUseID != "t1" {
		t.Errorf("tool result not fed back: %+v", last)
	}
	if ag.TotalIn != 250 || ag.TotalOut != 25 {
		t.Errorf("usage tracking: %d/%d", ag.TotalIn, ag.TotalOut)
	}
	if ag.TotalCost <= 0 {
		t.Error("cost should be computed for known model")
	}
}

func TestAgentDeniesInPlanMode(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		{Blocks: []provider.Block{{Type: "tool_use", ID: "t1", Name: "write_file", Input: map[string]any{"path": "x", "content": "y"}}}},
		{Blocks: []provider.Block{provider.TextBlock("understood")}},
	}}
	ag, _ := newTestAgent(t, f, permissions.Plan)
	if _, err := ag.Run(context.Background(), "write x"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(ag.Cfg.Root, "x")); !os.IsNotExist(err) {
		t.Error("file must not exist in plan mode")
	}
	res := f.seen[1].Messages[len(f.seen[1].Messages)-1].Content[0]
	if !res.IsError || !strings.Contains(res.Content, "Permission denied") {
		t.Errorf("expected denial fed to model, got %+v", res)
	}
}

func TestAgentNonInteractiveAskBecomesDeny(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		{Blocks: []provider.Block{{Type: "tool_use", ID: "t1", Name: "bash", Input: map[string]any{"command": "make deploy"}}}},
		{Blocks: []provider.Block{provider.TextBlock("ok")}},
	}}
	ag, out := newTestAgent(t, f, permissions.Default)
	if _, err := ag.Run(context.Background(), "deploy"); err != nil {
		t.Fatal(err)
	}
	res := f.seen[1].Messages[len(f.seen[1].Messages)-1].Content[0]
	if !res.IsError {
		t.Errorf("non-interactive ask must deny, got %+v", res)
	}
	if !strings.Contains(out.String(), "non-interactive") {
		t.Error("user-facing message missing")
	}
}

func TestCostCapStopsSession(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		{Blocks: []provider.Block{provider.TextBlock("expensive")}, Usage: provider.Usage{In: 10_000_000, Out: 1_000_000}},
	}}
	ag, _ := newTestAgent(t, f, permissions.Default)
	ag.Cfg.MaxCostUSD = 0.01
	if _, err := ag.Run(context.Background(), "hi"); err == nil || !strings.Contains(err.Error(), "cost cap") {
		t.Errorf("expected cost cap error, got %v", err)
	}
}
