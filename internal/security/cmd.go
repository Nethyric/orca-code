package security

import (
	"regexp"
	"strings"
)

// shellMeta matches any character that can chain, substitute, redirect,
// expand, quote or glob. A command containing one is NEVER auto-approved —
// it always goes to the user. This closes the classic bypasses:
//
//	git difftool -y -x "evil"   → quotes present → ask
//	ls; rm -rf ~                → ';' present    → ask
//	cat $(secret)               → '$' present    → ask
var shellMeta = regexp.MustCompile("[|&;<>()$`\\\\\"'\n\r*?\\[\\]{}!#~=]")

// SplitSimple splits a metacharacter-free command into argv. ok is false when
// the command contains any shell metacharacter, quote or expansion.
func SplitSimple(cmd string) (argv []string, ok bool) {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" || shellMeta.MatchString(cmd) {
		return nil, false
	}
	return strings.Fields(cmd), true
}

type argvCheck func(root string, args []string) bool

func noArgs(_ string, args []string) bool { return len(args) == 0 }

// pathsInRoot returns a checker that rejects every flag not in allowedFlags
// and requires every non-flag argument to resolve INSIDE the project root.
// This is what stops `cat ~/.ssh/id_rsa` or `head /etc/shadow` from being
// auto-approved.
func pathsInRoot(allowedFlags map[string]bool) argvCheck {
	return func(root string, args []string) bool {
		for _, a := range args {
			if strings.HasPrefix(a, "-") {
				if allowedFlags == nil || !allowedFlags[a] {
					return false
				}
				continue
			}
			if _, inside := ResolveInRoot(root, a); !inside {
				return false
			}
		}
		return true
	}
}

var gitSafeSub = map[string]bool{
	"status": true, "diff": true, "log": true, "show": true,
	"branch": true, "remote": true, "tag": true,
}

// Flag allowlist for read-only git subcommands. Everything else — including
// --output, --ext-diff, -x, -c and any pager tricks — falls through to "ask".
var gitSafeFlags = map[string]bool{
	"--stat": true, "--oneline": true, "--name-only": true, "--name-status": true,
	"--cached": true, "--staged": true, "-p": true, "--no-color": true,
	"--graph": true, "--all": true, "-v": true, "--short": true, "-s": true,
	"--porcelain": true, "--decorate": true,
}

func gitReadOnly(root string, args []string) bool {
	if len(args) == 0 {
		return false
	}
	if !gitSafeSub[args[0]] {
		return false // difftool, push, checkout, config … → ask the user
	}
	for _, a := range args[1:] {
		if strings.HasPrefix(a, "-") && !gitSafeFlags[a] {
			return false
		}
		if !strings.HasPrefix(a, "-") {
			if _, inside := ResolveInRoot(root, a); !inside {
				return false
			}
		}
	}
	return true
}

var versionOnly = func(root string, args []string) bool {
	return len(args) == 1 && (args[0] == "version" || args[0] == "--version")
}

var readOnlyCommands = map[string]argvCheck{
	"pwd":    noArgs,
	"whoami": noArgs,
	"date":   noArgs,
	"uname":  pathsInRoot(map[string]bool{"-a": true, "-r": true, "-m": true, "-s": true}),
	"ls":     pathsInRoot(map[string]bool{"-l": true, "-a": true, "-la": true, "-al": true, "-lh": true, "-lah": true, "-R": true, "-1": true}),
	"cat":    pathsInRoot(map[string]bool{"-n": true}),
	"head":   pathsInRoot(map[string]bool{"-n": true, "-c": true}),
	"tail":   pathsInRoot(map[string]bool{"-n": true, "-c": true}),
	"wc":     pathsInRoot(map[string]bool{"-l": true, "-c": true, "-w": true}),
	"file":   pathsInRoot(nil),
	"which":  pathsInRoot(nil),
	"grep":   pathsInRoot(map[string]bool{"-r": true, "-R": true, "-n": true, "-i": true, "-l": true, "-c": true, "-v": true, "-rn": true, "-in": true, "-rni": true}),
	"rg":     pathsInRoot(map[string]bool{"-n": true, "-i": true, "-l": true, "-c": true, "--no-heading": true}),
	"git":    gitReadOnly,
	"go":     versionOnly,
	"node":   versionOnly,
	"python": versionOnly, "python3": versionOnly,
	"npm": versionOnly, "cargo": versionOnly, "rustc": versionOnly,
}

// IsReadOnly reports whether cmd is a simple, metacharacter-free command that
// is known to be read-only AND whose path arguments stay inside root. Only
// such commands may skip the permission prompt in default mode.
func IsReadOnly(root, cmd string) bool {
	argv, ok := SplitSimple(cmd)
	if !ok || len(argv) == 0 {
		return false
	}
	check, known := readOnlyCommands[argv[0]]
	if !known {
		return false
	}
	return check(root, argv[1:])
}

// catastrophic is a best-effort BACKSTOP, not the security boundary. The real
// protections are default-ask permissions, path confinement and the
// metacharacter gate above. These patterns exist only to refuse the most
// obviously destructive commands even in yolo mode.
var catastrophic = []*regexp.Regexp{
	regexp.MustCompile(`(^|[;&|]\s*)(sudo\s+)?rm\s+(-\w+\s+)*(/|/\*|~|~/\*|\$HOME)(\s|$)`),
	regexp.MustCompile(`\bmkfs(\.\w+)?\b`),
	regexp.MustCompile(`\bdd\b[^\n]*\bof=/dev/`),
	regexp.MustCompile(`:\(\)\s*\{[^}]*\}\s*;\s*:`),
	regexp.MustCompile(`>\s*/dev/(sd|nvme|hd)`),
	regexp.MustCompile(`\bchmod\s+-R\s+777\s+/(\s|$)`),
	regexp.MustCompile(`(?i)\b(del|rd)\s+/s\b`), // Windows
}

// IsCatastrophic reports whether cmd matches a known-destructive pattern.
func IsCatastrophic(cmd string) bool {
	for _, re := range catastrophic {
		if re.MatchString(cmd) {
			return true
		}
	}
	return false
}
