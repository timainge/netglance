<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-white.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo.svg">
    <img src="docs/assets/logo.svg" width="32" height="32" alt="">
  </picture>
  netglance
</h1>

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Tests: 1,670](https://img.shields.io/badge/tests-1%2C670-brightgreen)]() [![CI](https://img.shields.io/github/actions/workflow/status/timainge/netglance/ci.yml?label=CI)](https://github.com/timainge/netglance/actions/workflows/ci.yml) [![Docs](https://img.shields.io/github/actions/workflow/status/timainge/netglance/deploy-docs.yml?label=docs)](https://github.com/timainge/netglance/actions/workflows/deploy-docs.yml)

Home network health checks — run by you or your AI.

A Python toolkit for network discovery, monitoring, and security checks. Use it three ways:

- **CLI** — 30+ commands for scanning, diagnostics, and monitoring straight from your terminal
- **Library** — import `netglance` modules into your own Python scripts and automations
- **AI agent** — runs as an MCP server so Claude, Copilot, Cursor, or any MCP-compatible assistant can diagnose your network for you

Covers device discovery (ARP/mDNS), connectivity (ping, speed, jitter, bufferbloat, traceroute), security (DNS leaks, ARP spoofing, TLS, rogue DHCP, firewall), WiFi analysis, port scanning, IoT fingerprinting, and continuous monitoring with alerts.

**[Read the docs](https://timainge.github.io/netglance/)**

## Install

```bash
# with uv (recommended)
uv tool install netglance

# or with pip
pip install netglance
```

## Quick start

```bash
# Find devices on your network
sudo netglance discover

# Run a full health check
netglance report

# Check DNS for leaks
netglance dns

# Measure speed
netglance speed
```

## Development

```bash
git clone https://github.com/timainge/netglance.git
cd netglance
uv pip install -e ".[dev]"
uv run pytest

# Docs site (local preview)
uv run --group docs mkdocs serve
```

## AI Agent Mode (MCP)

netglance works as an MCP server — any AI assistant can run network diagnostics on your behalf. Ask Claude "what's on my network?" and it calls the right tools, interprets the results, and explains what to do.

```bash
# Start the MCP server
netglance mcp serve

# Or via the dedicated entry point
netglance-mcp
```

### Claude Desktop (macOS)

File: `~/Library/Application Support/Claude/claude_desktop_config.json`

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

### Claude Code

```bash
claude mcp add netglance -- uvx netglance-mcp
```

### Cursor

File: `~/.cursor/mcp.json`

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

File: `.vscode/mcp.json`

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

File: `~/.codeium/windsurf/mcp_config.json`

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

Settings → Tools → AI Assistant → MCP → Add stdio server:
- Command: `uvx`
- Arguments: `netglance-mcp`

The MCP server exposes network diagnostic tools including device discovery, connectivity checks, DNS health, port scanning, WiFi analysis, speed tests, and more. See `netglance mcp tools` for the full list.

Some tools (ARP scanning, packet capture) require elevated privileges. Run with `sudo` if needed.

## License

MIT
