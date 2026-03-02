# HTTP Tool

## What it does

The HTTP tool detects transparent proxies and inspects HTTP response headers for security issues. It helps identify if your network traffic is being intercepted by middleboxes (corporate proxies, ISP proxies, captive portals) and checks for suspicious headers that indicate interception or content modification.

Key capabilities:

- **Proxy detection** — Looks for proxy-related headers (Via, X-Forwarded-For, X-Cache, etc.) in responses
- **Header inspection** — Displays all response headers from a URL for analysis
- **Content integrity checking** — Compares response body against a known hash to detect ISP/proxy injection
- **Redirect chain analysis** — Follows redirects automatically and reports final status

## Quick start

Check for transparent proxies using default URLs:

```bash
netglance http check
```

Probe a specific URL:

```bash
netglance http check https://example.com
```

Inspect all response headers from a URL:

```bash
netglance http headers https://example.com
```

Set a custom timeout (e.g., 10 seconds):

```bash
netglance http check --timeout 10 https://example.com
```

## Commands

### `netglance http check [URL]`

Checks a URL (or default URLs if omitted) for transparent proxy indicators.

**Arguments:**

- `URL` (optional) — The URL to check. If omitted, checks built-in default URLs.

**Options:**

- `--timeout, -t` — Request timeout in seconds (default: 5.0)

**Output:** A table with columns for URL, HTTP status code, proxy detection result (YES/NO), suspicious headers found, and details.

### `netglance http headers URL`

Displays all HTTP response headers returned by a URL.

**Arguments:**

- `URL` (required) — The URL to inspect

**Options:**

- `--timeout, -t` — Request timeout in seconds (default: 5.0)

**Output:** A formatted table of all response headers. Proxy-related headers are highlighted in red.

## Understanding the output

### Proxy detection result

The tool checks for seven proxy-related headers:

- **Via** — Indicates the request passed through one or more proxies
- **X-Forwarded-For** — Contains the client's original IP, added by proxies
- **X-Forwarded-Host** — Original requested host, added by proxies
- **X-Cache** — Cache status from a proxy or CDN
- **X-Proxy-ID** — Proxy identifier
- **X-Forwarded-Host** — Original host header before proxy modification

If any of these headers appear in the response, the tool reports "YES" for proxy detection. This indicates your request passed through a transparent proxy.

### Suspicious headers

The table shows which proxy headers were found and their values. A value like `X-Forwarded-For: 203.0.113.42` means the proxy logged your original IP.

### Status code

The HTTP response status code (e.g., 200 for success, 403 for forbidden, 502 for proxy error).

### Details section

- "One or more proxy-related headers found in the response." — Indicates transparent proxy detection
- Individual header listings with their values
- "[dim]clean[/dim]" — No suspicious headers detected

## Related concepts

- **[TLS Tool](./tls.md)** — Detect HTTPS interception by checking certificate validity. A proxy that intercepts HTTPS will use its own certificate.
- **[DNS Tool](./dns.md)** — Detect DNS hijacking or redirect injection. Proxies sometimes modify DNS responses.
- **[Traffic Tool](./traffic.md)** — Monitor bandwidth; combine with HTTP checks to detect traffic shaping by proxies.

## Troubleshooting

**False positives from CDNs**

CDNs like Cloudflare add Via and X-Cache headers as part of normal operation. These aren't necessarily security concerns. If you trust your CDN, you can ignore these flags.

**Expected corporate proxy headers**

If you're on a corporate network with an approved proxy, seeing proxy headers is expected and not a security issue. Use the HTTP tool to verify the proxy identity matches your organization's policy.

**Timeouts on slow connections**

If requests timeout, increase the `--timeout` value:

```bash
netglance http check --timeout 15 https://slow-site.example.com
```

**Captive portal detection**

If the tool reports redirects or unusual status codes (302, 307), your network may have a captive portal. The HTTP tool will follow redirects automatically but won't bypass authentication.

**Content injection detection (advanced)**

To check if a proxy is injecting content (e.g., ads or tracking scripts), you can manually compare response bodies:

1. Fetch the URL twice and compare outputs
2. Use an external tool to generate the expected hash
3. Cross-check against a known clean response from a VPN or different network
