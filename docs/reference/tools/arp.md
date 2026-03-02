# ARP Monitor

Monitor your network's ARP table for changes, anomalies, and potential spoofing attacks.

## What it does

The ARP monitor watches your network's Address Resolution Protocol table—the system that maps IP addresses to MAC addresses on your local network. It can:

- **Display the current ARP table** with vendor information
- **Detect anomalies** like MAC address changes, duplicate IPs, and duplicate MACs
- **Identify spoofing** by comparing against a saved baseline
- **Watch continuously** for real-time monitoring across your network

This is useful for detecting MITM (man-in-the-middle) attacks, network configuration issues, and tracking device changes on your network.

## Quick start

Show the current ARP table:

```bash
netglance arp table
```

Save the current state as a baseline (do this on a healthy, known-good network):

```bash
netglance arp save
```

Compare current state against the saved baseline:

```bash
netglance arp check
```

Watch the ARP table continuously for anomalies:

```bash
netglance arp watch
```

## Commands

### `netglance arp table`

Display all ARP entries currently in the system's ARP table.

**Options:**

- `--interface, -i <name>` — Filter results to a specific network interface (e.g., `en0`). Optional.

**Output:**

A table with four columns:

- **IP Address** — The IPv4 address
- **MAC Address** — The hardware (Ethernet) address in xx:xx:xx:xx:xx:xx format
- **Vendor** — The vendor name associated with the MAC address (OUI lookup)
- **Interface** — The network interface the entry was seen on

**Example:**

```bash
$ netglance arp table
                                    ARP Table
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ IP Address    ┃ MAC Address         ┃ Vendor        ┃ Interf ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 192.168.1.1   │ aa:bb:cc:dd:ee:ff   │ Acme Corp     │ en0    │
│ 192.168.1.10  │ 11:22:33:44:55:66   │ Apple Inc.    │ en0    │
│ 192.168.1.20  │ 99:88:77:66:55:44   │ Unknown       │ en0    │
└───────────────┴─────────────────────┴───────────────┴────────┘
```

Filter by interface:

```bash
netglance arp table --interface en0
```

### `netglance arp save`

Capture and save the current ARP table as a baseline for later comparison.

**Options:**

- `--label, -l <label>` — Assign a descriptive label to this baseline. Optional; defaults to `"arp"`.
- `--db <path>` — Path to the netglance database. Optional; uses default location if not specified.

**Output:**

Confirms the baseline was saved and displays the ARP entries that were captured.

**Example:**

```bash
$ netglance arp save --label "before-maintenance"
Baseline saved (id=5, 12 entries)

                       Saved ARP Baseline
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ IP Address    ┃ MAC Address         ┃ Vendor        ┃ Interf ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 192.168.1.1   │ aa:bb:cc:dd:ee:ff   │ Acme Corp     │ en0    │
│ 192.168.1.10  │ 11:22:33:44:55:66   │ Apple Inc.    │ en0    │
└───────────────┴─────────────────────┴───────────────┴────────┘
```

**Note:** Run this command on a healthy, known-good network state to establish a reliable baseline.

### `netglance arp check`

Compare the current ARP table against the most recently saved baseline and report any anomalies.

**Options:**

- `--gateway, -g <ip>` — Specify the gateway IP to watch. Optional; helps identify gateway spoofing.
- `--db <path>` — Path to the netglance database. Optional; uses default location if not specified.

**Output:**

Displays the current ARP table followed by any detected anomalies as colored panels.

**Example with no anomalies:**

```bash
$ netglance arp check
                           Current ARP Table
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ IP Address    ┃ MAC Address         ┃ Vendor        ┃ Interf ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 192.168.1.1   │ aa:bb:cc:dd:ee:ff   │ Acme Corp     │ en0    │
└───────────────┴─────────────────────┴───────────────┴────────┘

No anomalies detected.
```

**Example with an alert:**

```bash
$ netglance arp check --gateway 192.168.1.1
                           Current ARP Table
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ IP Address    ┃ MAC Address         ┃ Vendor        ┃ Interf ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 192.168.1.1   │ aa:bb:cc:dd:ee:ff   │ Acme Corp     │ en0    │
└───────────────┴─────────────────────┴───────────────┴────────┘

╭─ [red]gateway_spoof[/red] ───────────────────────────────────────────╮
│ Gateway 192.168.1.1 MAC changed from aa:bb:cc:dd:ee:ff to       │
│ ff:ee:dd:cc:bb:aa — possible ARP spoofing                       │
│                                                                  │
│ severity: critical                                              │
╰──────────────────────────────────────────────────────────────────╯
```

### `netglance arp watch`

Continuously monitor the ARP table, polling at regular intervals and displaying alerts in real-time.

