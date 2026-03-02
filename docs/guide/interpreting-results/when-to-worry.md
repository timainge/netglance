# When to Worry

netglance reports findings across many modules—device discovery, DNS, ports, ARP, certificates, and more. Not all findings demand urgent action. This guide helps you triage what requires immediate attention, what needs investigation, and what you can safely ignore.

## Triage Matrix

| Tier | Response Time | Action | Examples |
|------|---|---|---|
| **Critical** | Act now | Verify immediately, then contain or remediate | ARP spoofing, rogue DHCP, unknown device, DNS hijacking, new open ports |
| **Investigate** | Within 24 hours | Gather context, check logs, understand cause | Certificate warnings, baseline drift, latency spikes, WiFi interference |
| **Informational** | Note and move on | No action needed unless patterns emerge | Self-signed certs, filtered ports, mDNS traffic, WPA2 on old devices |

---

## Critical Findings — Act Immediately

These findings indicate active compromise, imminent risk, or a security incident in progress.

### ARP Spoofing Detected

**What it means**: Someone or something on your network is sending fake ARP packets claiming to be another device. This is a classic MITM (man-in-the-middle) attack setup.

**What to do**:
1. Run `netglance arp --full` to see which device is doing the spoofing and which device(s) are being spoofed.
2. Physically locate the spoofing device (check your router's connected devices list).
3. If it's your own device, you may have network utilities installed. If it's unknown, isolate it: disconnect it from WiFi or unplug the ethernet cable.
4. Run the ARP check again to confirm spoofing stops.
5. If the device reappears after disconnection, it may be an intruder. Escalate (see "When to escalate" below).

### Rogue DHCP Server

**What it means**: A device other than your router is assigning IP addresses. Attackers use this to redirect traffic or hand out DNS servers pointing to a malicious server.

**What to do**:
1. Reboot your router to reset its DHCP scope.
2. Run `netglance discover` to see all devices and their IP assignments.
3. If netglance reports a second DHCP server, it's still active. Check which device it is.
4. Disconnect that device immediately.
5. Check your router's logs if available (most home routers don't have detailed logs, but it's worth checking).

### Unknown Devices on the Network

**What it means**: A device is connected (via WiFi or ethernet) that you don't recognize.

**What to do**:
1. Check the device's MAC address: `netglance discover --by-mac` shows vendor info.
2. Cross-reference against your own devices: new phone? guest laptop? smart speaker?
3. If you recognize the vendor (e.g., "Apple Inc.") but not the specific device, ask household members if they brought a device over.
4. If you don't recognize it and can't explain it, **isolate it immediately**: kick it off WiFi via your router's admin panel, or unplug ethernet.
5. Run `netglance discover` again in 5 minutes. If it reappears, it's actively trying to reconnect. This warrants escalation.

### DNS Queries Redirected to Unexpected Servers

**What it means**: Your DNS queries are being answered by a server other than the one you configured (your ISP, 1.1.1.1, 8.8.8.8, etc.).

**What to do**:
1. Run `netglance dns --check-resolvers` to see which DNS servers are handling your queries.
2. Compare to your configuration: check your router's DNS settings and your OS network settings.
3. If you see a resolver you didn't set up, check if it's your ISP's secondary resolver (many ISPs run multiple DNS servers).
4. If it's truly unexpected, restart your router and check again.
5. If an unknown resolver persists, your DNS may be hijacked. Escalate immediately.

### New Open Ports on Previously Scanned Devices

**What it means**: A device that previously had no open ports (or a known set) now has new ones. This could indicate compromised software, a rogue service, or legitimate new software.

**What to do**:
1. Run `netglance scan --host <device-ip>` to confirm the port is really open and see what service claims it.
2. Check the device's recent activity: Did you install new software? Did the OS update? Did you enable a service?
3. If you can't explain it, check the device's own logs for new processes.
4. If the port is running unknown software and the device is compromised or unusual, consider reimaging or isolation.

---

## Investigate Findings — Look Closer Within 24 Hours

These findings often have benign explanations but warrant context gathering.

### Unexpected DNS Resolution Failures

**What it means**: Queries to some domains are failing or timing out.

**What to do**:
1. Try the lookup manually: `nslookup example.com` from your computer.
2. Try from a different device to rule out per-device issues.
3. Try with a public resolver: `nslookup example.com 8.8.8.8` to see if your ISP's DNS is the problem.
4. Check if the domain exists and is resolvable (use `dig` or an online tool).
5. If netglance shows failures on internal .local domains, check if your mDNS responder is running (usually automatic on modern systems).

### Certificate Warnings on Internal Services

**What it means**: A service (your router, NAS, printer, home automation hub) is using a self-signed or expired certificate.

**What to do**:
1. Determine if the certificate is self-signed (normal for internal devices) or actually expired (check the expiry date).
2. If expired, restart the device—many devices generate new certs on boot.
3. If it's self-signed and expected (your own NAS or router), you can safely ignore it.
4. If you didn't set up this service and the certificate is suspicious, investigate further (see false positives section below).

### Baseline Drift — New Services Detected

**What it means**: Your network has new devices or services that weren't there before.

**What to do**:
1. Review what changed: Did you buy a new device? Did an OS update start a new service?
2. Check your baseline snapshots: `netglance baseline --list` shows history.
3. If you can't explain it, check your devices' update history and installation logs.
4. If drift is concerning, create a new baseline after confirming all changes are legitimate: `netglance baseline --capture`.

### WiFi Channel Interference

**What it means**: Your WiFi network is competing with neighbors' networks on the same or adjacent channels, degrading throughput.

**What to do**:
1. Run `netglance wifi --interference` to see competing SSIDs and their channels.
2. Log into your router and check your current channel.
3. Try switching to a less-congested channel (usually 1, 6, or 11 for 2.4 GHz; any channel for 5 GHz, which has more bandwidth).
4. Rerun the WiFi analysis after a few minutes to see if throughput improves.
5. If interference persists, your neighbors' routers are there to stay—this is informational unless performance is unacceptable.

### Elevated Latency or Packet Loss

**What it means**: Network responses are slower than expected or some packets aren't getting through.

**What to do**:
1. Run `netglance ping --verbose` to see latency to your gateway and common endpoints (1.1.1.1, 8.8.8.8).
2. Run it multiple times over a few minutes—latency can be temporary.
3. Check if one specific device or path has high latency (use `netglance route --trace <destination>`).
4. Look for patterns: Is it always slow, or only to certain destinations? Only on WiFi?
5. If it's WiFi-specific, move closer to the router or switch to 5 GHz (if available).
6. If it's to external destinations, it's usually your ISP. Contact them if it persists.

---

## Informational Findings — Usually Safe to Ignore

These findings are normal on home networks and rarely indicate a problem.

### Self-Signed Certificates on Internal Devices

**What it means**: Your router, NAS, printer, smart TV, or other local device uses a certificate it generated itself instead of one from a certificate authority.

**Why it's normal**: Home devices don't need CA-signed certificates. They generate their own for HTTPS access and are verified by checking the fingerprint, not the signer.

**When to care**: Only if the certificate is expired (check its expiry date) or you didn't set up the device that's using it.

### Filtered (Not Open) Ports on Port Scans

**What it means**: A port is closed or blocked by a firewall, not open.

**Why it's normal**: Filtering is the default secure behavior. Only deliberately exposed ports (SSH, HTTP, etc.) should be open.

**When to care**: Never. Filtered ports are good news—they're not responding to unsolicited traffic.

### mDNS and Bonjour Traffic

**What it means**: Apple devices (and some Android/Linux devices) are announcing themselves and discovering services via .local domains.

**Why it's normal**: This is how modern devices discover printers, AirPlay speakers, and each other on a home network.

**When to care**: Never. This is expected background noise on modern networks.

### Minor DNS Response Time Variations

**What it means**: DNS lookups sometimes take 10 ms, sometimes 50 ms.

**Why it's normal**: DNS caching, network congestion, and resolver load cause small timing variations.

**When to care**: Only if response times spike to seconds (which indicates a real problem).

### WPA2 (Not WPA3) on Older Devices

**What it means**: Your router or some devices support only WPA2, not the newer WPA3 encryption.

**Why it's normal**: WPA3 is new. Older devices don't support it, and many home routers still run WPA2.

**When to care**: You should upgrade if possible for better security, but WPA2 is still secure for home networks. Don't worry unless you're on WPA (not WPA2), which is deprecated.

---

## False Positive Patterns

### New Device = Your Own New Device

**Scenario**: netglance reports a new device, you think it's an intruder.

**Reality**: You just bought a new phone, laptop, smart speaker, or game console.

**How to confirm**: Check the device's MAC vendor. If it says "Apple Inc." or "Samsung Electronics," it's likely yours. Ask household members. Check when the device first appeared (use baseline timestamps).

**To suppress**: Create a baseline after you verify the device is yours so future reports ignore it as new.

### ARP Changes After Router Reboot

**Scenario**: netglance detects "ARP spoofing" shortly after you restart your router.

**Reality**: Devices are reconnecting. ARP tables are being rebuilt. This is normal churn.

**How to confirm**: Run the check again 5–10 minutes later. If it disappears, it was false alarm. Run the check several times over an hour to see if the same device is spoofing consistently or if it was a one-time detection.

### Port Changes After OS Update

**Scenario**: A previously closed port is now open.

**Reality**: An OS update enabled a service (printer sharing, remote access, etc.) that you didn't explicitly turn on.

**How to confirm**: Check your OS's service list. On macOS: `launchctl list | grep service-name`. On Linux: `systemctl list-units --type=service`. On Windows: Services app.

### DNS "Leak" That's Actually Correct

**Scenario**: netglance reports that your DNS queries are going to 8.8.8.8, but you configured your ISP's resolver.

**Reality**: Your ISP's resolver is forwarding your queries to Google's public DNS (common practice). This is not a leak.

**How to confirm**: Trace the query: `dig +trace example.com` shows the resolver chain. If your ISP's resolver appears, they're the one forwarding to Google, not a third party.

---

## When to Escalate

Contact professional help (IT security, your ISP, or local law enforcement) if you see:

- **Persistent unknown devices** that reappear after you disconnect them, especially if they keep trying to reconnect.
- **Confirmed ARP spoofing from a device you don't own** and can't physically locate.
- **Evidence of DNS hijacking** (queries redirected to truly unknown servers that persist after reboots).
- **Unexplained outbound traffic spikes** (high bandwidth to unknown destinations) detected over time.
- **Multiple simultaneous findings** (unknown device + ARP spoofing + certificate warnings) that suggest coordinated compromise.

Most home network security incidents are much rarer than findings suggest. Use this guide to separate signal from noise, and trust your instincts—if something feels wrong, it probably warrants investigation.
