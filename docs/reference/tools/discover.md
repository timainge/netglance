# Device Discovery

> Find all devices on your local network using ARP scanning and mDNS browsing.

## What it does

The discover tool maps your local network by sending ARP (Address Resolution Protocol) requests to discover devices by IP and MAC address, and by browsing mDNS/Bonjour services to identify hostnames. It combines both methods to build a complete inventory of connected devices, enriching the results with vendor information from a MAC address (OUI) database.

Use discovery to understand what's on your network, detect new or missing devices, and track changes over time. ARP works on the local network segment only; mDNS can reveal hostnames and friendly names for services like printers, smart home devices, and computers.

## Quick start

Scan your subnet for all devices:
```bash
uv run netglance discover
```

Scan a specific subnet with a timeout:
```bash
uv run netglance discover --subnet 192.168.1.0/24
```

Scan using only ARP or only mDNS:
```bash
uv run netglance discover --method arp
uv run netglance discover --method mdns
```

Save results to the database and compare against a baseline:
```bash
uv run netglance discover --save --diff
```

Export results as JSON:
```bash
uv run netglance discover --json
```

## Commands

### discover (main command)

Discover devices on the local network.

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--subnet` | `-s` | `192.168.1.0/24` | Subnet to scan (CIDR notation). |
| `--interface` | `-i` | none | Network interface to use for ARP scanning (e.g., `eth0`, `en0`). If not specified, scapy auto-detects. |
| `--method` | `-m` | `all` | Discovery method: `arp`, `mdns`, or `all`. |
| `--save` | | false | Persist discovery results to SQLite and save as baseline. |
| `--diff` | | false | Compare current scan against the saved baseline and highlight new, missing, and changed devices. |
| `--json` | | false | Output results as JSON instead of a formatted table. |
| `--db` | | `~/.config/netglance/netglance.db` | Override database path (hidden option). |

## Understanding the output

### Device table

When you run a discovery scan, you get a table with these columns:

| Column | Meaning |
|--------|---------|
| **IP** | IPv4 address assigned to the device (or discovered via mDNS). |
| **MAC** | Media Access Control (physical hardware) address, in lowercase hex (e.g., `a4:83:e7:12:34:56`). Empty if discovered via mDNS only. |
| **Hostname** | Hostname or device name from reverse DNS lookup (ARP) or mDNS service name. |
| **Vendor** | Manufacturer name resolved from MAC address OUI (Organizationally Unique Identifier) database. |
| **Method** | How the device was discovered: `arp` (ARP scan), `mdns` (mDNS/Bonjour), or `arp+mdns` (found by both methods). |
| **Status** | In diff mode, shows `online` (known device), `new` (not in baseline), or `changed` (same MAC, different IP or hostname). |

### Missing devices table

When you use `--diff`, a second table appears showing devices that were in the baseline but are not found in the current scan. These are devices that were on your network before but are no longer responding or have left the network.

### JSON output

With `--json`, the output includes:

```json
{
  "devices": [
    {
      "ip": "192.168.1.42",
      "mac": "a4:83:e7:12:34:56",
      "hostname": "printer.local",
      "vendor": "Apple Inc.",
      "discovery_method": "arp+mdns",
      "first_seen": "2025-02-18T14:30:15.123456",
      "last_seen": "2025-02-18T14:30:15.123456"
    }
  ],
  "diff": {
    "new": [...],
    "missing": [...],
    "changed": [...]
  }
}
```

The diff object is only included if `--diff` was used.

## Discovery methods

### ARP scanning

Sends ARP requests to all addresses in the specified subnet. Each request asks "who has this IP?" and waits for responses. Devices reply with their MAC address. This method:

- Works on the local network segment only.
- Requires no special service configuration from target devices.
- Finds any device with an IP address on your subnet.
- Provides reliable MAC addresses.
- May require root/sudo on some platforms for raw socket access.

### mDNS browsing

Listens for mDNS/Bonjour service advertisements (like `_http._tcp.local.` and `_workstation._tcp.local.`). This method:

- Does not require sending unsolicited requests; devices advertise themselves.
- Often discovers hostnames and friendly device names.
- May not find devices that don't advertise any mDNS services.
- Does not always provide MAC addresses.
- Works across network segments if mDNS multicast is available.

### Combined mode (default)

Runs both ARP and mDNS scans and merges the results by MAC address. When a device is found by both methods, ARP data takes precedence (since it always has a MAC), but the hostname from mDNS is kept if the ARP lookup didn't find one.

## Device diff

Use `--diff` to compare the current scan against a saved baseline and understand what has changed:

- **new**: MAC addresses found in the current scan but not in the baseline. These are devices that are now on your network.
- **missing**: MAC addresses in the baseline but not found in the current scan. These devices were on your network before but are no longer responding.
- **changed**: Same MAC address, but different IP or hostname. This can indicate a device has been assigned a new IP or changed its hostname.

Each time you use `--save`, a new baseline is created. Use `--diff` on the same baseline to see changes between scans.

## Related concepts

- [ARP and MAC Addresses](../../guide/concepts/arp-and-mac-addresses.md) — background on how ARP works, what MAC addresses are, and why they matter for device identification.
- [DNS Explained](../../guide/concepts/dns-explained.md) — how DNS and mDNS service discovery works and what hostname resolution means.

## Troubleshooting

### "Permission denied" or "cannot open raw socket"

ARP scanning requires raw socket access, which usually needs root or administrator privileges on macOS and Linux.

**Fix:** Run with `sudo`:
```bash
sudo uv run netglance discover --method arp
```

Or use mDNS only (no sudo needed):
```bash
uv run netglance discover --method mdns
```

### No devices found

- **Wrong subnet**: Verify your subnet is correct. On macOS, run `ifconfig` to see your interface and subnet. On Linux, run `ip addr`.
- **Devices not responding**: Some devices ignore ARP requests or disable mDNS. Try broadening the timeout or checking manually with `ping`.
- **Interface not selected**: If you have multiple network interfaces, specify the correct one with `--interface en0` (macOS) or `--interface eth0` (Linux).

### Scan taking too long

Large subnets (e.g., 10.0.0.0/16) require many ARP requests. The default timeout is 3 seconds per request. For large scans, consider:

- Narrowing the subnet (e.g., scan 10.0.1.0/24 instead of 10.0.0.0/16).
- Using ARP only and skipping mDNS: `--method arp`.

### Missing hostnames

- Devices without reverse DNS or mDNS service advertisement will show blank hostnames. This is normal for many IoT devices.
- Add custom hostnames manually by editing your local DNS or `/etc/hosts` if needed.

### Vendor lookup shows "unknown"

The MAC OUI database may not have entries for very new or obscure vendors. If you know the vendor, you can note it manually.
