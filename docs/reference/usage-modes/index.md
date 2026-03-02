# Usage Modes

> One toolkit, many ways to run it — pick the setup that fits how you manage your network.

netglance works as a quick CLI tool, an AI assistant backend, a background daemon, a dedicated monitor on hardware, or a lightweight cron job. You can combine modes too.

<div class="card-grid">
<a class="card" href="cli/">
<p class="card-title">Interactive CLI</p>
<p class="card-desc">Run a command, get results, done. Ad-hoc troubleshooting and one-off checks.</p>
</a>
<a class="card" href="mcp/">
<p class="card-title">AI Agent (MCP)</p>
<p class="card-desc">Natural language network diagnostics via Claude, Cursor, VS Code, and more.</p>
</a>
<a class="card" href="daemon/">
<p class="card-title">Background Daemon</p>
<p class="card-desc">Always-on monitoring with scheduled checks, alerts, and trend storage.</p>
</a>
<a class="card" href="dedicated/">
<p class="card-title">Dedicated Monitor</p>
<p class="card-desc">24/7 on a Raspberry Pi, Mac Mini, or Docker container.</p>
</a>
<a class="card" href="scheduled/">
<p class="card-title">Scheduled Checks</p>
<p class="card-desc">Lightweight cron or systemd timers. No persistent process needed.</p>
</a>
<a class="card card-soon" href="./">
<p class="card-title">Router Integration <span class="card-pill">Coming soon</span></p>
<p class="card-desc">Pull device lists, bandwidth stats, and DNS logs straight from your router.</p>
</a>
</div>

## At a glance

| Mode | Best for | Setup effort | Persistent | Needs hardware |
|------|----------|:------------:|:----------:|:--------------:|
| [Interactive CLI](cli.md) | Ad-hoc troubleshooting | Minimal | No | No |
| [AI Agent (MCP)](mcp.md) | Natural language diagnostics | Low | No | No |
| [Background Daemon](daemon.md) | Always-on monitoring | Medium | Yes | No |
| [Dedicated Monitor](dedicated.md) | 24/7 headless operation | Higher | Yes | Yes |
| [Scheduled Checks](scheduled.md) | Periodic checks without a daemon | Low | No | No |

---

## Interactive CLI

The default way to use netglance. Run a command, get results, done.

**Who it's for**: Anyone troubleshooting a network issue right now — slow internet, mystery device, DNS problems.

```bash
sudo netglance discover
netglance dns
netglance report
```

This is what [Getting Started](../getting-started.md) covers. **[Read more &rarr;](cli.md)**

---

## AI Agent (MCP Server)

netglance exposes all 25 diagnostic tools via the [Model Context Protocol](https://modelcontextprotocol.io/), so AI assistants can run network checks through natural language.

**Who it's for**: Users of Claude Desktop, Claude Code, Cursor, VS Code Copilot, Windsurf, Goose, or JetBrains AI who want to ask questions like "are there any unknown devices on my network?" and get real answers.

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

**[Read more &rarr;](mcp.md)**

---

## Background Daemon

Run netglance as a persistent background service that executes scheduled checks, stores results, and triggers alerts.

**Who it's for**: Users who want continuous monitoring on their primary machine without thinking about it.

```bash
netglance daemon install
netglance daemon status
```

**[Read more &rarr;](daemon.md)**

---

## Dedicated Monitor

Deploy netglance on always-on hardware for 24/7 network visibility.

| Platform | Best when | Notes |
|----------|-----------|-------|
| **Raspberry Pi** | Low power, cheap, dedicated | ARM-compatible, ~5W power draw |
| **Mac Mini** | Already have one, want launchd | Native macOS, no cross-compile |
| **Docker** | Portable, reproducible, any host | Works on NAS, VM, or cloud |

**Who it's for**: Users who want a network monitoring appliance — always running, always watching, even when your laptop is closed.

**[Read more &rarr;](dedicated.md)**

---

## Scheduled Checks

Run netglance on a timer without a persistent process. Lighter than the daemon, good for servers and VMs.

**Who it's for**: Linux users, sysadmins, or anyone who prefers cron/systemd timers over a daemon.

```bash
# crontab -e
0 */6 * * * /usr/local/bin/netglance report --json >> /var/log/netglance/report.log 2>&1
```

**[Read more &rarr;](scheduled.md)**

---

## Combining Modes

Modes aren't mutually exclusive. Common combinations:

- **Daemon + MCP**: Background monitoring collects data; ask your AI assistant to analyze it on demand.
- **Pi + Scheduled Checks + Alerts**: Dedicated hardware runs periodic scans and notifies you when something changes.
- **CLI + Daemon**: Use the daemon for continuous baselines, drop into CLI for deep dives when an alert fires.

Pick one mode to start. Add more as your needs grow.
