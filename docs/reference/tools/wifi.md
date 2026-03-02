# WiFi

Analyze your wireless network environment, detect nearby access points, monitor channel congestion, and identify potential rogue access points (evil twins).

## What it does

The `netglance wifi` tool provides comprehensive wireless network analysis on macOS:

- **Scan nearby networks** — Discover all WiFi networks in range, showing signal strength, channel, band, and security type
- **Check current connection** — Display detailed info about your active WiFi connection, including signal, noise, and SNR
- **Analyze channel utilization** — See how many networks are on each WiFi channel to identify congestion
- **Detect rogue APs** — Identify networks broadcasting known SSIDs from unexpected MAC addresses (potential evil-twin attacks)

Uses the macOS `airport` utility when available, with automatic fallback to `networksetup` for compatibility with modern macOS versions.

## Quick start

```bash
# Scan nearby networks, sorted by signal strength
netglance wifi scan

# Check your current WiFi connection
netglance wifi info

# See which channels are crowded
netglance wifi channels

# Detect rogue APs given known SSIDs and BSSIDs
netglance wifi rogues --ssid "HomeNetwork" --bssid "aa:bb:cc:dd:ee:ff" \
                     --ssid "HomeNetwork" --bssid "11:22:33:44:55:66"
```

## Commands

### `netglance wifi scan`

Scan and list all nearby WiFi networks.

```bash
netglance wifi scan [--sort {signal|channel|ssid}]
```

**Options:**
- `--sort, -s` — Sort results by `signal` (strongest first, default), `channel` (ascending), or `ssid` (alphabetical)

**Output:**
A table showing:
- **SSID** — Network name (or "(hidden)" if not broadcasting)
- **BSSID** — MAC address of the access point
- **Signal** — Signal strength in dBm (negative number, e.g., -55 dBm)
- **Bar** — Visual signal bar (5 blocks = excellent)
- **Ch** — WiFi channel number
- **Band** — Frequency band (2.4 GHz, 5 GHz, or 6 GHz)
- **Security** — Authentication type (WPA2, WPA3, Open, WEP, etc.)

### `netglance wifi info`

Show details about your current WiFi connection.

```bash
netglance wifi info
```

**Output:**
Displays in a panel:
- **SSID** — Connected network name
- **BSSID** — Access point MAC address
- **Signal** — Current signal strength in dBm with visual bar
- **Channel** — Channel number and band
- **Security** — Authentication method
- **Noise** — Background noise level (if available)
- **SNR** — Signal-to-Noise Ratio in dB (if noise data available)

### `netglance wifi channels`

Show how many networks occupy each WiFi channel (congestion analysis).

```bash
netglance wifi channels
```

**Output:**
A table with:
- **Channel** — Channel number
- **Networks** — Count of networks on that channel
- **Usage** — Visual bar (green ≤2 networks, yellow ≤5, red >5)

Helps identify less congested channels for your own network.

### `netglance wifi rogues`

Detect potential rogue access points (evil twins).

```bash
netglance wifi rogues --ssid NAME --bssid MAC [--ssid NAME --bssid MAC ...]
```

**Options:**
- `--ssid, -s` — Known SSID to monitor (repeatable, can provide multiple)
- `--bssid, -b` — Known/trusted MAC address for that SSID (repeatable, must match --ssid order)

**Example:**
```bash
netglance wifi rogues \
  --ssid "HomeNetwork" --bssid "aa:bb:cc:dd:ee:ff" \
  --ssid "HomeNetwork" --bssid "11:22:33:44:55:66" \
  --ssid "GuestWiFi" --bssid "99:88:77:66:55:44"
```

**Output:**
If rogue APs detected, shows a red-highlighted table with the suspicious networks. If no rogues found, displays a green confirmation message.

## Understanding the output

### Signal strength (dBm)

WiFi signal strength is measured in dBm (decibels relative to one milliwatt), always a negative number:

- **≥ -50 dBm** — Excellent (5 bars). Strongest possible signal.
- **≥ -60 dBm** — Good (4 bars). Strong and reliable.
- **≥ -70 dBm** — Fair (3 bars). Usable, but may see packet loss.
- **≥ -80 dBm** — Weak (2 bars). Unreliable, expect slowdowns.
- **≥ -90 dBm** — Very weak (1 bar). Barely connected.
- **< -90 dBm** — No signal (0 bars).

The closer to 0 (less negative), the stronger the signal.

### Bands and channels

- **2.4 GHz** — Channels 1–14. Longer range, more interference, slower speeds. Overlapping channels cause congestion.
- **5 GHz** — Channels 36–196. Shorter range, less interference, faster speeds.
- **6 GHz** — Channels 1+. Newest standard (WiFi 6E), least congestion.

The scan output may show dual-band networks (e.g., "36,1" means primarily on channel 36, also on channel 1).

### Security types

- **WPA3** — Newest, most secure.
- **WPA2** — Widely used, secure. Still good for most users.
- **WPA/WPA2** — Mixed mode, backward compatible.
- **WEP** — Outdated and insecure. Avoid.
- **Open** — No authentication. Insecure.

### Noise and SNR

- **Noise (dBm)** — Background RF interference level. Lower (more negative) is better.
- **SNR (dB)** — Signal-to-Noise Ratio (signal dBm minus noise dBm). Higher is better; ≥20 dB is good.

### Rogue detection

A "rogue AP" flag appears when:
1. A network is broadcasting an SSID you marked as "known"
2. But the BSSID (MAC address) doesn't match any you provided

This indicates a potential evil-twin attack or misconfiguration. Verify before connecting.

## Related concepts

- **[ARP tool](arp.md)** — Monitor ARP activity to detect ARP spoofing attacks on wireless devices
- **[Discover tool](discover.md)** — Discover connected devices on your network
- **WiFi security concepts** — Understanding WPA, channel overlap, and rogue access points

## Troubleshooting

### "Error: WiFi scanning via airport is only supported on macOS"

The tool only works on macOS. For other platforms, consider using standard WiFi utilities (iwconfig on Linux, netsh on Windows).

### Limited scan results or no networks found

**On macOS 14+ without Location Services:**
The `airport` command may return empty results. Grant Location Services permission:
1. System Settings → Privacy & Security → Location Services
2. Enable Location Services
3. Try the scan again

Alternatively, the tool will automatically fall back to `networksetup`, which may show fewer details but confirm if you're connected.

### Scan shows only your own network

Make sure Location Services is enabled (see above). Otherwise, the tool is working correctly; you may just have very few neighbors or they're on weak channels.

### "Not connected to any WiFi network"

The `wifi info` command found no active WiFi connection. Connect to a WiFi network first, then run the command again.

### 5 GHz networks show in scan but not in use

Your Mac may not support 5 GHz (older models), or the network's 5 GHz band is not in your region's allowed channels. Check System Settings → Network for your WiFi adapter's capabilities.

### Rogue detection not triggering for a known evil twin

Ensure:
1. You're providing the exact SSID (case-sensitive) and MAC address
2. You're using `--ssid` and `--bssid` in matching pairs
3. The network is in range during the scan
4. MAC addresses are in lowercase format (tool will handle case-insensitively)
