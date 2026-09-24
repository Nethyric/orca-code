package agent

import (
	"context"
	"fmt"

	"github.com/Nethyric/orca/internal/provider"
)

// DefaultCompactChars ≈ 75k tokens of history before auto-compaction kicks in.
const DefaultCompactChars = 300_000

// estimateChars approximates the conversation size (≈ tokens × 4).
func estimateChars(msgs []provider.Message) int {
	total := 0
	for _, m := range msgs {
		for _, b := range m.Content {
			total += len(b.Text) + len(b.Content)
			for k, v := range b.Input {
				total += len(k)
				if s, ok := v.(string); ok {
					total += len(s)
				}
			}
		}
	}
	return total
}

// findCut returns the largest safe boundary ≤ target: a user message whose
// first block is plain text (never between a tool_use and its tool_result).
func findCut(msgs []provider.Message, target int) int {
	best := 0
	for i, m := range msgs {
		if i > target {
			break
		}
		if i == 0 {
			continue // cutting at 0 would summarise nothing
		}
		if m.Role == "user" && len(m.Content) > 0 && m.Content[0].Type == "text" {
			best = i
		}
	}
	return best
}

// maybeCompact summarises older history with the model itself when the
// conversation grows past the threshold, keeping recent turns verbatim.
func (a *Agent) maybeCompact(ctx context.Context) {
	threshold := a.Cfg.CompactChars
	if threshold < 0 {
		return // disabled
	}
	if threshold == 0 {
		threshold = DefaultCompactChars
	}
	if estimateChars(a.Messages) < threshold || len(a.Messages) < 6 {
		return
	}
	cut := findCut(a.Messages, len(a.Messages)*7/10)
	if cut < 2 {
		return
	}
	old := a.Messages[:cut]
	sumReq := provider.Request{
		System: "You compress coding-agent conversations. Produce a dense summary that preserves: the user's goals, every file path touched and what changed, key decisions, unresolved problems, and important tool output. No preamble.",
		Messages: append(append([]provider.Message{}, old...), provider.Message{
			Role:    "user",
			Content: []provider.Block{provider.TextBlock("Summarize the conversation above now, following your instructions.")},
		}),
		MaxTokens: 2000,
	}
	resp, err := a.Provider.Complete(ctx, sumReq, nil)
	if err != nil || resp.Text() == "" {
		a.UI.Warn("auto-compaction failed; continuing with full history")
		return
	}
	a.addUsage(resp.Usage)
	summary := provider.Message{Role: "user", Content: []provider.Block{provider.TextBlock(
		"[Earlier conversation summary — treat as authoritative history]\n" + resp.Text(),
	)}}
	a.Messages = append([]provider.Message{summary}, a.Messages[cut:]...)
	a.UI.Info(fmt.Sprintf("⌁ compacted history: %d → %d messages", cut+len(a.Messages)-1, len(a.Messages)))
}
