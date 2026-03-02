# Common Findings

This page explains 20 of the most common findings netglance reports, what they mean, and what to do about them. Findings are organized by module category.

## Device Discovery

### New unknown device detected

**Module:** Discovery
**Severity:** ⚠️ Warn
**What it means:** netglance found a device on your network that wasn't present in the previous baseline. The device has an unfamiliar hostname or MAC vendor.

**What to do:**
1. Check your baseline file to confirm this device wasn't previously recorded.
2. Physically identify the device (check connected phones, laptops, smart home devices, guest devices).
3. If it's a known household device, update your baseline and add it to a known devices list.
4. If unknown and suspicious, unplug the device and monitor for its reappearance.

---

### Device disappeared from network

**Module:** Discovery
**Severity:** ℹ️ Info
**What it means:** A device that was in your previous baseline is no longer responding to discovery probes (ARP, mDNS, UPnP).

**What to do:**
1. Confirm the device is still on the network (is it powered on? connected to WiFi?).
2. Check if the device changed IP address or switched to a different network interface.
3. If the device is intentionally offline, update your baseline.
4. For always-on devices (servers, NAS), investigate why they're not responding.

---

### Device with randomized MAC address detected

**Module:** Discovery
**Severity:** ⚠️ Warn
**What it means:** A device is using a randomized MAC address, often for privacy. This makes it harder to track the device reliably across scans.

**What to do:**
1. Check your phone or laptop settings—many devices enable MAC randomization by default on WiFi.
2. If this is intentional privacy behavior, note it in your baseline to reduce future warnings.
3. For critical devices, consider disabling MAC randomization in settings for consistent tracking.

---

## DNS & Resolution

### DNS inconsistency detected

**Module:** DNS
**Severity:** ⚠️ Warn
**What it means:** Queries to the same hostname from different resolvers (your router, ISP, or public DNS like 8.8.8.8) returned different IP addresses. This can indicate DNS hijacking or inconsistent DNS configuration.

**What to do:**
1. Note which resolvers disagreed and for which hostnames.
2. Check your router's DNS settings—ensure all devices use the same resolvers.
3. If using multiple resolvers intentionally, verify they're all legitimate (not ISP injected).
4. Consider switching to a single public resolver (8.8.8.8, 1.1.1.1, or Quad9) to avoid conflicts.

---

### DNS leak detected

**Module:** DNS
**Severity:** 🔴 Fail
**What it means:** DNS queries from a device or VPN tunnel were sent to an unexpected resolver, bypassing your configured DNS settings. Often indicates a misconfigured VPN or device not respecting system DNS settings.

**What to do:**
1. Identify which device or application is leaking queries.
2. If using a VPN, check that it's configured to force all DNS through the VPN tunnel.
3. On the device, manually set DNS to the expected resolver (iPhone/Android Settings, Windows Control Panel, macOS System Preferences).
4. Restart the device or VPN client and re-run netglance to confirm.

---

### Slow DNS resolution

**Module:** DNS
**Severity:** ⚠️ Warn
**What it means:** DNS queries are taking longer than expected (typically >100ms). This can indicate a slow resolver, network congestion, or high load on your DNS infrastructure.

**What to do:**
1. Test your current DNS resolver directly: `dig google.com @<resolver-ip>` and note the query time.
2. Try switching to a fast public resolver: `8.8.8.8` (Google), `1.1.1.1` (Cloudflare), or `9.9.9.9` (Quad9).
3. Check if your router or Pi-hole is under high load (monitor CPU/memory).
4. If using a local DNS filter (Pi-hole, AdGuard), verify it's not overloaded with requests.

---

## TLS & Certificates

### Certificate expiring soon

**Module:** TLS
**Severity:** ⚠️ Warn
**What it means:** A TLS certificate on a device or service will expire within 30 days. After expiration, browsers and clients will refuse to connect.

**What to do:**
1. Identify the device or service with the expiring certificate (e.g., home lab server, NAS, router admin interface).
2. Renew the certificate before the expiration date. Many services auto-renew; check settings.
3. For self-hosted services, use Let's Encrypt (via certbot or similar) for free, auto-renewing certificates.
4. Mark the renewal date in your calendar if the service doesn't auto-renew.

