package permissions

import "testing"

func dec(t *testing.T, p *Permissions, tool, perm string, args map[string]any) Verdict {
	t.Helper()
	return p.Check(t.TempDir(), tool, perm, args).Verdict
}

func TestDefaultMode(t *testing.T) {
	p := New(Default, nil, nil)
	if v := dec(t, p, "read_file", "read", map[string]any{"path": "x"}); v != Allow {
		t.Errorf("read in default = %v", v)
	}
	if v := dec(t, p, "write_file", "write", map[string]any{"path": "x"}); v != Ask {
		t.Errorf("write in default = %v", v)
	}
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "git status"}); v != Allow {
		t.Errorf("read-only bash = %v", v)
	}
	if v := dec(t, p, "bash", "bash", map[string]any{"command": `git difftool -y -x "evil"`}); v != Ask {
		t.Errorf("difftool bypass must ask, got %v", v)
	}
	if v := dec(t, p, "web_fetch", "web", map[string]any{"url": "https://x"}); v != Ask {
		t.Errorf("web in default = %v", v)
	}
}

func TestPlanModeDeniesWrites(t *testing.T) {
	p := New(Plan, nil, nil)
	for tool, perm := range map[string]string{"write_file": "write", "bash": "bash", "web_fetch": "web"} {
		if v := dec(t, p, tool, perm, map[string]any{"command": "ls"}); v != Deny {
			t.Errorf("%s in plan = %v, want deny", tool, v)
		}
	}
	if v := dec(t, p, "grep", "read", nil); v != Allow {
		t.Errorf("read in plan = %v", v)
	}
}

func TestYoloStillBlocksCatastrophic(t *testing.T) {
	p := New(Yolo, nil, nil)
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "rm -rf /"}); v != Deny {
		t.Errorf("catastrophic in yolo = %v, want deny", v)
	}
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "make build"}); v != Allow {
		t.Errorf("normal bash in yolo = %v", v)
	}
}

func TestRules(t *testing.T) {
	p := New(Default, []string{"bash(git *)", "edit_file(src/*)"}, []string{"bash(git push*)"})
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "git commit -m x"}); v != Allow {
		t.Errorf("allow rule failed: %v", v)
	}
	// deny beats allow
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "git push --force"}); v != Deny {
		t.Errorf("deny rule must beat allow: %v", v)
	}
	if v := dec(t, p, "edit_file", "write", map[string]any{"path": "src/a.go"}); v != Allow {
		t.Errorf("edit rule failed: %v", v)
	}
	if v := dec(t, p, "edit_file", "write", map[string]any{"path": "other/a.go"}); v != Ask {
		t.Errorf("non-matching edit = %v", v)
	}
}

func TestAcceptEdits(t *testing.T) {
	p := New(AcceptEdits, nil, nil)
	if v := dec(t, p, "write_file", "write", map[string]any{"path": "x"}); v != Allow {
		t.Errorf("write in acceptEdits = %v", v)
	}
	if v := dec(t, p, "bash", "bash", map[string]any{"command": "make deploy"}); v != Ask {
		t.Errorf("bash still gated in acceptEdits: %v", v)
	}
}
