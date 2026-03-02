# Security Model

netglance is a local-first tool. It runs on your machine, stores data on your machine, and sends nothing to the cloud. This page explains the security boundaries, authentication options, and what to watch for when exposing services beyond localhost.

## Threat Model

netglance protects against:

- **Malicious websites** exploiting CORS to query your local API and exfiltrate network data
- **Malformed input** attempting command injection through subnet, host, or port parameters
- **Accidental LAN exposure** when binding the API or MCP server to a non-localhost address without auth

netglance does **not** protect against:

- An attacker with shell access to your machine (if they have that, they don't need netglance)
- Nation-state adversaries targeting your home network (use dedicated IDS/IPS hardware)

## Transports and Authentication

| Component | Transport | Default Bind | Auth | Network Exposed? |
|-----------|-----------|-------------|------|------------------|
| MCP server (stdio) | stdin/stdout | N/A | None needed | No — process-local |
| MCP server (HTTP) | Streamable HTTP | 127.0.0.1:8080 | None | Only if you bind 0.0.0.0 |
| REST API | HTTP | 127.0.0.1:8080 | Optional API key | Only if you bind 0.0.0.0 |
| Daemon | None | N/A | None needed | No — no network listener |

### MCP Server (stdio)

The default MCP transport. Your AI client (Claude Desktop, Claude Code, Cursor, etc.) launches netglance as a subprocess and communicates over stdin/stdout. There is no network socket — no other process on the machine or network can reach it. Authentication would be pointless here.

### MCP Server (HTTP)

Used with `netglance mcp serve --transport http`. Binds to `127.0.0.1:8080` by default, so only your machine can connect. If you bind to `0.0.0.0` to share across your LAN, netglance will print a warning — the HTTP transport has no built-in auth.

### REST API

Started with `netglance api serve`. Binds to `127.0.0.1:8080` by default.

**API key authentication** is available for LAN exposure:

```bash
# Explicit key
netglance api serve --host 0.0.0.0 --api-key my-secret-key

# Environment variable (takes priority)
export NETGLANCE_API_KEY=my-secret-key
netglance api serve --host 0.0.0.0
```

If you bind to a non-localhost address without providing an API key, netglance auto-generates one and prints it to the console.

Clients pass the key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: my-secret-key" http://192.168.1.50:8080/api/v1/devices
```

### Daemon

The background daemon runs scheduled tasks (discovery, DNS checks, baselines) and writes results to the local SQLite database. It has no network listener and no attack surface.

## CORS Policy

The REST API restricts CORS to localhost origins by default. This prevents malicious websites from querying your local API.

To allow additional origins (e.g. a web UI on another machine):

```bash
netglance api serve --cors-origin http://192.168.1.50:3000
```

## Input Validation

All user-supplied parameters (subnets, hostnames, port ranges, URLs) are validated at the API and MCP boundary before reaching any module. This prevents injection attacks in edge cases where modules shell out to external tools (e.g. nmap).

- **Subnets**: Must be valid CIDR notation, max /16 (65,536 addresses)
- **Hostnames**: Must match `[a-zA-Z0-9._-]`, max 253 characters, or be a valid IP
- **Port ranges**: Must contain only digits, commas, and hyphens
- **URLs**: Must use `http://` or `https://` scheme, no shell metacharacters

Invalid input returns HTTP 400 (REST API) or an error dict (MCP).

## Privilege Model

Some tools require elevated privileges (root/sudo) for raw socket access:

| Capability | Tools | Without sudo |
|-----------|-------|-------------|
| ARP scanning | `discover`, `topology`, `iot` | PermissionError with clear message |
| SYN scan | `scan` (SYN mode) | Falls back to TCP connect scan |
| Packet capture | `dhcp` | PermissionError with clear message |
| Raw ICMP | `trace_route` | PermissionError with clear message |

Use `get_server_capabilities` (MCP) to check what's available at your current privilege level.

To run the MCP server with full privileges:

```json
{
  "mcpServers": {
    "netglance": {
      "command": "sudo",
      "args": ["uvx", "netglance-mcp"]
    }
  }
}
```

## Data Storage

- **Database**: SQLite at `~/.config/netglance/netglance.db`
- **Config**: YAML at `~/.config/netglance/config.yaml`
- **No cloud**: Nothing is sent to any remote server. All data stays on your machine.
- **No telemetry**: No analytics, crash reports, or usage tracking.

Network data (device MACs, IPs, hostnames) is stored locally. If this machine is shared, consider filesystem permissions on `~/.config/netglance/`.