---

### Self-signed certificate detected

**Module:** TLS
**Severity:** ℹ️ Info
**What it means:** A device is using a self-signed certificate (not issued by a trusted Certificate Authority). This is common for home lab devices and routers, but browsers will warn about it.

**What to do:**
1. Confirm the device is one you control (router, NAS, home server).
2. If you want to avoid browser warnings, generate a proper certificate from a trusted CA (Let's Encrypt is free).
3. For internal-only devices, self-signed is acceptable—just add the certificate to your trusted store if needed.
4. If this certificate appeared unexpectedly, investigate the device to ensure it wasn't compromised.

---

### Expired certificate

**Module:** TLS
**Severity:** 🔴 Fail
**What it means:** A TLS certificate has passed its expiration date. Clients will refuse to connect, and the service is inaccessible via HTTPS.

**What to do:**
1. Immediately identify and access the affected device (SSH, local console, web admin panel).
2. Renew or replace the certificate with a valid one.
3. Restart the affected service to load the new certificate.
4. Clear browser cache if you've seen the old certificate (browser may cache the warning).

---

## Port Scanning & Services

### Open SSH (port 22) on unexpected device

**Module:** Scan
**Severity:** 🔴 Fail
**What it means:** A device has SSH listening on port 22, which wasn't expected. SSH access can allow remote command execution if the device is compromised or has weak credentials.

**What to do:**
1. Confirm this is a device you administer (home server, NAS, Raspberry Pi).
2. If it's a new device, verify you intentionally enabled SSH.
3. If this device shouldn't have SSH, disable it in the device's settings.
4. Ensure the device has a strong password or uses key-based authentication.
5. Consider restricting SSH access to your local network only (disable remote access from the internet).

---

### Open HTTP/HTTPS on IoT device

**Module:** Scan
**Severity:** ⚠️ Warn
**What it means:** An IoT device (camera, smart plug, thermostat) is running an unencrypted HTTP web interface (port 80) or has an HTTPS interface (port 443) accessible from the network.

**What to do:**
1. Access the device's settings and check for an option to disable web access or switch to HTTPS-only.
2. Verify the device has a strong password (not factory defaults like admin/admin).
3. If the web interface is not needed, disable it entirely.
4. Consider isolating IoT devices on a separate WiFi network (guest network) to limit lateral movement if compromised.

---

### Previously closed port now open

**Module:** Scan
**Severity:** ⚠️ Warn
**What it means:** A port that was closed in your previous baseline is now open on a device. This could indicate new software, a misconfiguration, or unauthorized access.

**What to do:**
1. Identify which device and port changed.
2. Check if you or another household member installed new software recently.
3. SSH into the device and verify the listening service: `sudo netstat -tulpn | grep LISTEN`
4. If you don't recognize the service, research it or disable it.
5. Update your baseline to reflect intentional changes.

---

## Wireless (WiFi)

### WPA2 instead of WPA3

**Module:** WiFi
**Severity:** ⚠️ Warn
**What it means:** Your WiFi network is using WPA2 encryption instead of the newer WPA3. WPA2 is still secure for home use, but WPA3 offers better protection against modern attacks.

**What to do:**
1. Check your router's WiFi settings.
2. If your router supports WPA3, enable it (may be labeled "WPA3" or "WPA2/WPA3 mixed" mode).
3. Reconnect all devices to the network—most modern devices support WPA3.
4. For older devices that don't support WPA3, use a mixed mode temporarily while you upgrade those devices.

---

### Channel congestion or overlap with neighbors

**Module:** WiFi
**Severity:** ⚠️ Warn
**What it means:** Your WiFi channel overlaps with nearby networks, causing interference and reducing your signal strength. Common on 2.4 GHz band where only channels 1, 6, and 11 don't overlap.

**What to do:**
1. Scan nearby networks: use your router's web interface or an app like WiFi Analyzer.
2. On 2.4 GHz, switch to channel 1, 6, or 11 (whichever has the least interference).
3. On 5 GHz (80+ channels available), switch to a less congested channel.
4. Reboot your router after changing channels.
5. Test connectivity and speed after the change.

---

### Open (unencrypted) WiFi network detected

**Module:** WiFi
**Severity:** 🔴 Fail
**What it means:** A WiFi network is broadcasting without encryption. This is likely a neighbor's network (not yours), but could indicate a serious misconfiguration.

**What to do:**
1. Confirm this is not your own network—check your router's settings to ensure encryption is enabled.
2. If it's a neighbor's open network, inform them of the security risk (optional, but helpful).
3. If it's your network, immediately enable WPA2 or WPA3 encryption in your router settings.
4. Set a strong WiFi password (at least 16 characters with mixed case, numbers, and symbols).

---

## ARP & IP

### ARP spoofing detected

**Module:** ARP
**Severity:** 🔴 Fail
**What it means:** netglance detected conflicting ARP responses for the same IP address or MAC address. This is a sign of ARP spoofing, where an attacker is impersonating another device.

**What to do:**
1. Check if any devices on your network have duplicate IP addresses (DHCP misconfiguration).
2. If using static IPs, verify no two devices have the same IP.
3. Enable ARP binding or DHCP snooping on your router to prevent spoofing.
4. If the network is small and trusted, ARP spoofing risk is low—monitor for suspicious traffic.
5. Consider enabling a local ARP firewall or static ARP entries for critical devices.

---

### Duplicate IP address on network

**Module:** ARP
**Severity:** 🔴 Fail
**What it means:** Two devices are responding to the same IP address. This causes packet loss and network instability.

**What to do:**
1. Identify which devices have the conflicting IP (check router's DHCP client list or use `arp -a`).
2. If one device has a static IP, find and release it in the device's network settings.
3. If both are using DHCP, restart the router to reset the DHCP pool.
4. Assign static IPs to critical devices to prevent future conflicts.

---

## Connectivity & Traffic

### High jitter detected

**Module:** Ping
**Severity:** ⚠️ Warn
**What it means:** Latency to a device varies widely between pings (high standard deviation). This causes problems for VoIP, gaming, and video conferencing.

**What to do:**
1. Check for network congestion—run a bandwidth monitor during the warning.
2. If on WiFi, move closer to the router or switch to 5 GHz if available.
3. If on wired, check the cable connection and switch to Ethernet if possible.
4. Look for background downloads, backups, or other heavy network usage.
5. If the issue persists, your ISP connection may be unstable—contact them.

---

### IPv6 leak detected

**Module:** Traffic
**Severity:** ⚠️ Warn
**What it means:** Your device is leaking traffic over IPv6, even though you intended to use IPv4 only. Common when using a VPN that doesn't properly block IPv6.

**What to do:**
1. If using a VPN, check that it supports and enforces IPv6 blocking.
2. On your device, disable IPv6 if it's not needed (Settings > Network > IPv6 > Disabled).
3. If you need IPv6, ensure your VPN provider has a proper IPv6 configuration.
4. Re-run netglance to confirm the leak is closed.

---

## System & Integration

### DHCP rogue server detected

**Module:** Scan (DHCP probes)
**Severity:** 🔴 Fail
**What it means:** A device other than your router responded to a DHCP discovery request. A rogue DHCP server can redirect traffic or assign incorrect gateway IPs.

**What to do:**
1. Disable DHCP on any secondary routers, access points, or devices accidentally running DHCP.
2. Check your router's logs for unauthorized DHCP assignments.
3. Use DHCP snooping on your router to block unauthorized DHCP servers.
4. If you can't identify the rogue server, isolate devices one by one until the responses stop.

---

### Baseline drift detected

**Module:** Baseline
**Severity:** ℹ️ Info / ⚠️ Warn
**What it means:** Your network state has changed significantly since the last baseline (devices added/removed, ports changed, DNS settings differ). This isn't necessarily bad, but indicates your baseline is outdated.

**What to do:**
1. Review the reported changes to confirm they're intentional (new device, upgraded router, etc.).
2. If changes are legitimate, create a new baseline: `netglance baseline create --name "post-upgrade"`.
3. If changes are unexpected, investigate before updating the baseline.
4. Keep named baselines for different network configurations (e.g., "before-router-upgrade", "after-port-forwarding").
