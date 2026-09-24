package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"

	"github.com/Nethyric/orca/internal/config"
)

// OpenAI speaks the Chat Completions wire format (OpenAI, OpenRouter, Groq,
// DeepSeek, Mistral, Together, Ollama, LM Studio, …).
type OpenAI struct {
	Settings config.ProviderSettings
	Client   *http.Client
}

func (p *OpenAI) Label() string { return p.Settings.Name + "/" + p.Settings.Model }

func (p *OpenAI) Complete(ctx context.Context, req Request, onText func(string)) (*Response, error) {
	payload := map[string]any{
		"model":          p.Settings.Model,
		"messages":       toOpenAIMessages(req.System, req.Messages),
		"stream":         true,
		"stream_options": map[string]any{"include_usage": true},
	}
	if req.MaxTokens > 0 {
		payload["max_tokens"] = req.MaxTokens
	}
	if len(req.Tools) > 0 {
		tools := make([]map[string]any, len(req.Tools))
		for i, t := range req.Tools {
			tools[i] = map[string]any{"type": "function", "function": map[string]any{
				"name": t.Name, "description": t.Description, "parameters": t.InputSchema,
			}}
		}
		payload["tools"] = tools
	}
	headers := map[string]string{}
	if p.Settings.APIKey != "" {
		headers["Authorization"] = "Bearer " + p.Settings.APIKey
	}
	body, err := doStream(ctx, p.Client, p.Settings.BaseURL+"/chat/completions", headers, payload)
	if err != nil {
		return nil, err
	}
	defer body.Close()

	type toolAcc struct {
		id, name, args string
	}
	acc := map[int]*toolAcc{}
	resp := &Response{}
	var text string

	err = readSSE(body, func(data string) error {
		var chunk struct {
			Choices []struct {
				Delta struct {
					Content   string `json:"content"`
					ToolCalls []struct {
						Index    int    `json:"index"`
						ID       string `json:"id"`
						Function struct {
							Name      string `json:"name"`
							Arguments string `json:"arguments"`
						} `json:"function"`
					} `json:"tool_calls"`
				} `json:"delta"`
				FinishReason string `json:"finish_reason"`
			} `json:"choices"`
			Usage *struct {
				PromptTokens     int `json:"prompt_tokens"`
				CompletionTokens int `json:"completion_tokens"`
			} `json:"usage"`
			Error *struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			return nil // tolerate unknown frames
		}
		if chunk.Error != nil && chunk.Error.Message != "" {
			return fmt.Errorf("provider error: %s", chunk.Error.Message)
		}
		if chunk.Usage != nil {
			resp.Usage.In = chunk.Usage.PromptTokens
			resp.Usage.Out = chunk.Usage.CompletionTokens
		}
		if len(chunk.Choices) == 0 {
			return nil
		}
		ch := chunk.Choices[0]
		if ch.Delta.Content != "" {
			text += ch.Delta.Content
			if onText != nil {
				onText(ch.Delta.Content)
			}
		}
		for _, tc := range ch.Delta.ToolCalls {
			a, ok := acc[tc.Index]
			if !ok {
				a = &toolAcc{}
				acc[tc.Index] = a
			}
			if tc.ID != "" {
				a.id = tc.ID
			}
			if tc.Function.Name != "" {
				a.name = tc.Function.Name
			}
			a.args += tc.Function.Arguments
		}
		if ch.FinishReason != "" {
			resp.StopReason = ch.FinishReason
		}
		return nil
	})
	if err != nil {
		return nil, err
	}

	if text != "" {
		resp.Blocks = append(resp.Blocks, TextBlock(text))
	}
	idxs := make([]int, 0, len(acc))
	for i := range acc {
		idxs = append(idxs, i)
	}
	sort.Ints(idxs)
	for n, i := range idxs {
		a := acc[i]
		input := map[string]any{}
		if a.args != "" {
			if err := json.Unmarshal([]byte(a.args), &input); err != nil {
				input = map[string]any{"_malformed_json": a.args}
			}
		}
		id := a.id
		if id == "" {
			id = fmt.Sprintf("call_%d", n)
		}
		resp.Blocks = append(resp.Blocks, Block{Type: "tool_use", ID: id, Name: a.name, Input: input})
	}
	if resp.StopReason == "tool_calls" {
		resp.StopReason = "tool_use"
	}
	return resp, nil
}

// toOpenAIMessages converts the canonical format to Chat Completions turns.
// tool_result error state is preserved by prefixing the content — the wire
// format has no error flag (the Python version silently dropped it).
func toOpenAIMessages(system string, messages []Message) []map[string]any {
	out := []map[string]any{{"role": "system", "content": system}}
	for _, msg := range messages {
		if msg.Role == "assistant" {
			var text string
			var calls []map[string]any
			for _, b := range msg.Content {
				switch b.Type {
				case "text":
					text += b.Text
				case "tool_use":
					args, _ := json.Marshal(b.Input)
					calls = append(calls, map[string]any{
						"id": b.ID, "type": "function",
						"function": map[string]any{"name": b.Name, "arguments": string(args)},
					})
				}
			}
			entry := map[string]any{"role": "assistant"}
			if text != "" {
				entry["content"] = text
			} else {
				entry["content"] = nil
			}
			if len(calls) > 0 {
				entry["tool_calls"] = calls
			}
			if text != "" || len(calls) > 0 {
				out = append(out, entry)
			}
			continue
		}
		var texts string
		for _, b := range msg.Content {
			switch b.Type {
			case "tool_result":
				content := b.Content
				if b.IsError {
					content = "ERROR: " + content
				}
				out = append(out, map[string]any{"role": "tool", "tool_call_id": b.ToolUseID, "content": content})
			case "text":
				if texts != "" {
					texts += "\n"
				}
				texts += b.Text
			}
		}
		if texts != "" {
			out = append(out, map[string]any{"role": "user", "content": texts})
		}
	}
	return out
}
