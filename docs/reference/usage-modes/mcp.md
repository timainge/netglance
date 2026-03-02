# AI Agent (MCP Server)

> Ask your AI assistant about your network and get real answers.

netglance includes an [MCP server](https://modelcontextprotocol.io/) that exposes all 25 diagnostic tools to AI assistants. Instead of remembering command syntax, describe what you want in plain English — "are there any unknown devices on my network?", "is my DNS leaking?", "why is my internet slow?" — and your AI runs the right checks automatically.

## When to use this mode

- You prefer natural language over CLI flags
- You want an AI to interpret results and suggest next steps, not just show raw output
- You use Claude Desktop, Claude Code, Cursor, VS Code Copilot, Windsurf, Goose, or JetBrains AI
- You want to combine network diagnostics with other tasks in an AI conversation (e.g., "check my network, then draft a ticket for IT")

## What it looks like

Once configured, you talk to your AI assistant normally:

> **You**: What's on my network right now?
>
> **Assistant**: I'll scan your network. *(runs discover_devices)* I found 8 devices:
> your router, MacBook, two iPhones, a Samsung TV, a Wyze camera, a Sonos speaker,
> and an unknown device at 192.168.1.115 with a TP-Link MAC address.
> Want me to scan its ports to figure out what it is?

> **You**: Is my DNS being hijacked?
>
> **Assistant**: Let me check. *(runs check_dns_health)* Your DNS looks clean — no
> hijacking detected. All queries resolve consistently across 4 resolvers and DNSSEC
> is validating correctly.

The AI has access to 25 tools covering discovery, connectivity, security, and monitoring. It picks the right tool, runs it, and explains the results in context.

## Setup

### 1. Install netglance

```bash
uv tool install netglance
```

### 2. Configure your AI client

=== "Claude Desktop"

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

    Restart Claude Desktop. You'll see netglance tools in the tools menu.

=== "Claude Code"

    ```bash
    claude mcp add netglance -- uvx netglance-mcp
    ```

=== "Cursor"

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

=== "VS Code (Copilot)"

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

=== "Windsurf"

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

=== "JetBrains"

    Settings &rarr; Tools &rarr; AI Assistant &rarr; MCP &rarr; Add stdio server:

    - **Command**: `uvx`
    - **Arguments**: `netglance-mcp`

### 3. Start asking questions

Try these to verify it's working:

- "What devices are on my network?"
- "Run a speed test and tell me if my connection is slow."
- "Is my VPN leaking DNS queries?"
- "Check if any IoT devices have security risks."

## How it works

The MCP server runs locally on your machine. Your AI client launches it automatically when needed (via the config above) and communicates over stdio. No data leaves your network unless a specific tool makes outbound connections (DNS queries, speed tests, TLS checks to remote hosts).

Tools that require elevated privileges (ARP scanning, packet capture) degrade gracefully with clear error messages when running unprivileged. Use `get_server_capabilities` to check what's available at your current privilege level.

To run with full privileges:

```bash
# In your MCP client config, change the command to:
"command": "sudo",
"args": ["uvx", "netglance-mcp"]
```

## Pairing with the daemon

MCP + Daemon is a powerful combination. The daemon collects data continuously in the background, and your AI assistant queries the stored results on demand:

- Daemon captures baselines, metrics, and alerts around the clock
- Ask your AI: "compare my current network to last week's baseline"
- AI reads from the database — no need to re-run slow scans

See [Background Daemon](daemon.md) for daemon setup.

## Full reference

For the complete list of 25 tools, their parameters, privilege requirements, and tool annotations, see the **[MCP Server reference](../tools/mcp.md)**.
