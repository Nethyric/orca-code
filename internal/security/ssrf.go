package security

import (
	"fmt"
	"net"
	"net/http"
	"syscall"
	"time"
)

// IsForbiddenIP reports whether ip must never be reached by model-driven web
// tools: loopback, RFC1918 private ranges, link-local (which includes the
// cloud metadata endpoint 169.254.169.254), CGNAT, unspecified and multicast
// addresses, plus their IPv6 equivalents.
func IsForbiddenIP(ip net.IP) bool {
	if ip == nil {
		return true
	}
	if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() ||
		ip.IsLinkLocalMulticast() || ip.IsUnspecified() || ip.IsMulticast() {
		return true
	}
	if ip4 := ip.To4(); ip4 != nil {
		if ip4[0] == 100 && ip4[1]&0xc0 == 64 { // 100.64.0.0/10 CGNAT
			return true
		}
		if ip4[0] == 0 { // 0.0.0.0/8
			return true
		}
		if ip4[0] == 192 && ip4[1] == 0 && ip4[2] == 0 { // 192.0.0.0/24
			return true
		}
	}
	return false
}

// SafeHTTPClient returns an http.Client for model-driven web access
// (web_fetch / web_search). The IP check runs at CONNECT time on the already
// resolved address, so DNS rebinding cannot bypass it. Redirects are capped
// and re-validated (scheme + the same connect-time check applies to every
// hop). Provider/API traffic intentionally does NOT use this client, so local
// model servers (Ollama, LM Studio) keep working.
func SafeHTTPClient(timeout time.Duration) *http.Client {
	dialer := &net.Dialer{
		Timeout: 10 * time.Second,
		Control: func(network, address string, _ syscall.RawConn) error {
			host, _, err := net.SplitHostPort(address)
			if err != nil {
				return err
			}
			if ip := net.ParseIP(host); IsForbiddenIP(ip) {
				return fmt.Errorf("blocked: %s is a private/internal address (SSRF protection)", host)
			}
			return nil
		},
	}
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			DialContext:           dialer.DialContext,
			MaxIdleConns:          4,
			TLSHandshakeTimeout:   10 * time.Second,
			ResponseHeaderTimeout: 20 * time.Second,
			DisableKeepAlives:     true,
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return fmt.Errorf("too many redirects (max 5)")
			}
			if req.URL.Scheme != "http" && req.URL.Scheme != "https" {
				return fmt.Errorf("redirect to unsupported scheme %q blocked", req.URL.Scheme)
			}
			return nil
		},
	}
}
