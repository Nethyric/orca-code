package tools

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"time"

	"github.com/Nethyric/orca/internal/security"
)

const (
	MaxShellOutput  = 30_000
	DefaultShellSec = 120
	MaxShellSec     = 600
)

func shellArgv(command string) []string {
	if runtime.GOOS == "windows" {
		return []string{"cmd", "/c", command}
	}
	return []string{"bash", "-c", command}
}

func toolBash(c *Context, args map[string]any) (string, error) {
	command := strArg(args, "command")
	if command == "" {
		return "", fmt.Errorf("bash requires 'command'")
	}
	if security.IsCatastrophic(command) {
		return "", fmt.Errorf("refused: this command matches a known-destructive pattern and is blocked in every mode")
	}
	sec := intArg(args, "timeout", DefaultShellSec)
	if sec > MaxShellSec {
		sec = MaxShellSec
	}
	if sec < 1 {
		sec = 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(sec)*time.Second)
	defer cancel()

	argv := shellArgv(command)
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Dir = c.Root
	out, err := cmd.CombinedOutput()
	text := string(out)
	if ctx.Err() == context.DeadlineExceeded {
		return truncateMiddle(fmt.Sprintf("%s\n[timed out after %ds]", text, sec)), nil
	}
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return truncateMiddle(fmt.Sprintf("%s\n[exit code: %d]", text, exitErr.ExitCode())), nil
		}
		return "", fmt.Errorf("failed to run command: %v", err)
	}
	if text == "" {
		return "(no output)", nil
	}
	return truncateMiddle(text), nil
}

func truncateMiddle(text string) string {
	for len(text) > 0 && (text[len(text)-1] == '\n' || text[len(text)-1] == '\r') {
		text = text[:len(text)-1]
	}
	if len(text) <= MaxShellOutput {
		if text == "" {
			return "(no output)"
		}
		return text
	}
	half := MaxShellOutput / 2
	dropped := len(text) - MaxShellOutput
	return fmt.Sprintf("%s\n⋯ [truncated %d characters] ⋯\n%s", text[:half], dropped, text[len(text)-half:])
}
