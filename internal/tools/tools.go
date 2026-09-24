// Package tools implements the agent's hands: file IO, search, shell and web.
// Every path is confined to the project root (symlink-aware); escapes are a
// hard error unless the user launched orca with --allow-outside-root.
package tools

import (
	"bytes"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/Nethyric/orca/internal/ignore"
	"github.com/Nethyric/orca/internal/security"
)

const (
	MaxReadBytes   = 5_000_000
	MaxGrepResults = 200
	MaxGlobResults = 500
	MaxWalkFiles   = 50_000
)

type Todo struct {
	Content string `json:"content"`
	Status  string `json:"status"`
}

// Context carries per-session tool state.
type Context struct {
	Root             string
	Ignore           *ignore.Ignore
	Undo             *UndoStack
	Todos            []Todo
	AllowOutsideRoot bool
	WebClient        *http.Client // SSRF-safe; injectable for tests
}

func NewContext(root string) *Context {
	abs, _ := filepath.Abs(root)
	return &Context{
		Root:      abs,
		Ignore:    ignore.Load(abs),
		Undo:      &UndoStack{},
		WebClient: security.SafeHTTPClient(25 * time.Second),
	}
}

// resolve confines p to the project root.
func (c *Context) resolve(p string) (string, error) {
	abs, inside := security.ResolveInRoot(c.Root, p)
	if !inside && !c.AllowOutsideRoot {
		return "", fmt.Errorf("path %q escapes the project root — blocked (start orca with --allow-outside-root to permit)", p)
	}
	return abs, nil
}

func (c *Context) rel(abs string) string {
	if r, err := filepath.Rel(c.Root, abs); err == nil && !strings.HasPrefix(r, "..") {
		return filepath.ToSlash(r)
	}
	return filepath.ToSlash(abs)
}

// ---- helpers ---------------------------------------------------------------

func strArg(args map[string]any, key string) string {
	if v, ok := args[key].(string); ok {
		return v
	}
	return ""
}

func intArg(args map[string]any, key string, def int) int {
	switch v := args[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	}
	return def
}

func boolArg(args map[string]any, key string) bool {
	v, _ := args[key].(bool)
	return v
}

func isBinary(data []byte) bool {
	n := len(data)
	if n > 8192 {
		n = 8192
	}
	return bytes.IndexByte(data[:n], 0) >= 0
}

// walk lists files under dir honouring .gitignore + default ignores.
func (c *Context) walk(dir string) ([]string, error) {
	var out []string
	err := filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return nil //nolint:nilerr — unreadable entries are skipped
		}
		rel := c.rel(p)
		if p != dir && c.Ignore.Match(rel, d.IsDir()) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if !d.IsDir() {
			out = append(out, p)
			if len(out) >= MaxWalkFiles {
				return filepath.SkipAll
			}
		}
		return nil
	})
	return out, err
}

// ---- read_file --------------------------------------------------------------

func toolReadFile(c *Context, args map[string]any) (string, error) {
	abs, err := c.resolve(strArg(args, "path"))
	if err != nil {
		return "", err
	}
	info, err := os.Stat(abs)
	if err != nil {
		return "", fmt.Errorf("file not found: %s", c.rel(abs))
	}
	if info.IsDir() {
		return "", fmt.Errorf("%s is a directory (use ls)", c.rel(abs))
	}
	if info.Size() > MaxReadBytes {
		return "", fmt.Errorf("file too large (%d bytes): %s", info.Size(), c.rel(abs))
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return "", err
	}
	if isBinary(data) {
		return "", fmt.Errorf("binary file: %s", c.rel(abs))
	}
	offset := intArg(args, "offset", 1)
	if offset < 1 {
		offset = 1
	}
	limit := intArg(args, "limit", 2000)
	lines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	total := len(lines)
	if offset > total {
		return fmt.Sprintf("(no lines at offset %d; file has %d lines)", offset, total), nil
	}
	end := offset - 1 + limit
	if end > total {
		end = total
	}
	var b strings.Builder
	if offset > 1 {
		fmt.Fprintf(&b, "⋯ showing lines %d–%d of %d\n", offset, end, total)
	}
	for i := offset - 1; i < end; i++ {
		fmt.Fprintf(&b, "%6d\t%s\n", i+1, lines[i])
	}
	if end < total {
		fmt.Fprintf(&b, "⋯ %d more lines (use offset=%d to continue)", total-end, end+1)
	}
	return strings.TrimSuffix(b.String(), "\n"), nil
}

// ---- write_file -------------------------------------------------------------

func toolWriteFile(c *Context, args map[string]any) (string, error) {
	abs, err := c.resolve(strArg(args, "path"))
	if err != nil {
		return "", err
	}
	content, ok := args["content"].(string)
	if !ok {
		return "", fmt.Errorf("write_file requires 'content'")
	}
	c.Undo.Push(abs)
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(abs, []byte(content), 0o644); err != nil {
		return "", err
	}
	n := strings.Count(content, "\n")
	if content != "" && !strings.HasSuffix(content, "\n") {
		n++
	}
	return fmt.Sprintf("Wrote %s (%d lines)", c.rel(abs), n), nil
}

