package provider

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Nethyric/orca/internal/config"
)

func sse(w http.ResponseWriter, frames ...string) {
	w.Header().Set("Content-Type", "text/event-stream")
	for _, f := range frames {
		fmt.Fprintf(w, "data: %s\n\n", f)
	}
}

func TestOpenAIStreamTextAndTools(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/chat/completions") {
			t.Errorf("bad path %s", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer sk-test" {
			t.Errorf("auth header = %q", got)
		}
		sse(w,
			`{"choices":[{"delta":{"content":"Hel"}}]}`,
			`{"choices":[{"delta":{"content":"lo"}}]}`,
			`{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read_file","arguments":"{\"pa"}}]}}]}`,
			`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\":\"x.go\"}"}}]}},{"delta":{}}]}`,
			`{"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":10,"completion_tokens":7}}`,
			"[DONE]",
		)
	}))
	defer srv.Close()

	p := &OpenAI{Settings: config.ProviderSettings{Name: "openai", Kind: "openai", BaseURL: srv.URL, APIKey: "sk-test", Model: "gpt-test"}, Client: srv.Client()}
	var streamed string
	resp, err := p.Complete(context.Background(), Request{System: "s", Messages: []Message{{Role: "user", Content: []Block{TextBlock("hi")}}}}, func(d string) { streamed += d })
	if err != nil {
		t.Fatal(err)
	}
	if streamed != "Hello" || resp.Text() != "Hello" {
		t.Errorf("text = %q / %q", streamed, resp.Text())
	}
	uses := resp.ToolUses()
	if len(uses) != 1 || uses[0].Name != "read_file" || uses[0].Input["path"] != "x.go" || uses[0].ID != "c1" {
		t.Errorf("tool uses = %+v", uses)
	}
	if resp.Usage.In != 10 || resp.Usage.Out != 7 {
		t.Errorf("usage = %+v", resp.Usage)
	}
	if resp.StopReason != "tool_use" {
		t.Errorf("stop = %q", resp.StopReason)
	}
}

func TestAnthropicStream(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-api-key") != "sk-ant" || r.Header.Get("anthropic-version") == "" {
			t.Error("missing anthropic headers")
		}
		sse(w,
			`{"type":"message_start","message":{"usage":{"input_tokens":21}}}`,
			`{"type":"content_block_start","index":0,"content_block":{"type":"text"}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi "}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"there"}}`,
			`{"type":"content_block_stop","index":0}`,
			`{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu1","name":"bash"}}`,
			`{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"command\":"}}`,
			`{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\"ls\"}"}}`,
			`{"type":"content_block_stop","index":1}`,
			`{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":9}}`,
			`{"type":"message_stop"}`,
		)
	}))
	defer srv.Close()

	p := &Anthropic{Settings: config.ProviderSettings{Name: "anthropic", Kind: "anthropic", BaseURL: srv.URL, APIKey: "sk-ant", Model: "claude-test"}, Client: srv.Client()}
	resp, err := p.Complete(context.Background(), Request{Messages: []Message{{Role: "user", Content: []Block{TextBlock("hi")}}}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Text() != "Hi there" {
		t.Errorf("text = %q", resp.Text())
	}
	uses := resp.ToolUses()
	if len(uses) != 1 || uses[0].Name != "bash" || uses[0].Input["command"] != "ls" {
		t.Errorf("uses = %+v", uses)
	}
	if resp.Usage.In != 21 || resp.Usage.Out != 9 || resp.StopReason != "tool_use" {
		t.Errorf("usage/stop = %+v %q", resp.Usage, resp.StopReason)
	}
}

func TestRetryOn500ThenSuccess(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if atomic.AddInt32(&calls, 1) == 1 {
			w.Header().Set("Retry-After", "1")
			http.Error(w, `{"error":{"message":"overloaded"}}`, 500)
			return
		}
		sse(w, `{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}`, "[DONE]")
	}))
	defer srv.Close()

	p := &OpenAI{Settings: config.ProviderSettings{BaseURL: srv.URL, Model: "m", Name: "test"}, Client: srv.Client()}
	resp, err := p.Complete(context.Background(), Request{Messages: []Message{{Role: "user", Content: []Block{TextBlock("x")}}}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Text() != "ok" || atomic.LoadInt32(&calls) != 2 {
		t.Errorf("text=%q calls=%d", resp.Text(), calls)
	}
}

// A 400 with "timeout" in the body must NOT be retried (Python bug: body sniffing).
func TestNoRetryOn400(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		http.Error(w, `{"error":{"message":"failed to read body: i/o timeout"}}`, 400)
	}))
	defer srv.Close()

	p := &OpenAI{Settings: config.ProviderSettings{BaseURL: srv.URL, Model: "m", Name: "test"}, Client: srv.Client()}
	_, err := p.Complete(context.Background(), Request{Messages: []Message{{Role: "user", Content: []Block{TextBlock("x")}}}}, nil)
	if err == nil || !strings.Contains(err.Error(), "HTTP 400") {
		t.Fatalf("want HTTP 400 error, got %v", err)
	}
	if atomic.LoadInt32(&calls) != 1 {
		t.Errorf("400 was retried %d times — must be exactly 1 call", calls)
	}
}

func TestToOpenAIMessagesPreservesErrors(t *testing.T) {
	msgs := toOpenAIMessages("sys", []Message{
		{Role: "assistant", Content: []Block{{Type: "tool_use", ID: "t1", Name: "bash", Input: map[string]any{"command": "ls"}}}},
		{Role: "user", Content: []Block{ToolResultBlock("t1", "boom", true)}},
	})
	found := false
	for _, m := range msgs {
		if m["role"] == "tool" {
			found = true
			if c, _ := m["content"].(string); !strings.HasPrefix(c, "ERROR:") {
				t.Errorf("tool error flag lost: %v", m)
			}
		}
	}
	if !found {
		t.Fatal("tool message missing")
	}
}
