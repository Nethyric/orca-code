// Package provider implements streaming LLM clients for the Anthropic
// Messages API and the OpenAI Chat Completions API (spoken by OpenRouter,
// Groq, DeepSeek, Mistral, Ollama and most gateways).
//
// Retry policy (fixing the Python version's bugs): a request is retried at
// most 3 times, ONLY on transport errors or genuinely retryable statuses
// (408/429/5xx/529) — never by sniffing keywords in 400 bodies. Retry-After
// is honoured, backoff is capped-exponential with jitter.
package provider

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Nethyric/orca/internal/config"
)

// ---- canonical message format (Anthropic-shaped) ---------------------------

type Block struct {
	Type      string         `json:"type"`
	Text      string         `json:"text,omitempty"`
	ID        string         `json:"id,omitempty"`
	Name      string         `json:"name,omitempty"`
	Input     map[string]any `json:"input,omitempty"`
	ToolUseID string         `json:"tool_use_id,omitempty"`
	Content   string         `json:"content,omitempty"`
	IsError   bool           `json:"is_error,omitempty"`
}

type Message struct {
	Role    string  `json:"role"`
	Content []Block `json:"content"`
}

func TextBlock(text string) Block { return Block{Type: "text", Text: text} }

func ToolResultBlock(id, content string, isErr bool) Block {
	return Block{Type: "tool_result", ToolUseID: id, Content: content, IsError: isErr}
}

type ToolSpec struct {
	Name        string
	Description string
	InputSchema map[string]any
}

type Request struct {
	System    string
	Messages  []Message
	Tools     []ToolSpec
	MaxTokens int
}

type Usage struct{ In, Out int }

type Response struct {
	Blocks     []Block
	StopReason string
	Usage      Usage
}

// Text returns the concatenated text blocks.
func (r *Response) Text() string {
	var b strings.Builder
	for _, blk := range r.Blocks {
		if blk.Type == "text" {
			b.WriteString(blk.Text)
		}
	}
	return b.String()
}

// ToolUses returns the tool_use blocks in order.
func (r *Response) ToolUses() []Block {
	var out []Block
	for _, blk := range r.Blocks {
		if blk.Type == "tool_use" {
			out = append(out, blk)
		}
	}
	return out
}

// Provider streams one completion; onText receives live text deltas.
type Provider interface {
	Label() string
	Complete(ctx context.Context, req Request, onText func(string)) (*Response, error)
}

// New builds a provider from resolved settings.
func New(s config.ProviderSettings, client *http.Client) (Provider, error) {
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Minute}
	}
	switch s.Kind {
	case "anthropic":
		return &Anthropic{Settings: s, Client: client}, nil
	case "openai":
		return &OpenAI{Settings: s, Client: client}, nil
	}
	return nil, fmt.Errorf("unknown provider kind %q", s.Kind)
}

// ---- shared transport -------------------------------------------------------

var retryableStatus = map[int]bool{408: true, 429: true, 500: true, 502: true, 503: true, 504: true, 529: true}

// doStream POSTs payload and returns the response body for SSE reading.
func doStream(ctx context.Context, client *http.Client, url string, headers map[string]string, payload any) (io.ReadCloser, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	var lastErr error
	for attempt := 1; attempt <= 3; attempt++ {
		req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "text/event-stream")
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := client.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("cannot reach %s: %v", url, err)
			if ctx.Err() != nil {
				return nil, lastErr
			}
			sleepBackoff(attempt, "")
			continue
		}
		if resp.StatusCode == http.StatusOK {
			return resp.Body, nil
		}
		detail := readErrorDetail(resp)
		resp.Body.Close()
		lastErr = fmt.Errorf("HTTP %d: %s", resp.StatusCode, detail)
		if retryableStatus[resp.StatusCode] && attempt < 3 {
			sleepBackoff(attempt, resp.Header.Get("Retry-After"))
			continue
		}
		return nil, lastErr
	}
	return nil, lastErr
}

func sleepBackoff(attempt int, retryAfter string) {
	if s, err := strconv.Atoi(strings.TrimSpace(retryAfter)); err == nil && s > 0 && s <= 60 {
		time.Sleep(time.Duration(s) * time.Second)
		return
	}
	base := 1 << attempt // 2s, 4s, 8s
	if base > 8 {
		base = 8
	}
	time.Sleep(time.Duration(base)*time.Second + time.Duration(rand.Intn(600))*time.Millisecond)
}

func readErrorDetail(resp *http.Response) string {
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	var parsed struct {
		Error struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(raw, &parsed) == nil && parsed.Error.Message != "" {
		return parsed.Error.Message
	}
	s := strings.TrimSpace(string(raw))
	if len(s) > 400 {
		s = s[:400]
	}
	if s == "" {
		s = resp.Status
	}
	return s
}

// readSSE calls fn for every `data:` payload until [DONE] or EOF.
func readSSE(r io.Reader, fn func(data string) error) error {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 8*1024*1024)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(line[5:])
		if data == "" || data == "[DONE]" {
			if data == "[DONE]" {
				return nil
			}
			continue
		}
		if err := fn(data); err != nil {
			return err
		}
	}
	return sc.Err()
}