// ---- edit_file --------------------------------------------------------------

func toolEditFile(c *Context, args map[string]any) (string, error) {
	abs, err := c.resolve(strArg(args, "path"))
	if err != nil {
		return "", err
	}
	oldS := strArg(args, "old_string")
	newS := strArg(args, "new_string")
	if oldS == "" {
		return "", fmt.Errorf("edit_file requires a non-empty 'old_string'")
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return "", fmt.Errorf("file not found: %s", c.rel(abs))
	}
	if isBinary(data) {
		return "", fmt.Errorf("cannot edit binary file: %s", c.rel(abs))
	}
	content := string(data)
	count := strings.Count(content, oldS)
	if count == 0 {
		hint := closestLineHint(content, oldS)
		return "", fmt.Errorf("old_string not found in %s.%s", c.rel(abs), hint)
	}
	if count > 1 && !boolArg(args, "replace_all") {
		return "", fmt.Errorf("old_string appears %d times in %s — make it unique (add surrounding lines) or set replace_all=true", count, c.rel(abs))
	}
	c.Undo.Push(abs)
	var updated string
	if boolArg(args, "replace_all") {
		updated = strings.ReplaceAll(content, oldS, newS)
	} else {
		updated = strings.Replace(content, oldS, newS, 1)
	}
	if err := os.WriteFile(abs, []byte(updated), 0o644); err != nil {
		return "", err
	}
	label := "1 replacement"
	if count > 1 {
		label = fmt.Sprintf("%d replacements", count)
	}
	return fmt.Sprintf("Edited %s (%s)", c.rel(abs), label), nil
}

// closestLineHint helps the model self-correct after a failed exact match.
func closestLineHint(content, oldS string) string {
	first := strings.TrimSpace(strings.SplitN(oldS, "\n", 2)[0])
	if first == "" {
		return ""
	}
	lines := strings.Split(content, "\n")
	bestIdx, bestScore := -1, 0
	for i, line := range lines {
		score := commonLen(strings.TrimSpace(line), first)
		if score > bestScore {
			bestScore, bestIdx = score, i
		}
	}
	if bestIdx < 0 || bestScore*2 < len(first) {
		return ""
	}
	lo := bestIdx - 2
	if lo < 0 {
		lo = 0
	}
	hi := bestIdx + 3
	if hi > len(lines) {
		hi = len(lines)
	}
	var b strings.Builder
	b.WriteString(" Closest match near line " + fmt.Sprint(bestIdx+1) + ":\n")
	for i := lo; i < hi; i++ {
		fmt.Fprintf(&b, "%6d\t%s\n", i+1, lines[i])
	}
	return strings.TrimSuffix(b.String(), "\n")
}

func commonLen(a, b string) int {
	n := 0
	for n < len(a) && n < len(b) && a[n] == b[n] {
		n++
	}
	return n
}

// ---- ls ----------------------------------------------------------------------

func toolLs(c *Context, args map[string]any) (string, error) {
	p := strArg(args, "path")
	if p == "" {
		p = "."
	}
	abs, err := c.resolve(p)
	if err != nil {
		return "", err
	}
	entries, err := os.ReadDir(abs)
	if err != nil {
		return "", err
	}
	showAll := boolArg(args, "all")
	var dirs, files []string
	for _, e := range entries {
		name := e.Name()
		if !showAll && strings.HasPrefix(name, ".") {
			continue
		}
		if e.IsDir() {
			dirs = append(dirs, name+"/")
		} else {
			files = append(files, name)
		}
	}
	sort.Strings(dirs)
	sort.Strings(files)
	out := append(dirs, files...)
	if len(out) == 0 {
		return "(empty directory)", nil
	}
	return strings.Join(out, "\n"), nil
}

// ---- todo ----------------------------------------------------------------------

func toolTodo(c *Context, args map[string]any) (string, error) {
	raw, ok := args["todos"].([]any)
	if !ok {
		return "", fmt.Errorf("todo requires 'todos' (array)")
	}
	todos := make([]Todo, 0, len(raw))
	for _, item := range raw {
		m, ok := item.(map[string]any)
		if !ok {
			return "", fmt.Errorf("each todo must be an object with content/status")
		}
		td := Todo{Content: strArg(m, "content"), Status: strArg(m, "status")}
		switch td.Status {
		case "pending", "in_progress", "completed":
		default:
			return "", fmt.Errorf("invalid status %q (pending|in_progress|completed)", td.Status)
		}
		todos = append(todos, td)
	}
	c.Todos = todos
	var b strings.Builder
	for _, td := range todos {
		mark := "☐"
		switch td.Status {
		case "completed":
			mark = "☒"
		case "in_progress":
			mark = "▶"
		}
		fmt.Fprintf(&b, "%s %s\n", mark, td.Content)
	}
	return strings.TrimSuffix(b.String(), "\n"), nil
}
