// Package permissions decides allow / ask / deny for every tool call.
// Friction scales with danger; nothing dangerous is ever auto-approved
// based on regex blacklists alone.
package permissions

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/Nethyric/orca/internal/security"
)

type Mode string

const (
	Default     Mode = "default"     // reads free; writes/bash/web ask (safe read-only bash auto)
	AcceptEdits Mode = "acceptEdits" // file edits auto; bash/web still gated
	Plan        Mode = "plan"        // read-only exploration
	Yolo        Mode = "yolo"        // everything allowed except catastrophic
)

var Modes = []Mode{Default, AcceptEdits, Plan, Yolo}

func ParseMode(s string) (Mode, error) {
	for _, m := range Modes {
		if string(m) == s {
			return m, nil
		}
	}
	return "", fmt.Errorf("unknown permission mode %q (default|acceptEdits|plan|yolo)", s)
}

type Verdict string

const (
	Allow Verdict = "allow"
	Ask   Verdict = "ask"
	Deny  Verdict = "deny"
)

type Decision struct {
	Verdict Verdict
	Reason  string
}

const PlanNotice = "Plan mode is active: file modification, command execution and web access are disabled. " +
	"Explore with read_file/grep/glob/ls and present a concrete plan."

type Permissions struct {
	Mode  Mode
	Allow []string
	Deny  []string
}

func New(mode Mode, allow, deny []string) *Permissions {
	return &Permissions{Mode: mode, Allow: allow, Deny: deny}
}

// Check evaluates one tool call. perm is the tool's category
// (read|write|bash|web|none), root the project root.
func (p *Permissions) Check(root, tool, perm string, args map[string]any) Decision {
	command, _ := args["command"].(string)

	if p.matches(p.Deny, tool, args) {
		return Decision{Deny, fmt.Sprintf("blocked by a deny rule for %s", tool)}
	}
	if perm == "bash" && security.IsCatastrophic(command) {
		return Decision{Deny, "refused — catastrophic command, blocked in every mode"}
	}
	if p.Mode == Yolo {
		return Decision{Allow, ""}
	}
	if p.Mode == Plan {
		if perm == "write" || perm == "bash" || perm == "web" {
			return Decision{Deny, PlanNotice}
		}
		return Decision{Allow, ""}
	}
	if p.matches(p.Allow, tool, args) {
		return Decision{Allow, "allow rule"}
	}
	if p.Mode == AcceptEdits && perm == "write" {
		return Decision{Allow, "acceptEdits"}
	}
	switch perm {
	case "read", "none":
		return Decision{Allow, ""}
	case "bash":
		if security.IsReadOnly(root, command) {
			return Decision{Allow, "read-only command"}
		}
		return Decision{Ask, ""}
	default: // write, web
		return Decision{Ask, ""}
	}
}

// AllowSession appends a session-scoped allow rule.
func (p *Permissions) AllowSession(rule string) {
	for _, r := range p.Allow {
		if r == rule {
			return
		}
	}
	p.Allow = append(p.Allow, rule)
}

var aliases = map[string]string{
	"edit": "edit_file", "write": "write_file", "read": "read_file",
	"webfetch": "web_fetch", "websearch": "web_search",
}

func canonical(name string) string {
	n := strings.ToLower(name)
	if a, ok := aliases[n]; ok {
		return a
	}
	return n
}

// matches evaluates rules like `bash(git *)`, `edit_file(src/*)`, `web_fetch`.
func (p *Permissions) matches(rules []string, tool string, args map[string]any) bool {
	for _, rule := range rules {
		if i := strings.IndexByte(rule, '('); i > 0 && strings.HasSuffix(rule, ")") {
			name, pattern := rule[:i], rule[i+1:len(rule)-1]
			if canonical(name) != tool {
				continue
			}
			switch tool {
			case "bash":
				cmd, _ := args["command"].(string)
				if globLike(pattern, strings.TrimSpace(cmd)) {
					return true
				}
			case "write_file", "edit_file":
				path, _ := args["path"].(string)
				if globLike(pattern, path) {
					return true
				}
			default:
				return true
			}
		} else if canonical(rule) == tool {
			return true
		}
	}
	return false
}

// globLike does shell-style matching where * spans any characters.
func globLike(pattern, s string) bool {
	var b strings.Builder
	b.WriteString("^")
	for _, r := range pattern {
		switch r {
		case '*':
			b.WriteString(".*")
		case '?':
			b.WriteString(".")
		default:
			b.WriteString(regexp.QuoteMeta(string(r)))
		}
	}
	b.WriteString("$")
	re, err := regexp.Compile(b.String())
	return err == nil && re.MatchString(s)
}
