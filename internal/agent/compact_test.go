package agent

import (
	"context"
	"strings"
	"testing"

	"github.com/Nethyric/orca/internal/permissions"
	"github.com/Nethyric/orca/internal/provider"
)

func bigHistory(n int, filler string) []provider.Message {
	var msgs []provider.Message
	for i := 0; i < n; i++ {
		msgs = append(msgs,
			provider.Message{Role: "user", Content: []provider.Block{provider.TextBlock("task " + filler)}},
			provider.Message{Role: "assistant", Content: []provider.Block{provider.TextBlock("done " + filler)}},
		)
	}
	return msgs
}

func TestAutoCompaction(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		// 1st provider call = the summary request
		{Blocks: []provider.Block{provider.TextBlock("SUMMARY: built the API, edited api/routes.go")}},
		// 2nd = the actual answer
		{Blocks: []provider.Block{provider.TextBlock("final answer")}},
	}}
	ag, _ := newTestAgent(t, f, permissions.Default)
	ag.Cfg.CompactChars = 500 // tiny threshold to trigger
	ag.Messages = bigHistory(10, strings.Repeat("x", 100))
	before := len(ag.Messages)

	out, err := ag.Run(context.Background(), "continue")
	if err != nil {
		t.Fatal(err)
	}
	if out != "final answer" {
		t.Errorf("final = %q", out)
	}
	if len(f.seen) != 2 {
		t.Fatalf("provider calls = %d, want 2 (summary + turn)", len(f.seen))
	}
	if !strings.Contains(f.seen[0].System, "compress") {
		t.Error("first call must be the summary request")
	}
	if len(ag.Messages) >= before {
		t.Errorf("history not compacted: %d → %d", before, len(ag.Messages))
	}
	first := ag.Messages[0]
	if first.Role != "user" || !strings.Contains(first.Content[0].Text, "SUMMARY: built the API") {
		t.Errorf("summary message missing: %+v", first)
	}
}

func TestCompactionDisabled(t *testing.T) {
	f := &fake{turns: []*provider.Response{
		{Blocks: []provider.Block{provider.TextBlock("ok")}},
	}}
	ag, _ := newTestAgent(t, f, permissions.Default)
	ag.Cfg.CompactChars = -1 // disabled
	ag.Messages = bigHistory(10, strings.Repeat("x", 100))
	if _, err := ag.Run(context.Background(), "hi"); err != nil {
		t.Fatal(err)
	}
	if len(f.seen) != 1 {
		t.Errorf("no summary call expected, got %d calls", len(f.seen))
	}
}

func TestFindCutNeverSplitsToolPairs(t *testing.T) {
	msgs := []provider.Message{
		{Role: "user", Content: []provider.Block{provider.TextBlock("a")}},
		{Role: "assistant", Content: []provider.Block{{Type: "tool_use", ID: "t", Name: "bash"}}},
		{Role: "user", Content: []provider.Block{provider.ToolResultBlock("t", "out", false)}}, // not a valid cut
		{Role: "assistant", Content: []provider.Block{provider.TextBlock("b")}},
		{Role: "user", Content: []provider.Block{provider.TextBlock("next task")}}, // valid cut = 4
		{Role: "assistant", Content: []provider.Block{provider.TextBlock("c")}},
	}
	if cut := findCut(msgs, 5); cut != 4 {
		t.Errorf("cut = %d, want 4", cut)
	}
	if cut := findCut(msgs, 3); cut != 0 {
		t.Errorf("cut with low target = %d, want 0 (tool_result is not a boundary)", cut)
	}
}
