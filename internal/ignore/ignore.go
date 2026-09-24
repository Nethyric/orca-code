// Package ignore implements .gitignore matching WITH negation support
// (`!pattern`), which the Python version silently dropped.
package ignore

import (
	"os"
	"path"
	"path/filepath"
	"strings"
)

// DefaultDirs are always skipped when walking, in every project.
var DefaultDirs = map[string]bool{
	".git": true, ".hg": true, ".svn": true, "node_modules": true,
	"__pycache__": true, ".venv": true, "venv": true, ".mypy_cache": true,
	".pytest_cache": true, ".ruff_cache": true, "dist": true, "build": true,
	"target": true, ".next": true, ".nuxt": true, ".turbo": true,
	".idea": true, ".tox": true, ".cache": true, ".DS_Store": true,
}

type rule struct {
	pattern  string
	negate   bool
	dirOnly  bool
	anchored bool // pattern contains a slash → match against full rel path
}

// Ignore holds an ordered gitignore rule set. Last matching rule wins.
type Ignore struct {
	rules []rule
}

// Load reads root/.gitignore (missing file → empty set, never an error).
func Load(root string) *Ignore {
	ig := &Ignore{}
	data, err := os.ReadFile(filepath.Join(root, ".gitignore"))
	if err != nil {
		return ig
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		r := rule{}
		if strings.HasPrefix(line, "!") {
			r.negate = true
			line = line[1:]
		}
		if strings.HasSuffix(line, "/") {
			r.dirOnly = true
			line = strings.TrimSuffix(line, "/")
		}
		line = strings.TrimPrefix(line, "/")
		r.anchored = strings.Contains(line, "/")
		r.pattern = line
		if r.pattern != "" {
			ig.rules = append(ig.rules, r)
		}
	}
	return ig
}

// Match reports whether rel (a slash-separated path relative to the root)
// should be ignored. Gitignore semantics: rules apply in order, the last
// match decides, `!` re-includes.
func (ig *Ignore) Match(rel string, isDir bool) bool {
	rel = strings.TrimPrefix(path.Clean(rel), "./")
	base := path.Base(rel)
	if DefaultDirs[base] && isDir {
		return true
	}
	ignored := false
	for _, r := range ig.rules {
		if r.dirOnly && !isDir {
			continue
		}
		var hit bool
		if r.anchored {
			hit = globPath(r.pattern, rel)
		} else {
			hit, _ = path.Match(r.pattern, base)
		}
		if hit {
			ignored = !r.negate
		}
	}
	return ignored
}

// globPath matches slash-separated glob patterns with `**` support.
func globPath(pattern, rel string) bool {
	pp := strings.Split(pattern, "/")
	rp := strings.Split(rel, "/")
	var match func(pi, ri int) bool
	match = func(pi, ri int) bool {
		if pi == len(pp) {
			return ri == len(rp)
		}
		if pp[pi] == "**" {
			for skip := ri; skip <= len(rp); skip++ {
				if match(pi+1, skip) {
					return true
				}
			}
			return false
		}
		if ri >= len(rp) {
			return false
		}
		ok, _ := path.Match(pp[pi], rp[ri])
		return ok && match(pi+1, ri+1)
	}
	return match(0, 0)
}
