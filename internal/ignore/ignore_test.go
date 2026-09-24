package ignore

import (
	"os"
	"path/filepath"
	"testing"
)

func load(t *testing.T, content string) *Ignore {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, ".gitignore"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return Load(dir)
}

func TestNegationSupport(t *testing.T) {
	ig := load(t, "*.log\n!keep.log\n")
	if !ig.Match("debug.log", false) {
		t.Error("debug.log should be ignored")
	}
	if ig.Match("keep.log", false) {
		t.Error("keep.log must be re-included by !keep.log")
	}
}

func TestDirOnlyAndAnchored(t *testing.T) {
	ig := load(t, "tmp/\nsrc/*.gen.go\ndocs/**/draft.md\n")
	if !ig.Match("tmp", true) {
		t.Error("tmp/ dir should match")
	}
	if ig.Match("tmp", false) {
		t.Error("plain file named tmp should NOT match dir-only rule")
	}
	if !ig.Match("src/a.gen.go", false) {
		t.Error("anchored glob should match")
	}
	if ig.Match("other/a.gen.go", false) {
		t.Error("anchored glob must not match other dirs")
	}
	if !ig.Match("docs/a/b/draft.md", false) {
		t.Error("** should span directories")
	}
}

func TestDefaultDirs(t *testing.T) {
	ig := &Ignore{}
	if !ig.Match("node_modules", true) {
		t.Error("node_modules dir always ignored")
	}
	if ig.Match("main.go", false) {
		t.Error("main.go must not be ignored")
	}
}
