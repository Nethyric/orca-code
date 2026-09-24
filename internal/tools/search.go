package tools

import (
	"fmt"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"
)

// ---- grep -------------------------------------------------------------------

func toolGrep(c *Context, args map[string]any) (string, error) {
	pattern := strArg(args, "pattern")
	if pattern == "" {
		return "", fmt.Errorf("grep requires 'pattern'")
	}
	if boolArg(args, "ignore_case") {
		pattern = "(?i)" + pattern
	}
	re, err := regexp.Compile(pattern)
	if err != nil {
		return "", fmt.Errorf("invalid regexp: %v", err)
	}
	p := strArg(args, "path")
	if p == "" {
		p = "."
	}
	abs, err := c.resolve(p)
	if err != nil {
		return "", err
	}
	globPat := strArg(args, "glob")

	var files []string
	if info, err := os.Stat(abs); err == nil && !info.IsDir() {
		files = []string{abs}
	} else {
		files, _ = c.walk(abs)
	}

	var out []string
	for _, f := range files {
		rel := c.rel(f)
		if globPat != "" {
			if ok, _ := path.Match(globPat, path.Base(rel)); !ok && !globMatch(globPat, rel) {
				continue
			}
		}
		data, err := os.ReadFile(f)
		if err != nil || isBinary(data) {
			continue
		}
		for i, line := range strings.Split(string(data), "\n") {
			if re.MatchString(line) {
				if len(line) > 400 {
					line = line[:400] + "…"
				}
				out = append(out, fmt.Sprintf("%s:%d: %s", rel, i+1, strings.TrimRight(line, "\r")))
				if len(out) >= MaxGrepResults {
					out = append(out, fmt.Sprintf("⋯ stopped at %d matches", MaxGrepResults))
					return strings.Join(out, "\n"), nil
				}
			}
		}
	}
	if len(out) == 0 {
		return "(no matches)", nil
	}
	return strings.Join(out, "\n"), nil
}

// ---- glob -------------------------------------------------------------------

// globMatch matches slash-separated glob patterns with ** support.
func globMatch(pattern, rel string) bool {
	pp := strings.Split(strings.Trim(pattern, "/"), "/")
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

func toolGlob(c *Context, args map[string]any) (string, error) {
	pattern := strArg(args, "pattern")
	if pattern == "" {
		return "", fmt.Errorf("glob requires 'pattern'")
	}
	p := strArg(args, "path")
	if p == "" {
		p = "."
	}
	abs, err := c.resolve(p)
	if err != nil {
		return "", err
	}
	files, _ := c.walk(abs)
	type hit struct {
		rel   string
		mtime int64
	}
	var hits []hit
	for _, f := range files {
		rel := c.rel(f)
		if globMatch(pattern, rel) || func() bool { ok, _ := path.Match(pattern, path.Base(rel)); return ok }() {
			var mt int64
			if info, err := os.Stat(f); err == nil {
				mt = info.ModTime().UnixNano()
			}
			hits = append(hits, hit{rel, mt})
			if len(hits) >= MaxGlobResults {
				break
			}
		}
	}
	if len(hits) == 0 {
		return "(no files match)", nil
	}
	sort.Slice(hits, func(i, j int) bool { return hits[i].mtime > hits[j].mtime })
	out := make([]string, len(hits))
	for i, h := range hits {
		out[i] = h.rel
	}
	return strings.Join(out, "\n"), nil
}
