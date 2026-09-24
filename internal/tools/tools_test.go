package tools

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func newCtx(t *testing.T) *Context {
	t.Helper()
	return NewContext(t.TempDir())
}

func TestWriteReadEdit(t *testing.T) {
	c := newCtx(t)
	if _, err := Run(c, "write_file", map[string]any{"path": "src/main.go", "content": "package main\n\nfunc main() {}\n"}); err != nil {
		t.Fatal(err)
	}
	out, err := Run(c, "read_file", map[string]any{"path": "src/main.go"})
	if err != nil || !strings.Contains(out, "package main") {
		t.Fatalf("read failed: %v / %q", err, out)
	}
	if _, err := Run(c, "edit_file", map[string]any{
		"path": "src/main.go", "old_string": "func main() {}", "new_string": "func main() { println(1) }",
	}); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(filepath.Join(c.Root, "src/main.go"))
	if !strings.Contains(string(data), "println(1)") {
		t.Error("edit not applied")
	}
}

func TestEditUniquenessAndHint(t *testing.T) {
	c := newCtx(t)
	_, _ = Run(c, "write_file", map[string]any{"path": "a.txt", "content": "x = 1\ny = 2\nx = 1\n"})
	if _, err := Run(c, "edit_file", map[string]any{"path": "a.txt", "old_string": "x = 1", "new_string": "x = 9"}); err == nil {
		t.Error("ambiguous old_string must error")
	}
	if _, err := Run(c, "edit_file", map[string]any{"path": "a.txt", "old_string": "x = 1", "new_string": "x = 9", "replace_all": true}); err != nil {
		t.Errorf("replace_all should succeed: %v", err)
	}
	_, err := Run(c, "edit_file", map[string]any{"path": "a.txt", "old_string": "y = 22222", "new_string": "z"})
	if err == nil || !strings.Contains(err.Error(), "Closest match") {
		t.Errorf("expected closest-match hint, got: %v", err)
	}
}

func TestPathConfinement(t *testing.T) {
	c := newCtx(t)
	for _, p := range []string{"../escape.txt", "/etc/passwd", "~/x", "a/../../b"} {
		if _, err := Run(c, "read_file", map[string]any{"path": p}); err == nil || !strings.Contains(err.Error(), "escapes the project root") {
			t.Errorf("path %q must be blocked, got: %v", p, err)
		}
		if _, err := Run(c, "write_file", map[string]any{"path": p, "content": "x"}); err == nil || !strings.Contains(err.Error(), "escapes the project root") {
			t.Errorf("write to %q must be blocked, got: %v", p, err)
		}
	}
	c.AllowOutsideRoot = true
	tmp := filepath.Join(t.TempDir(), "ok.txt")
	if _, err := Run(c, "write_file", map[string]any{"path": tmp, "content": "x"}); err != nil {
		t.Errorf("outside write with opt-in should work: %v", err)
	}
}

func TestUndoBinarySafe(t *testing.T) {
	c := newCtx(t)
	bin := []byte{0x00, 0xff, 0x10, 0x88, 0x00, 0x7f}
	path := filepath.Join(c.Root, "blob.bin")
	if err := os.WriteFile(path, bin, 0o644); err != nil {
		t.Fatal(err)
	}
	c.Undo.BeginTurn()
	c.Undo.Push(path)
	if err := os.WriteFile(path, []byte("overwritten"), 0o644); err != nil {
		t.Fatal(err)
	}
	restored := c.Undo.UndoLastTurn()
	if len(restored) != 1 {
		t.Fatalf("restored = %v", restored)
	}
	data, _ := os.ReadFile(path)
	if !bytes.Equal(data, bin) {
		t.Error("binary content corrupted by undo (the Python bug)")
	}
}

func TestUndoDeletesNewFiles(t *testing.T) {
	c := newCtx(t)
	c.Undo.BeginTurn()
	_, _ = Run(c, "write_file", map[string]any{"path": "new.txt", "content": "hi"})
	c.Undo.UndoLastTurn()
	if _, err := os.Stat(filepath.Join(c.Root, "new.txt")); !os.IsNotExist(err) {
		t.Error("newly created file should be deleted on undo")
	}
}

func TestGrepAndGlobRespectIgnore(t *testing.T) {
	c := newCtx(t)
	_, _ = Run(c, "write_file", map[string]any{"path": "keep.go", "content": "package x // TODO fix\n"})
	if err := os.MkdirAll(filepath.Join(c.Root, "node_modules"), 0o755); err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(filepath.Join(c.Root, "node_modules", "dep.go"), []byte("// TODO vendor\n"), 0o644)

	out, err := Run(c, "grep", map[string]any{"pattern": "TODO"})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "keep.go") || strings.Contains(out, "node_modules") {
		t.Errorf("grep ignore handling wrong:\n%s", out)
	}
	out, _ = Run(c, "glob", map[string]any{"pattern": "**/*.go"})
	if !strings.Contains(out, "keep.go") || strings.Contains(out, "node_modules") {
		t.Errorf("glob ignore handling wrong:\n%s", out)
	}
}

func TestBashToolExecutesAndTruncates(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("bash integration test requires bash; install Git Bash/WSL for local shell execution")
	}
	c := newCtx(t)
	out, err := Run(c, "bash", map[string]any{"command": "echo hello"})
	if err != nil || !strings.Contains(out, "hello") {
		t.Fatalf("bash echo: %v %q", err, out)
	}
	out, err = Run(c, "bash", map[string]any{"command": "exit 3"})
	if err != nil || !strings.Contains(out, "[exit code: 3]") {
		t.Fatalf("exit code not reported: %v %q", err, out)
	}
	if _, err := Run(c, "bash", map[string]any{"command": "rm -rf /"}); err == nil {
		t.Error("catastrophic command must be refused at tool level")
	}
}

func TestTodoValidation(t *testing.T) {
	c := newCtx(t)
	if _, err := Run(c, "todo", map[string]any{"todos": []any{
		map[string]any{"content": "a", "status": "bogus"},
	}}); err == nil {
		t.Error("invalid status must error")
	}
	out, err := Run(c, "todo", map[string]any{"todos": []any{
		map[string]any{"content": "a", "status": "completed"},
		map[string]any{"content": "b", "status": "in_progress"},
	}})
	if err != nil || !strings.Contains(out, "☒ a") || !strings.Contains(out, "▶ b") {
		t.Errorf("todo render: %v %q", err, out)
	}
}
