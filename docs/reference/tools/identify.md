# Device Identification

The `identify` command fingerprints devices on your network using multiple signals: MAC address vendor lookup, mDNS services, UPnP device descriptions, open ports, and hostnames. It combines these signals to classify each device by type and confidence.

## What it does

Device fingerprinting collects clues from multiple sources and synthesizes them into a single identification profile:

- **MAC OUI lookup** — identifies the hardware vendor from the MAC address
- **mDNS/Bonjour browsing** — discovers advertised services (AirPlay, HomeKit, printers, etc.)
- **UPnP M-SEARCH** — finds UPnP devices and fetches device descriptions
- **Open port signatures** — matches known port combinations to device types
- **Hostname patterns** — regex-based classification (iPhone, DESKTOP-, ESP_, etc.)
- **Randomized MAC detection** — warns when a device uses a locally-administered address

Classification priority: UPnP > mDNS > open ports > hostname > MAC vendor.

## Quick start

Fingerprint all devices on your subnet:
```bash
netglance identify
```

Fingerprint a single IP in detail:
```bash
netglance identify 192.168.1.42
```

Scan a different subnet:
```bash
netglance identify --subnet 10.0.0.0/24
```

Label a device with a friendly name:
```bash
netglance identify 192.168.1.42 --label "Living Room Alexa"
```

Show only unidentified devices:
```bash
netglance identify --unknown
```

Output as JSON:
```bash
netglance identify --json
```

## Commands

### Main command: `identify`

Fingerprint and identify network devices.

**Arguments:**
- `IP` (optional) — Fingerprint a single device at this IP address. Omit to scan all devices on the subnet.

**Options:**
- `--subnet`, `-s` — Subnet to scan (default: `192.168.1.0/24`)
- `--unknown` — Show only devices that could not be classified
- `--label TEXT` — Assign a user-friendly label to a device (requires `IP`)
- `--type TEXT` — Assign a device type category to a device (requires `IP`)
- `--json` — Output results in JSON format
- `--db PATH` — Database path override (hidden, for advanced use)

## Understanding the output

### Table columns

**IP** — Device IP address on the network

**MAC** — Media Access Control address (hardware identifier)

**Type** — Inferred device category. Common types include:
- `smartphone`, `tablet`, `laptop`, `desktop` — personal computers
- `router`, `gateway`, `switch` — network infrastructure
- `printer`, `scanner` — office devices
- `camera`, `media` — entertainment and surveillance
- `iot` — general IoT devices (smart lights, plugs, sensors)
- `server` — always-on services (NAS, Raspberry Pi, etc.)
- `unknown` — device type could not be determined

**Manufacturer** — OUI vendor name from the MAC address, or extracted from UPnP

**Name** — User-assigned label, UPnP friendly name, or device hostname

**Confidence** — How certain the classification is (0–100%):
- **Green** (80%+) — high confidence
- **Yellow** (50–79%) — moderate confidence
- **Red** (<50%) — low confidence; treat as a guess

**Method** — Signal source for the classification:
- `upnp` — UPnP device description
- `mdns` — mDNS service type (Bonjour)
- `ports` — open port signature
- `hostname` — device hostname pattern
- `mac_vendor` — MAC address OUI
- `--` — no classification achieved

### Single-device fingerprint details

When you identify a single IP, the output includes additional details below the summary table:

```
mDNS services: _homekit._tcp, _airplay._tcp
UPnP device: Apple TV
  Manufacturer: Apple Inc.
  Model: TVML
Warning: MAC appears to be randomized (locally administered)
```

**Randomized MAC warning** — indicates privacy-mode MAC spoofing (common on modern iPhones, laptops). A randomized MAC reduces fingerprinting accuracy since vendor lookup fails.

## Related concepts

- **[Discovery](./discover.md)** — Finding devices on your network first. The `identify` command uses ARP discovery internally.
- **[Scanning](./scan.md)** — Port scanning identifies open ports for signature matching. Run a separate port scan for more granular data.
- **[Baseline](./baseline.md)** — Snapshots your network state (devices + profiles). Use this to track how device identifications change over time.

## Troubleshooting

**No devices found:**
- Make sure the `--subnet` matches your network. Run `netglance discover` first to verify your network configuration.
- mDNS and UPnP services may not be available on all networks (especially guest Wi-Fi or heavily firewalled networks).

**"Unknown" classification despite visible mDNS services:**
- Some devices advertise mDNS services but not through standard types. Check the raw `--json` output for the `mdns_services` array.
- Open port signatures are incomplete for newer or niche devices. Consider labeling the device manually with `--label`.

**MAC shown as randomized:**
- Many modern devices (iPhones, MacBooks, Android 10+) rotate MAC addresses for privacy. Fingerprinting still works via other signals (mDNS, UPnP), but OUI lookup won't work.
- If a device refuses all fingerprinting methods, the only reliable identifier is its IP + hostname.

**Timeout or slow fingerprinting:**
- mDNS and UPnP scans wait up to 5 seconds each per device. Slow networks or many devices will take longer.
- Run fingerprinting during low-traffic times if possible.

**Confidence is low for a device type you know:**
- Add more signals: run a separate port scan (`netglance scan IP`) to get open ports, then `identify` will cross-reference port signatures.
- Manually label the device with `--label` and `--type` to provide a ground truth for future scans.
