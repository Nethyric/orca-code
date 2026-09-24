// Package session persists conversations as JSONL under ~/.orca/sessions,
// one file per session, one JSON object per line.
package session

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

type Entry struct {
	Time time.Time `json:"time"`
	Role string    `json:"role"`
	Text string    `json:"text"`
}

type Writer struct {
	path string
}

// New creates sessions/<timestamp>.jsonl inside dir (created 0700).
func New(dir string) (*Writer, error) {
	sd := filepath.Join(dir, "sessions")
	if err := os.MkdirAll(sd, 0o700); err != nil {
		return nil, err
	}
	name := time.Now().Format("20060102-150405") + ".jsonl"
	return &Writer{path: filepath.Join(sd, name)}, nil
}

func (w *Writer) Path() string { return w.path }

// Append writes one entry; errors are swallowed (logging must never break
// the session).
func (w *Writer) Append(role, text string) {
	if w == nil || text == "" {
		return
	}
	f, err := os.OpenFile(w.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer f.Close()
	line, err := json.Marshal(Entry{Time: time.Now().UTC(), Role: role, Text: text})
	if err != nil {
		return
	}
	f.Write(append(line, '\n'))
}

// Read loads all entries of a session file (used by tests and future /resume).
func Read(path string) ([]Entry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var out []Entry
	for _, line := range splitLines(data) {
		if len(line) == 0 {
			continue
		}
		var e Entry
		if json.Unmarshal(line, &e) == nil {
			out = append(out, e)
		}
	}
	return out, nil
}

func splitLines(data []byte) [][]byte {
	var lines [][]byte
	start := 0
	for i, b := range data {
		if b == '\n' {
			lines = append(lines, data[start:i])
			start = i + 1
		}
	}
	if start < len(data) {
		lines = append(lines, data[start:])
	}
	return lines
}