**Options:**

- `--interval, -n <seconds>` — Poll interval in seconds. Default: `5.0`. Optional.
- `--gateway, -g <ip>` — Specify the gateway IP to watch. Optional; helps identify gateway spoofing.
- `--db <path>` — Path to the netglance database. Optional; uses default location if not specified.

**Output:**

Clears the screen and displays the live ARP table. If a baseline exists, anomalies are shown below the table. Press `Ctrl+C` to stop.

**Example:**

```bash
Watching ARP table... press Ctrl+C to stop.

                          ARP Table (live)
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ IP Address    ┃ MAC Address         ┃ Vendor        ┃ Interf ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 192.168.1.1   │ aa:bb:cc:dd:ee:ff   │ Acme Corp     │ en0    │
│ 192.168.1.10  │ 11:22:33:44:55:66   │ Apple Inc.    │ en0    │
└───────────────┴─────────────────────┴───────────────┴────────┘

No anomalies.
```

Watch with a 10-second interval:

```bash
netglance arp watch --interval 10
```

## Understanding the output

### ARP Table columns

- **IP Address** — The IPv4 address of the device on the network.
- **MAC Address** — The physical (hardware) address, typically in the format `xx:xx:xx:xx:xx:xx`. This is what the ARP table is designed to map.
- **Vendor** — The equipment manufacturer, looked up from the MAC address's Organizationally Unique Identifier (OUI). Unknown if the OUI is not in the vendor database.
- **Interface** — The network interface (e.g., `en0`, `eth0`) on which the ARP entry was observed.

### Anomaly types

**gateway_spoof** (critical)

The gateway's MAC address has changed since the baseline was saved. This is a strong indicator of ARP spoofing or a compromised gateway. Investigate immediately.

```
Gateway 192.168.1.1 MAC changed from aa:bb:cc:dd:ee:ff to ff:ee:dd:cc:bb:aa
```

**mac_changed** (critical)

An IP address's MAC has changed since the baseline. Could indicate device replacement, but also suspicious if unexpected. Verify the device is legitimate.

```
IP 192.168.1.10 changed MAC from 11:22:33:44:55:66 to 99:88:77:66:55:44
```

**duplicate_ip** (warning)

The same IP address appears in the ARP table with multiple different MAC addresses. This is a classic MITM or ARP spoofing signature—two devices claiming the same IP.

```
IP 192.168.1.15 has multiple MACs: 11:22:33:44:55:66, 99:88:77:66:55:44 — possible MITM
```

**duplicate_mac** (warning)

A single MAC address is bound to multiple IP addresses. This can occur with load balancers, VRRP, or virtual machines, but may also indicate misconfiguration or spoofing.

```
MAC aa:bb:cc:dd:ee:ff is shared by multiple IPs: 192.168.1.10, 192.168.1.20
```

## Related concepts

- **[ARP and MAC Addresses](../../guide/concepts/arp-and-mac-addresses.md)** — Deep dive into ARP protocol mechanics, spoofing techniques, and detection strategies.
- **[Discover Tool](discover.md)** — Enumerate and identify devices on your network.
- **[Baseline Tool](baseline.md)** — Save and compare snapshots of your entire network state.

## Troubleshooting

### "No ARP entries found"

The ARP table is empty. This can happen on a newly booted system or if no devices have communicated on the network recently. Send some traffic (e.g., `ping` a device) to populate the ARP table.

```bash
ping 192.168.1.1
netglance arp table
```

### "No ARP baseline found"

You are trying to run `arp check` or `arp watch` without a saved baseline. Save one first:

```bash
netglance arp save
```

### "Permission denied" or requires sudo

Some network operations may require elevated privileges on certain systems. Try:

```bash
sudo netglance arp table
```

### Interface filter returns no results

Verify the interface name is correct. List available interfaces:

```bash
netglance discover table  # Shows interfaces in the output
```

Then filter by the correct name:

```bash
netglance arp table --interface en0
```

### False positives from load balancers or VRRP

Virtual IP failover systems (like VRRP) can legitimately reassign MAC addresses to the same IP during failover events. If you see repeated `gateway_spoof` or `duplicate_mac` alerts from known infrastructure:

1. Verify the devices are legitimate.
2. Save a fresh baseline after failover to suppress further alerts.

```bash
netglance arp save --label "post-failover"
```

### macOS ARP table quirks

macOS caches ARP entries more aggressively than Linux. Expired entries may persist in the table for hours. To refresh:

```bash
sudo arp -d -a  # Clear the ARP table (requires sudo)
ping 192.168.1.1  # Repopulate by pinging a device
```

Alternatively, restart networking:

```bash
sudo ifconfig en0 down && sudo ifconfig en0 up
```
