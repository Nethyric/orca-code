package tools

import "fmt"

// Spec describes one tool: schema sent to the model + local handler + the
// permission category the permission engine uses.
type Spec struct {
	Name        string
	Description string
	Perm        string // read | write | bash | web | none
	Schema      map[string]any
	Fn          func(*Context, map[string]any) (string, error)
}

func schema(props map[string]any, required []string) map[string]any {
	return map[string]any{"type": "object", "properties": props, "required": required}
}

func str(desc string) map[string]any { return map[string]any{"type": "string", "description": desc} }
func num(desc string) map[string]any { return map[string]any{"type": "integer", "description": desc} }
func boolp(desc string) map[string]any {
	return map[string]any{"type": "boolean", "description": desc}
}

// Registry returns all tool specs in a stable order.
func Registry() []Spec {
	return []Spec{
		{
			Name: "read_file", Perm: "read",
			Description: "Read a text file with 1-based line numbers. Use offset/limit for slices of long files.",
			Schema: schema(map[string]any{
				"path": str("File path relative to the project root"), "offset": num("First line, 1-based"),
				"limit": num("Max lines (default 2000)"),
			}, []string{"path"}),
			Fn: toolReadFile,
		},
		{
			Name: "write_file", Perm: "write",
			Description: "Create or overwrite a file with full content. Parent dirs are created. Prefer edit_file for existing files.",
			Schema: schema(map[string]any{
				"path": str("File path"), "content": str("Complete file content"),
			}, []string{"path", "content"}),
			Fn: toolWriteFile,
		},
		{
			Name: "edit_file", Perm: "write",
			Description: "Replace an exact string in a file. old_string must match exactly and be unique unless replace_all=true. On mismatch you get a closest-match hint.",
			Schema: schema(map[string]any{
				"path": str("File path"), "old_string": str("Exact text to find"),
				"new_string": str("Replacement text"), "replace_all": boolp("Replace every occurrence"),
			}, []string{"path", "old_string", "new_string"}),
			Fn: toolEditFile,
		},
		{
			Name: "bash", Perm: "bash",
			Description: "Run a shell command in the project root (bash on POSIX, cmd on Windows). Output is combined and truncated to 30k chars.",
			Schema: schema(map[string]any{
				"command": str("The command to run"), "timeout": num("Seconds (default 120, max 600)"),
			}, []string{"command"}),
			Fn: toolBash,
		},
		{
			Name: "grep", Perm: "read",
			Description: "Search file contents with a Go regexp. Respects .gitignore, skips binary files. Max 200 matches.",
			Schema: schema(map[string]any{
				"pattern": str("Regular expression"), "path": str("File or directory (default .)"),
				"glob": str("Only files matching this glob, e.g. *.go"), "ignore_case": boolp("Case-insensitive"),
			}, []string{"pattern"}),
			Fn: toolGrep,
		},
		{
			Name: "glob", Perm: "read",
			Description: "Find files by glob pattern (supports **). Sorted by modification time, newest first.",
			Schema: schema(map[string]any{
				"pattern": str("e.g. **/*.go or src/**/*.ts"), "path": str("Directory to search (default .)"),
			}, []string{"pattern"}),
			Fn: toolGlob,
		},
		{
			Name: "ls", Perm: "read",
			Description: "List a directory, dirs first. all=true includes dotfiles.",
			Schema: schema(map[string]any{
				"path": str("Directory (default .)"), "all": boolp("Include dotfiles"),
			}, nil),
			Fn: toolLs,
		},
		{
			Name: "todo", Perm: "none",
			Description: "Replace the task list for multi-step work. Statuses: pending | in_progress | completed.",
			Schema: schema(map[string]any{
				"todos": map[string]any{"type": "array", "items": schema(map[string]any{
					"content": str("Task"), "status": map[string]any{"type": "string", "enum": []string{"pending", "in_progress", "completed"}},
				}, []string{"content", "status"})},
			}, []string{"todos"}),
			Fn: toolTodo,
		},
		{
			Name: "web_fetch", Perm: "web",
			Description: "Fetch an http(s) URL and return readable text (HTML stripped, 8k chars max). Private/internal addresses are blocked.",
			Schema: schema(map[string]any{
				"url": str("Full http(s) URL"),
			}, []string{"url"}),
			Fn: toolWebFetch,
		},
		{
			Name: "web_search", Perm: "web",
			Description: "Keyless web search (DuckDuckGo). Returns numbered titles+URLs; follow up with web_fetch.",
			Schema: schema(map[string]any{
				"query": str("Search query"), "max_results": num("1-8, default 5"),
			}, []string{"query"}),
			Fn: toolWebSearch,
		},
	}
}

var byName = func() map[string]Spec {
	m := map[string]Spec{}
	for _, s := range Registry() {
		m[s.Name] = s
	}
	return m
}()

// Lookup returns the spec for name.
func Lookup(name string) (Spec, bool) {
	s, ok := byName[name]
	return s, ok
}

// Run executes a tool by name. Any returned error is a model-visible result.
func Run(c *Context, name string, args map[string]any) (string, error) {
	spec, ok := byName[name]
	if !ok {
		return "", fmt.Errorf("unknown tool %q", name)
	}
	if args == nil {
		args = map[string]any{}
	}
	return spec.Fn(c, args)
}
