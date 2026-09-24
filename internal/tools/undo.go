package tools

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

const maxSnapshotBytes = 10 << 20 // 10 MiB per file

type undoEntry struct {
	turn    int
	path    string
	data    []byte // nil ⇒ file did not exist
	mode    fs.FileMode
	tooBig  bool
	existed bool
}

// UndoStack snapshots files BEFORE the agent overwrites them, grouped by
// agent turn. Snapshots are raw bytes, so binary files are restored intact
// (the Python version corrupted them by round-tripping through text).
type UndoStack struct {
	entries []undoEntry
	turn    int
}

func (u *UndoStack) BeginTurn() { u.turn++ }
func (u *UndoStack) Turn() int  { return u.turn }
func (u *UndoStack) Len() int   { return len(u.entries) }

// Push records the current state of path (may not exist yet).
func (u *UndoStack) Push(path string) {
	e := undoEntry{turn: u.turn, path: path}
	if info, err := os.Stat(path); err == nil && info.Mode().IsRegular() {
		e.existed = true
		e.mode = info.Mode().Perm()
		if info.Size() <= maxSnapshotBytes {
			if data, err := os.ReadFile(path); err == nil {
				e.data = data
			} else {
				e.tooBig = true
			}
		} else {
			e.tooBig = true
		}
	}
	u.entries = append(u.entries, e)
}

// UndoLastTurn reverts every change of the most recent turn (newest first).
func (u *UndoStack) UndoLastTurn() []string {
	if len(u.entries) == 0 {
		return nil
	}
	last := u.entries[len(u.entries)-1].turn
	start := len(u.entries)
	for start > 0 && u.entries[start-1].turn == last {
		start--
	}
	var restored []string
	for i := len(u.entries) - 1; i >= start; i-- {
		e := u.entries[i]
		base := filepath.Base(e.path)
		switch {
		case !e.existed:
			if err := os.Remove(e.path); err == nil {
				restored = append(restored, fmt.Sprintf("deleted %s (was newly created)", base))
			}
		case e.tooBig:
			restored = append(restored, fmt.Sprintf("SKIPPED %s (snapshot exceeded 10MB)", base))
		default:
			_ = os.MkdirAll(filepath.Dir(e.path), 0o755)
			if err := os.WriteFile(e.path, e.data, e.mode); err == nil {
				restored = append(restored, "restored "+base)
			}
		}
	}
	u.entries = u.entries[:start]
	return restored
}
