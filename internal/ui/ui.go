// Package ui renders Orca's terminal output: banner, streaming text, tool
// lines, diffs, permission prompts. Colors respect NO_COLOR and non-TTY.
package ui

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
)

const (
	esc     = "\x1b["
	reset   = esc + "0m"
	bold    = esc + "1m"
	dim     = esc + "2m"
	cyan    = esc + "38;5;81m"
	deepCyn = esc + "38;5;38m"
	green   = esc + "38;5;114m"
	red     = esc + "38;5;203m"
	yellow  = esc + "38;5;221m"
	magenta = esc + "38;5;141m"
	grey    = esc + "38;5;245m"
)

type UI struct {
	Out              io.Writer
	In               *bufio.Reader
	Color            bool
	IsTTY            bool
	StreamingStarted bool
}

func New() *UI {
	isTTY := false
	if fi, err := os.Stdout.Stat(); err == nil {
		isTTY = fi.Mode()&os.ModeCharDevice != 0
	}
	return &UI{
		Out:   os.Stdout,
		In:    bufio.NewReader(os.Stdin),
		Color: isTTY && os.Getenv("NO_COLOR") == "",
		IsTTY: isTTY,
	}
}

func (u *UI) c(code, s string) string {
	if !u.Color {
		return s
	}
	return code + s + reset
}

// Banner prints the startup box.
func (u *UI) Banner(version, providerLabel, root, mode string) {
	line := strings.Repeat("─", 56)
	fmt.Fprintf(u.Out, "%s\n", u.c(deepCyn, "╭─ "+u.c(bold+cyan, "orca")+u.c(deepCyn, " ── deep ocean "+line[:38]+"╮")))
	fmt.Fprintf(u.Out, "%s  %s %s\n", u.c(deepCyn, "│"), u.c(grey, "model"), u.c(bold, providerLabel))
	fmt.Fprintf(u.Out, "%s  %s %s\n", u.c(deepCyn, "│"), u.c(grey, "root "), root)
	fmt.Fprintf(u.Out, "%s  %s %s   %s\n", u.c(deepCyn, "│"), u.c(grey, "mode "), mode, u.c(grey, "v"+version+" · /help for commands"))
	fmt.Fprintf(u.Out, "%s\n", u.c(deepCyn, "╰"+line+"╯"))
}

// StreamText prints a streamed model text delta.
func (u *UI) StreamText(delta string) {
	u.StreamingStarted = true
	fmt.Fprint(u.Out, delta)
}

// EndStream terminates a streamed answer with a newline if needed.
func (u *UI) EndStream() {
	if u.StreamingStarted {
		fmt.Fprintln(u.Out)
		u.StreamingStarted = false
	}
}

// ToolCall renders "◆ bash(go test ./...)".
func (u *UI) ToolCall(name, detail string) {
	if len(detail) > 100 {
		detail = detail[:100] + "…"
	}
	detail = strings.ReplaceAll(detail, "\n", " ")
	fmt.Fprintf(u.Out, "%s %s%s%s%s\n", u.c(magenta, "◆"), u.c(bold+cyan, name), u.c(grey, "("), detail, u.c(grey, ")"))
}

// ToolResult renders the "↳ …" line under a tool call.
func (u *UI) ToolResult(summary string, isErr bool) {
	if len(summary) > 120 {
		summary = summary[:120] + "…"
	}
	summary = strings.ReplaceAll(summary, "\n", " · ")
	col := green
	if isErr {
		col = red
	}
	fmt.Fprintf(u.Out, "  %s %s\n", u.c(col, "↳"), u.c(dim, summary))
}

// Meter renders the per-turn usage line.
func (u *UI) Meter(inTok, outTok int, cost float64, capUSD float64) {
	capStr := ""
	if capUSD > 0 {
		capStr = fmt.Sprintf(" / cap $%.2f", capUSD)
	}
	costStr := ""
	if cost > 0 {
		costStr = fmt.Sprintf(" · $%.4f%s", cost, capStr)
	}
	fmt.Fprintf(u.Out, "%s\n", u.c(grey, fmt.Sprintf("⌁ tokens %d in / %d out%s", inTok, outTok, costStr)))
}

func (u *UI) Info(msg string)  { fmt.Fprintf(u.Out, "%s\n", u.c(grey, msg)) }
func (u *UI) Warn(msg string)  { fmt.Fprintf(u.Out, "%s %s\n", u.c(yellow, "⚠"), msg) }
func (u *UI) Error(msg string) { fmt.Fprintf(u.Out, "%s %s\n", u.c(red, "✗"), msg) }
func (u *UI) Success(msg string) {
	fmt.Fprintf(u.Out, "%s %s\n", u.c(green, "✓"), msg)
}

// AskPermission prompts the user for a gated tool call.
// Returns "y" (once), "a" (always this session), or "n" (deny).
func (u *UI) AskPermission(tool, detail string) string {
	fmt.Fprintf(u.Out, "\n%s %s wants to run:\n", u.c(yellow, "▲"), u.c(bold+cyan, tool))
	for _, line := range strings.Split(strings.TrimSpace(detail), "\n") {
		fmt.Fprintf(u.Out, "    %s\n", line)
	}
	fmt.Fprintf(u.Out, "  %s ", u.c(bold, "[y]es once · [a]lways this session · [n]o?"))
	if !u.IsTTY {
		fmt.Fprintln(u.Out, u.c(grey, "(non-interactive → denied)"))
		return "n"
	}
	answer, err := u.In.ReadString('\n')
	if err != nil {
		return "n"
	}
	switch strings.ToLower(strings.TrimSpace(answer)) {
	case "y", "yes":
		return "y"
	case "a", "always":
		return "a"
	default:
		return "n"
	}
}

// ReadLine shows the REPL prompt and reads one line.
func (u *UI) ReadLine() (string, error) {
	fmt.Fprintf(u.Out, "%s ", u.c(bold+deepCyn, "orca ❯"))
	line, err := u.In.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(line), nil
}
