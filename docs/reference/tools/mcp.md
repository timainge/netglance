# MCP Server

> Let AI assistants run network diagnostics using the Model Context Protocol.

## What it does

netglance includes an MCP server that exposes all 25 network diagnostic tools to AI assistants. Any MCP-compatible client — Claude Desktop, Claude Code, Cursor, VS Code Copilot, Windsurf, JetBrains AI — can discover devices, check DNS health, scan ports, trace routes, run speed tests, and more, all through natural language.

The MCP server runs locally on your machine. No data leaves your network unless a tool explicitly makes outbound connections (DNS queries, speed tests, TLS checks). Tools that need elevated privileges (ARP scanning, packet capture) degrade gracefully with clear error messages when running unprivileged.

## Quick start

Start the MCP server (stdio transport, for direct client integration):

```bash
netglance-mcp
```

Or via the CLI subcommand with more options:

```bash
netglance mcp serve
```

List all available tools:

```bash
netglance mcp tools
```

List tools with annotations and parameter details:

```bash
netglance mcp tools --verbose
```

## Client configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "netglance": {
      "command": "uvx",
      "args": ["netglance-mcp"]
    }
  }
}
```

Restart Claude Desktop after saving. You should see netglance tools listed in the tools menu.

### Claude Code

```bash
claude mcp add netglance -- uvx netglance-mcp
```

This registers netglance as an MCP server for all sessions. To add it to a specific project only, run the command from the project directory with `--scope project`.

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "netglance": {
      "command": "uvx",
      "args": ["netglance-mcp"]
    }
  }
}
```

### VS Code (Copilot)

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "netglance": {
      "type": "stdio",
      "command": "uvx",
      "args": ["netglance-mcp"]
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "netglance": {
      "command": "uvx",
      "args": ["netglance-mcp"]
    }
  }
}
```

### JetBrains

Settings &rarr; Tools &rarr; AI Assistant &rarr; MCP &rarr; Add stdio server:

- **Command**: `uvx`
- **Arguments**: `netglance-mcp`

## Commands

### mcp serve

Start the MCP server.

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--transport` | `-t` | `stdio` | Transport protocol: `stdio` or `http`. |
| `--host` | | `127.0.0.1` | Host to bind (HTTP transport only). |
| `--port` | `-p` | `8080` | Port to bind (HTTP transport only). |

```bash
# Default stdio transport (for MCP client integration)
netglance mcp serve

# HTTP transport for multi-client or remote access
netglance mcp serve --transport http --port 8080
```

!!! warning "HTTP transport security"
    The HTTP transport binds to localhost by default. If you expose it on `0.0.0.0`, be aware it has no authentication. Use stdio for single-client setups.

### mcp tools

List all MCP tools exposed by the server.

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--json` | | false | Output as JSON. |
| `--verbose` | `-v` | false | Show annotations and parameters. |

## Available tools

The MCP server exposes 25 tools organised by category:

### Discovery & inventory

| Tool | Description |
|------|-------------|
| `discover_devices` | Find all devices on the local network using ARP and mDNS. |
| `identify_devices` | Fingerprint devices to determine type, OS, and manufacturer. |
| `get_network_topology` | Build a topology map showing how devices are connected. |
| `compare_to_baseline` | Snapshot the network and diff against a saved baseline. |

### Connectivity & performance

| Tool | Description |
|------|-------------|
| `check_connectivity` | Ping the gateway, internet, and custom hosts. |
| `run_speed_test` | Measure download, upload, and latency. |
| `assess_performance` | Measure jitter, packet loss, MTU, and bufferbloat. |
| `trace_route` | Trace the network path to a destination. |
| `get_uptime_summary` | Get uptime history for a monitored host. |

### Security & auditing

| Tool | Description |
|------|-------------|
| `check_dns_health` | Check DNS resolver consistency and detect hijacking. |
| `scan_ports` | Scan TCP ports and identify open services. |
| `check_arp_table` | Read the ARP table and detect anomalies (MITM). |
| `check_tls_certificates` | Verify TLS certificates and detect interception. |
| `check_http_headers` | Probe HTTP headers for proxy injection. |
| `check_vpn_leaks` | Detect DNS and IPv6 leaks through VPN tunnels. |
| `check_dhcp` | Listen for DHCP traffic and detect rogue servers. |
| `audit_firewall` | Test egress firewall rules on common ports. |
| `check_ipv6` | Audit IPv6 configuration and privacy extensions. |
| `audit_iot_devices` | Find IoT devices and assess security risks. |
| `scan_wifi_environment` | Scan nearby WiFi networks and analyse channel usage. |

### Monitoring & data

| Tool | Description |
|------|-------------|
| `run_health_check` | Run a comprehensive health report across all modules. |
| `get_metrics` | Query stored metric time-series data. |
| `get_alert_log` | Retrieve recent alert log entries. |
| `get_server_capabilities` | Report privilege level and tool availability. |

### Utilities

| Tool | Description |
|------|-------------|
| `send_wake_on_lan` | Send a WoL magic packet to wake a device. |

## Privilege requirements

Some tools require elevated privileges (root/sudo) for raw socket access. When running without privileges, these tools return informative error messages instead of crashing.

| Tool | Why it needs root | Unprivileged behaviour |
|------|-------------------|----------------------|
| `discover_devices` | ARP scanning requires raw sockets. | Returns error with suggestion. |
| `scan_ports` | SYN scan requires raw sockets. | Falls back to TCP connect scan. |
| `check_dhcp` | DHCP sniffing requires packet capture. | Returns error with suggestion. |
| `trace_route` | Raw ICMP requires raw sockets. | Returns error with suggestion. |
| `get_network_topology` | Uses ARP scanning internally. | Discovery portion may fail. |
| `audit_iot_devices` | Uses ARP scanning internally. | Discovery portion may fail. |

Use `get_server_capabilities` to check the current privilege level and which tools are affected:

```
> Use the get_server_capabilities tool

The server reports it's running unprivileged. Tools like discover_devices
and check_dhcp need sudo. Want me to try the ones that work without root?
```

To run the MCP server with elevated privileges:

```bash
sudo netglance-mcp
```

## Resources

The MCP server also exposes three read-only resources:

| Resource URI | Description |
|-------------|-------------|
| `netglance://baseline/current` | Last saved network baseline. |
| `netglance://config` | Current netglance configuration. |
| `netglance://devices` | Last known device inventory. |

## Tool annotations

Every tool includes MCP annotations that help clients make auto-approve decisions:

- **readOnlyHint** — Tool only reads data (safe to auto-approve).
- **openWorldHint** — Tool makes network connections beyond localhost.
- **destructiveHint** — Tool modifies state (none of netglance's tools are destructive).

View annotations with:

```bash
netglance mcp tools --verbose
```

## Example conversations

Here are examples of what you can ask an AI assistant once netglance is connected:

- "What devices are on my network?"
- "Is my DNS being hijacked?"
- "Run a speed test and tell me if my connection is slow."
- "Check if any IoT devices on my network have security risks."
- "Trace the route to cloudflare.com and tell me where the latency is."
- "Compare my current network to the baseline — has anything changed?"
- "Is my VPN leaking DNS queries?"
