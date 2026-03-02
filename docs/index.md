---
title: netglance
hide:
  - navigation
  - toc
---

<div class="hero">
  <img src="assets/hero-light.png" alt="netglance hero" class="hero-img hero-light">
  <img src="assets/hero-dark.png" alt="netglance hero" class="hero-img hero-dark">
</div>

## Know your network. Protect your home.


netglance is a command-line toolkit for home network discovery, monitoring, and security. Find every device, check your DNS, measure speed, detect threats — all from your terminal.

---

## Many roles, one toolkit

netglance adapts to how you manage your network.

<div class="card-grid">
<a class="card" href="reference/usage-modes/cli/">
<p class="card-title">Interactive CLI</p>
<p class="card-desc">Run a command, get instant answers. Ad-hoc troubleshooting from your terminal.</p>
</a>
<a class="card" href="reference/usage-modes/mcp/">
<p class="card-title">AI Agent (MCP)</p>
<p class="card-desc">Ask Claude, Cursor, or VS Code about your network in plain English.</p>
</a>
<a class="card" href="reference/usage-modes/daemon/">
<p class="card-title">Background Daemon</p>
<p class="card-desc">Scheduled checks, alerts, and trend data — runs silently on your Mac.</p>
</a>
<a class="card" href="reference/usage-modes/dedicated/">
<p class="card-title">Dedicated Monitor</p>
<p class="card-desc">24/7 on a Raspberry Pi, Mac Mini, or Docker. Watches while you sleep.</p>
</a>
<a class="card" href="reference/usage-modes/scheduled/">
<p class="card-title">Scheduled Checks</p>
<p class="card-desc">Lightweight cron jobs on any Linux box. No persistent process.</p>
</a>
<a class="card card-soon" href="reference/usage-modes/index/">
<p class="card-title">Router Integration <span class="card-pill">Coming soon</span></p>
<p class="card-desc">Pull device lists, bandwidth stats, and DNS logs straight from your router.</p>
</a>
</div>

**[Compare all modes &rarr;](reference/usage-modes/index.md)**

---

## Start with a question

Not sure where to begin? Pick the question that matches your situation:

**[What's on my network?](guide/practical/whats-on-my-network.md)** — Find every connected device, identify mystery gadgets, and catch unauthorized access.

**[Is my internet actually slow?](guide/practical/is-my-internet-slow.md)** — Test speed, latency, and bufferbloat. Find out if the problem is your WiFi, your ISP, or something else.

**[Am I being watched?](guide/practical/am-i-being-watched.md)** — Check for DNS leaks, traffic interception, ARP spoofing, and VPN leaks.

**[Is my Wi-Fi secure?](guide/practical/is-my-wifi-secure.md)** — Audit encryption, find rogue access points, and lock down your wireless network.

**[Keep my network healthy](guide/practical/keep-my-network-healthy.md)** — Set up continuous monitoring, baselines, and alerts so you know the moment something changes.

---

## Install

=== "uv (recommended)"

    ```bash
    uv tool install netglance
    ```

=== "pip"

    ```bash
    pip install netglance
    ```

---

## See it in action

```console
$ sudo netglance discover
IP Address       Hostname         MAC Address        Vendor
───────────────────────────────────────────────────────────────
192.168.1.1      router.local     aa:bb:cc:dd:ee:ff  Apple
192.168.1.42     macbook.local    aa:bb:cc:dd:ee:00  Apple
192.168.1.100    tv.local         aa:bb:cc:dd:ee:01  Samsung
192.168.1.101    camera           aa:bb:cc:dd:ee:02  Wyze
```

```console
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

---

## 30 commands. 1,670 tests. Zero fluff.

netglance covers discovery, DNS, ping, speed, port scanning, ARP monitoring, TLS verification, Wi-Fi analysis, traffic monitoring, route tracing, firewalls, VPN leak detection, DHCP auditing, IPv6, and more.

[Get started](reference/getting-started.md) | [Browse the docs](guide/index.md)
