# Wake-on-LAN (WoL)

## What it does

The `wol` tool sends Wake-on-LAN (WoL) magic packets to power on devices remotely. Every network-connected device with WoL support has a network interface that can listen for a special UDP packet while powered down (if properly configured in BIOS/firmware). When netglance detects this packet, the device wakes up.

You can send packets to:
- A specific MAC address directly
- A named device from your netglance inventory
- Any broadcast address (for subnet-directed broadcasts across VLANs)
- Custom UDP ports (default is 9)

This is useful for scheduled device wake-ups, testing network resilience, and managing devices across your home lab.

## Quick start

Send a magic packet to a device by MAC address:

```bash
netglance wol send 00:11:22:33:44:55
```

Wake a device by its inventory name (must exist in discovered devices):

```bash
netglance wol wake my-laptop
```

Send a packet to a specific broadcast address and port:

```bash
netglance wol send 00:11:22:33:44:55 --broadcast 192.168.1.255 --port 7
```

Output as JSON for scripting:

```bash
netglance wol send 00:11:22:33:44:55 --json
```

## Commands

### `netglance wol send`

Send a magic packet directly to a MAC address.

```
netglance wol send <MAC> [options]
```

**Arguments:**
- `MAC` — Target device MAC address. Supports formats: `AA:BB:CC:DD:EE:FF`, `AA-BB-CC-DD-EE-FF`, or `AABBCCDDEEFF`.

**Options:**
- `--broadcast, -b <ADDRESS>` — Broadcast address to send the packet to (default: `255.255.255.255`). Set this to your subnet's broadcast address (e.g., `192.168.1.255`) for subnet-directed broadcasts.
- `--port, -p <PORT>` — UDP destination port (default: `9`). Some devices listen on port 7 instead; try this if the default doesn't work.
- `--json` — Output result as JSON instead of a formatted panel.

**Example:**
```bash
netglance wol send 00:11:22:33:44:55 -b 192.168.1.255 -p 9
```

### `netglance wol wake`

Wake a device by its hostname from the netglance inventory.

```
netglance wol wake <DEVICE_NAME> [options]
```

**Arguments:**
- `DEVICE_NAME` — Device hostname as discovered and stored by netglance. If you haven't run `netglance discover` yet, you'll need to do so to populate the inventory.

**Options:**
- `--broadcast, -b <ADDRESS>` — Broadcast address (default: `255.255.255.255`).
- `--port, -p <PORT>` — UDP port (default: `9`).
- `--json` — Output as JSON.

**Example:**
```bash
netglance wol wake my-laptop --broadcast 192.168.1.255
```

## Understanding the output

### Magic packet structure

A WoL magic packet is a 102-byte UDP datagram containing:
- 6 bytes of `0xFF` (the "preamble")
- 16 repetitions of the target device's 6-byte MAC address

The NIC recognizes this pattern even when the host is powered down, triggering a wake signal to the motherboard.

### Result fields

When you send a packet, netglance returns:

- **Status** — `Sent` (green) if the UDP datagram was successfully transmitted to the network. `Failed` (red) if a socket error occurred.
- **MAC** — The target MAC address.
- **Broadcast** — The broadcast address the packet was sent to.
- **Port** — The UDP port used.
- **Device** — The friendly device name (only shown when using `netglance wol wake`).

**Important:** A "Sent" status means netglance successfully sent the packet to the network. It does **not** guarantee the target device will wake up—that depends on BIOS/firmware configuration, network topology, and firewall rules.

## Related concepts

- **[Discover](discover.md)** — Populate your device inventory with MAC addresses and hostnames. You must run this before using `netglance wol wake`.
- **[Identify](identify.md)** — Assign friendly names to devices in your inventory for easier reference.
- **[Uptime](uptime.md)** — Monitor when devices come online. Pair with WoL to wake a device and then verify it's responding to pings.

## Troubleshooting

### Device doesn't wake up after sending the packet

1. **WoL must be enabled in firmware**
   - Restart the device and enter BIOS/UEFI setup (usually F2, F10, Del, or Esc during boot)
   - Look for "Wake on LAN," "Magic Packet," or "WoL" options
   - Ensure the NIC is powered when the system is off (sometimes labeled "Power from PCI-E" or similar)

2. **Device NIC must support WoL**
   - Older network cards may not support WoL
   - Verify your NIC driver is installed and up-to-date
   - On Linux/Mac, check driver with: `ethtool <interface>` (Linux) or system settings

3. **MAC address is incorrect**
   - Run `netglance discover` to scan your network and confirm the device's actual MAC
   - Verify using `ip link show` (Linux), `ipconfig /all` (Windows), or `ifconfig` (Mac)

### Packet sent but across a routed network

WoL magic packets use broadcast addresses, which don't cross router boundaries by default:

- **Same subnet:** Use the subnet broadcast address (e.g., `192.168.1.255` for a `/24` network). Find your broadcast with `ipcalc` or network scanning tools.
- **Different subnet/VLAN:** Many enterprise routers support **subnet-directed broadcasts** or **directed broadcasts**. Try sending the packet to the target subnet's broadcast address using the `--broadcast` flag.
- **Across the internet:** Standard WoL cannot reach across the public internet. Some routers support WoL over WAN features; consult your router's documentation.

### Port 9 doesn't work, try port 7

The default WoL port is 9, but some devices listen on port 7 instead (the discard port):

```bash
netglance wol send 00:11:22:33:44:55 --port 7
```

If neither works, check your device's WoL documentation or driver settings.

### Firewall blocks the packet

If your local firewall (iptables, nftables, pf) is running, ensure it allows inbound UDP on port 9 (or your custom port) from the broadcast address:

```bash
# Example: Allow WoL on macOS (pf)
sudo pfctl -e  # Enable pf if not already on
echo "pass in quick on en0 proto udp from any to 255.255.255.255 port 9" | sudo pfctl -f -
```

### No devices in inventory for `netglance wol wake`

The `wake` command looks up device hostnames in your netglance database:

```bash
netglance discover  # Scan your network and populate the inventory
netglance identify list  # View discovered devices and their hostnames
netglance wol wake <hostname>  # Now this will work
```

If a device isn't discovered, ensure it's powered on and responding to ARP/mDNS during the scan.
