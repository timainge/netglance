# Port Scanning

> Identify open ports and running services on a device to spot unexpected services and security risks.

## What it does

Port scanning checks which network ports are open on a device, helping identify running services (web servers, SSH, file sharing, etc.) and detect unexpected services that could be security risks. netglance supports two scanning modes: **quick scans** check ~100 common ports and finish in seconds, while **full scans** check all 65,535 ports but take longer. When nmap is available, netglance can optionally detect service versions to identify outdated or vulnerable software.

Port scanning is useful for baseline inventory (what services should be running on each device), ongoing monitoring (did anything new start?), and security posture assessment (are there listening ports you didn't expect?).

## Quick start

```bash
# Quick scan of the top 100 common ports on a device
netglance scan host 192.168.1.100

# Scan specific ports
netglance scan host 192.168.1.100 -p 22,80,443,3306

# Scan a range of ports
netglance scan host 192.168.1.100 -p 1-1024

# Save the scan and compare with the last one
netglance scan host 192.168.1.100 --save --diff

# Full scan (all ports, takes longer)
netglance scan host 192.168.1.100 -p 1-65535
```

## Commands

```
netglance scan host [OPTIONS] HOST

Arguments:
  HOST                     IP address or hostname to scan.

Options:
  -p, --ports TEXT         Port range (e.g. '22,80,443' or '1-1024').
                           Defaults to top-100 common ports if not specified.
  -s, --save               Persist results to the database for future comparison.
  -d, --diff               Compare with the last saved scan for this host.
                           Shows new, closed, and changed services.
  --help                   Show help message.
```

## Understanding the output

Each scan result displays a table with four columns:

- **Port**: The TCP port number. Color-coded for quick interpretation:
  - Green: normal service port
  - Red: suspicious/dangerous port (e.g., Telnet, unencrypted FTP, RDP, VNC)
  - Yellow: newly opened port (when using `--diff`)

- **State**: The port state:
  - `open`: Port is accepting connections; a service is actively listening
  - `filtered`: Port might be open, but a firewall is blocking the response
  - `closed`: Port is not listening

- **Service**: The service name detected on the port (e.g., http, ssh, smb). Only available when nmap is installed and can identify the service. Shows as empty if unknown.

- **Version**: The service version (e.g., OpenSSH 7.4). Requires nmap and service version detection enabled. Shows as empty if not detected.

### What "good" vs "bad" looks like

**Good example**: A laptop with only port 22 (SSH) and 5900 (VNC for remote desktop) open is expected—minimal attack surface.

**Bad example**: Port 23 (Telnet) open on any modern device is suspicious—Telnet sends credentials in plaintext. Port 445 (SMB/Windows file sharing) exposed directly to the internet is a common attack vector.

**Unexpected example**: Port 3306 (MySQL) open on a user's workstation when they don't run a database server suggests either misconfiguration or a rogue service.

## Quick vs full scan

- **Quick scan** (default): Checks the top 100 most commonly used ports. Completes in seconds. Best for:
  - Routine monitoring of devices
  - Quick inventory checks
  - Finding most common services

- **Full scan** (specify `-p 1-65535`): Checks all 65,535 ports. Takes minutes. Best for:
  - Initial security assessments
  - Detecting unusual or non-standard services
  - Comprehensive baseline documentation

### Trade-offs

- Quick scan misses services on non-standard ports (e.g., a web server on port 8080 instead of 80)
- Full scan is slow; consider running during off-hours or on less critical devices
- Scans generate network traffic and may trigger IDS/IPS alerts if running frequently

## Scan diff and change detection

The `--diff` flag compares the current scan against the last saved scan for the same host, showing:

- **New ports**: Ports that are now open but weren't before. May indicate new services or compromised device.
- **Closed ports**: Ports that were open before but are now closed. Expected during legitimate reconfiguration.
- **Changed services**: Same port is open in both scans but the service version changed (e.g., SSH upgraded from 7.4 to 8.0). Indicates updates or replacement.

**Workflow**: Use `--save --diff` together to automatically save each scan and compare with the previous one. Over time, this builds a timeline of changes and helps detect anomalies.

## Related concepts

- **Ports and services**: See `concepts/ports-and-services.md` for background on TCP/UDP ports, the well-known port range (0–1023), and which services commonly run on specific ports.
- **Service fingerprinting**: See `tools/discover.md` for how netglance identifies devices on the network using ARP, mDNS, and other discovery methods.

## Troubleshooting

**Issue: "Permission denied" or "Operation not permitted"**

SYN scans (the default mode) require raw socket access. On macOS and Linux:

```bash
sudo netglance scan host 192.168.1.100
```

On Windows, run the command prompt as Administrator.

---

**Issue: Service names and versions not showing**

Service detection requires nmap to be installed. Check if it's available:

```bash
which nmap
```

If not installed:
- **macOS**: `brew install nmap`
- **Ubuntu/Debian**: `apt-get install nmap`
- **Windows**: Download from https://nmap.org/download

Without nmap, netglance falls back to basic socket-level scanning and reports only open/closed/filtered state, no service names.

---

**Issue: Scan takes a very long time**

Full scans (all 65,535 ports) can take several minutes depending on the target and network. To speed up:

- Use quick scan (default) instead: `netglance scan host <IP>`
- Reduce the timeout: specify `-p 1-1024` to scan only the first 1024 ports
- Ensure no firewall is blocking ICMP packets; some networks drop all probe packets

---

**Issue: All ports show as "filtered"**

The target device or a firewall between you and the target is blocking probe packets. Common causes:

- Firewall rule blocking incoming TCP SYN probes
- Firewall rule blocking ICMP packets (breaks ping and some scans)
- Target is offline

Try scanning a known open port first (e.g., if you SSH into the device, port 22 should be open).

---

**Platform notes**

- **macOS**: Requires root/sudo for SYN scans. Homebrew nmap installation works well.
- **Linux**: Requires root/sudo for raw sockets. Most distributions package nmap in their repositories.
- **Windows**: Requires Administrator privilege. WSL2 may not have raw socket access depending on configuration.
