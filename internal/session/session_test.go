package session

import (
	"testing"
)

func TestWriteAndRead(t *testing.T) {
	w, err := New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w.Append("user", "add tests")
	w.Append("assistant", "done ✓")
	w.Append("user", "") // empty → skipped

	entries, err := Read(w.Path())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 {
		t.Fatalf("entries = %d, want 2", len(entries))
	}
	if entries[0].Role != "user" || entries[0].Text != "add tests" {
		t.Errorf("entry 0 = %+v", entries[0])
	}
	if entries[1].Role != "assistant" || entries[1].Text != "done ✓" {
		t.Errorf("entry 1 = %+v", entries[1])
	}
	if entries[0].Time.IsZero() {
		t.Error("timestamp missing")
	}
}

func TestNilWriterSafe(t *testing.T) {
	var w *Writer
	w.Append("user", "must not panic")
}
