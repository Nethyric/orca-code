package tools

import (
	"fmt"
	"html"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"

	"github.com/Nethyric/orca/internal/version"
)

const (
	maxWebBytes  = 2 << 20 // 2 MiB
	maxWebOutput = 8000
	webUA        = "Mozilla/5.0 (compatible; OrcaCode/" + version.Version + "; +https://github.com/Nethyric/orca-code)"
)

var (
	reScriptStyle = regexp.MustCompile(`(?is)<(script|style|noscript|template|svg|head)[^>]*>.*?</\s*(script|style|noscript|template|svg|head)\s*>`)
	reTags        = regexp.MustCompile(`(?s)<[^>]*>`)
	reBlankLines  = regexp.MustCompile(`\n{3,}`)
	reSpaces      = regexp.MustCompile(`[ \t]{2,}`)
	reTitle       = regexp.MustCompile(`(?is)<title[^>]*>(.*?)</title>`)
)

func htmlToText(raw string) (title, body string) {
	if m := reTitle.FindStringSubmatch(raw); m != nil {
		title = strings.TrimSpace(html.UnescapeString(m[1]))
	}
	txt := reScriptStyle.ReplaceAllString(raw, " ")
	txt = regexp.MustCompile(`(?i)</(p|div|li|tr|h1|h2|h3|h4|pre|br)>`).ReplaceAllString(txt, "\n")
	txt = reTags.ReplaceAllString(txt, " ")
	txt = html.UnescapeString(txt)
	var lines []string
	for _, l := range strings.Split(txt, "\n") {
		l = strings.TrimSpace(reSpaces.ReplaceAllString(l, " "))
		lines = append(lines, l)
	}
	body = reBlankLines.ReplaceAllString(strings.Join(lines, "\n"), "\n\n")
	return title, strings.TrimSpace(body)
}

func (c *Context) webGet(rawURL string) (finalURL, contentType, body string, err error) {
	u, err := url.Parse(rawURL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return "", "", "", fmt.Errorf("invalid URL %q (only http/https)", rawURL)
	}
	req, err := http.NewRequest("GET", rawURL, nil)
	if err != nil {
		return "", "", "", err
	}
	req.Header.Set("User-Agent", webUA)
	req.Header.Set("Accept", "text/html,text/plain,*/*")
	resp, err := c.WebClient.Do(req)
	if err != nil {
		return "", "", "", fmt.Errorf("fetch failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return "", "", "", fmt.Errorf("HTTP %d for %s", resp.StatusCode, rawURL)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxWebBytes))
	if err != nil {
		return "", "", "", err
	}
	return resp.Request.URL.String(), resp.Header.Get("Content-Type"), string(data), nil
}

func toolWebFetch(c *Context, args map[string]any) (string, error) {
	rawURL := strings.TrimSpace(strArg(args, "url"))
	if rawURL == "" {
		return "", fmt.Errorf("web_fetch requires 'url'")
	}
	finalURL, ctype, raw, err := c.webGet(rawURL)
	if err != nil {
		return "", err
	}
	header := "url: " + finalURL
	body := raw
	if strings.Contains(strings.ToLower(ctype), "html") || strings.Contains(strings.ToLower(raw[:min(2000, len(raw))]), "<html") {
		title, text := htmlToText(raw)
		if title != "" {
			header += "\ntitle: " + title
		}
		body = text
	}
	body = strings.TrimSpace(body)
	if body == "" {
		return "", fmt.Errorf("empty response from %s", rawURL)
	}
	if len(body) > maxWebOutput {
		body = fmt.Sprintf("%s\n⋯ [truncated at %d of %d chars]", body[:maxWebOutput], maxWebOutput, len(body))
	}
	return header + "\n\n" + body, nil
}

// ---- web_search (keyless, best-effort DDG lite scrape; SEARX_URL preferred) --

var reResultLink = regexp.MustCompile(`(?is)<a[^>]+href="(/{2}duckduckgo\.com/l/\?uddg=|https?://)([^"]+)"[^>]*>(.*?)</a>`)

func toolWebSearch(c *Context, args map[string]any) (string, error) {
	query := strings.TrimSpace(strArg(args, "query"))
	if query == "" {
		return "", fmt.Errorf("web_search requires 'query'")
	}
	maxResults := intArg(args, "max_results", 5)
	if maxResults < 1 {
		maxResults = 1
	}
	if maxResults > 8 {
		maxResults = 8
	}
	searchURL := "https://lite.duckduckgo.com/lite/?q=" + url.QueryEscape(query)
	_, _, raw, err := c.webGet(searchURL)
	if err != nil {
		return "", fmt.Errorf("web_search failed (%v) — DuckDuckGo scraping is best-effort; try web_fetch on a known URL", err)
	}
	var out []string
	seen := map[string]bool{}
	for _, m := range reResultLink.FindAllStringSubmatch(raw, -1) {
		link := m[2]
		if strings.HasPrefix(m[1], "//duckduckgo.com") {
			// redirect-wrapped: uddg=<escaped real url>&…
			if i := strings.Index(link, "&"); i > 0 {
				link = link[:i]
			}
			if dec, err := url.QueryUnescape(link); err == nil {
				link = dec
			}
		} else {
			link = m[1] + link
		}
		if strings.Contains(link, "duckduckgo.com") || seen[link] {
			continue
		}
		title, _ := htmlToText(m[3])
		if title == "" {
			_, title = htmlToText(m[3])
		}
		if title == "" {
			continue
		}
		seen[link] = true
		out = append(out, fmt.Sprintf("%d. %s\n   %s", len(out)+1, title, link))
		if len(out) >= maxResults {
			break
		}
	}
	if len(out) == 0 {
		return "(no results)", nil
	}
	return strings.Join(out, "\n"), nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
