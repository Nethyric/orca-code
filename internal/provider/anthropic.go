package provider

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/Nethyric/orca/internal/config"
)

// Anthropic speaks the native Messages API with SSE streaming.
type Anthropic struct {
	Settings config.ProviderSettings
	Client   *http.Client
}

func (p *Anthropic) Label() string { return p.Settings.Name + "/" + p.Settings.Model }

func (p *Anthropic) Complete(ctx context.Context, req Request, onText func(string)) (*Response, error) {
	maxTokens := req.MaxTokens
	if maxTokens <= 0 {
		maxTokens = 8192
	}
	msgs := make([]map[string]any, 0, len(req.Messages))
	for _, m := range req.Messages {
		blocks := make([]map[string]any, 0, len(m.Content))
		for _, b := range m.Content {
			switch b.Type {
			case "text":
				blocks = append(blocks, map[string]any{"type": "text", "text": b.Text})
			case "tool_use":
				input := b.Input
				if input == nil {
					input = map[string]any{}
				}
				blocks = append(blocks, map[string]any{"type": "tool_use", "id": b.ID, "name": b.Name, "input": input})
			case "tool_result":
				blk := map[string]any{"type": "tool_result", "tool_use_id": b.ToolUseID, "content": b.Content}
				if b.IsError {
					blk["is_error"] = true
				}
				blocks = append(blocks, blk)
			}
		}
		msgs = append(msgs, map[string]any{"role": m.Role, "content": blocks})
	}
	payload := map[string]any{
		"model": p.Settings.Model, "max_tokens": maxTokens,
		"system": req.System, "messages": msgs, "stream": true,
	}
	if len(req.Tools) > 0 {
		tools := make([]map[string]any, len(req.Tools))
		for i, t := range req.Tools {
			tools[i] = map[string]any{"name": t.Name, "description": t.Description, "input_schema": t.InputSchema}
		}
		payload["tools"] = tools
	}
	headers := map[string]string{
		"x-api-key":         p.Settings.APIKey,
		"anthropic-version": "2023-06-01",
	}
	body, err := doStream(ctx, p.Client, p.Settings.BaseURL+"/v1/messages", headers, payload)
	if err != nil {
		return nil, err
	}
	defer body.Close()

	resp := &Response{}
	type blockState struct {
		typ, id, name, text, partialJSON string
	}
	open := map[int]*blockState{}

	err = readSSE(body, func(data string) error {
		var ev struct {
			Type    string `json:"type"`
			Index   int    `json:"index"`
			Message *struct {
				Usage struct {
					InputTokens int `json:"input_tokens"`
				} `json:"usage"`
			} `json:"message"`
			ContentBlock *struct {
				Type string `json:"type"`
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"content_block"`
			Delta *struct {
				Type        string `json:"type"`
				Text        string `json:"text"`
				PartialJSON string `json:"partial_json"`
				StopReason  string `json:"stop_reason"`
			} `json:"delta"`
			Usage *struct {
				OutputTokens int `json:"output_tokens"`
			} `json:"usage"`
			Error *struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := json.Unmarshal([]byte(data), &ev); err != nil {
			return nil
		}
		switch ev.Type {
		case "message_start":
			if ev.Message != nil {
				resp.Usage.In = ev.Message.Usage.InputTokens
			}
		case "content_block_start":
			if ev.ContentBlock != nil {
				open[ev.Index] = &blockState{typ: ev.ContentBlock.Type, id: ev.ContentBlock.ID, name: ev.ContentBlock.Name}
			}
		case "content_block_delta":
			st := open[ev.Index]
			if st == nil || ev.Delta == nil {
				return nil
			}
			switch ev.Delta.Type {
			case "text_delta":
				st.text += ev.Delta.Text
				if onText != nil {
					onText(ev.Delta.Text)
				}
			case "input_json_delta":
				st.partialJSON += ev.Delta.PartialJSON
			}
		case "content_block_stop":
			st := open[ev.Index]
			if st == nil {
				return nil
			}
			switch st.typ {
			case "text":
				resp.Blocks = append(resp.Blocks, TextBlock(st.text))
			case "tool_use":
				input := map[string]any{}
				if st.partialJSON != "" {
					if err := json.Unmarshal([]byte(st.partialJSON), &input); err != nil {
						input = map[string]any{"_malformed_json": st.partialJSON}
					}
				}
				resp.Blocks = append(resp.Blocks, Block{Type: "tool_use", ID: st.id, Name: st.name, Input: input})
			}
			delete(open, ev.Index)
		case "message_delta":
			if ev.Delta != nil && ev.Delta.StopReason != "" {
				resp.StopReason = ev.Delta.StopReason
			}
			if ev.Usage != nil {
				resp.Usage.Out = ev.Usage.OutputTokens
			}
		case "error":
			if ev.Error != nil {
				return &providerErr{ev.Error.Message}
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return resp, nil
}

type providerErr struct{ msg string }

func (e *providerErr) Error() string { return "provider error: " + e.msg }
