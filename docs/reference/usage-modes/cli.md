# Interactive CLI

> Run a command. Get results. Done.

The interactive CLI is the simplest way to use netglance. No configuration, no background processes — just install and start asking questions about your network.

## When to use this mode

- You're troubleshooting something right now — slow internet, a mystery device, a DNS problem
- You want a one-off health check before or after changing network settings
- You're exploring what netglance can do before committing to continuous monitoring
- You need to export a quick inventory or scan result for a report

## What it looks like

```console
$ sudo netglance discover
IP Address       Hostname         MAC Address        Vendor
───────────────────────────────────────────────────────────────
192.168.1.1      router.local     aa:bb:cc:dd:ee:ff  Apple
192.168.1.42     macbook.local    aa:bb:cc:dd:ee:00  Apple
192.168.1.100    tv.local         aa:bb:cc:dd:ee:01  Samsung
192.168.1.101    camera           aa:bb:cc:dd:ee:02  Wyze

$ netglance report
Network Health Report
───────────────────────────────────────────────────────
Discover     ✓ 8 devices found
DNS          ✓ No leaks detected
Ping         ✓ All responsive (avg 5ms)
Speed        ⚠ Download 45 Mbps (expected 100+)
WiFi         ⚠ Signal: -68 dBm (fair)
TLS          ✓ All certificates valid
ARP          ✓ No spoofing detected
```

## Getting started

1. Install netglance:

    ```bash
    uv tool install netglance
    ```

2. Discover devices on your network:

    ```bash
    sudo netglance discover
    ```

3. Run a full health check:

    ```bash
    netglance report
    ```

4. Dive deeper with individual commands:

    ```bash
    netglance dns              # DNS health and leak detection
    netglance speed            # Download/upload speed test
    netglance wifi             # Wireless environment analysis
    sudo netglance scan <ip>   # Port scan a specific device
    ```

See [Getting Started](../getting-started.md) for a full walkthrough, or browse all [30 commands](../index.md#commands).

## Tips

- **Use `sudo`** for commands that need raw socket access (discover, scan, dhcp, trace). netglance tells you when it needs elevated privileges.
- **Pipe output** to files or tools: `netglance report --json | jq .` for machine-readable output.
- **Export results** with `netglance export` to save inventories as JSON, CSV, or HTML.
- **Run `--help`** on any command to see all available flags: `netglance ping --help`.

## When to level up

The CLI is great for ad-hoc work, but you'll eventually want more if:

- You keep running the same checks manually — try the [Background Daemon](daemon.md) or [Scheduled Checks](scheduled.md)
- You want to ask natural language questions — try the [AI Agent (MCP)](mcp.md)
- You want monitoring that runs even when your laptop sleeps — try a [Dedicated Monitor](dedicated.md)
