---
title: Disclaimer
---

# Disclaimer

netglance is **experimental software in active development**. It is provided as-is, with no warranties of any kind.

## What this means

- **No guarantees.** Features may be incomplete, behave unexpectedly, or change without notice.
- **Not a security product.** netglance can help you observe your network, but it is not a substitute for professional security tools, firewalls, or intrusion detection systems. Do not rely on it to protect your network.
- **Use at your own risk.** Some operations (port scanning, packet capture, ARP monitoring) interact directly with your network. Running them on networks you don't own or without permission may violate laws or policies.
- **No liability.** The authors are not responsible for any damage, data loss, network disruption, or other consequences arising from the use of this software.

## Permissions and privileges

Several netglance features require elevated privileges (`sudo`) to function — for example, ARP scanning, DHCP monitoring, and packet capture. Granting root access to any software carries inherent risk. Review what you're running before escalating.

## Accuracy

Network analysis results are best-effort. False positives and false negatives are possible. Always verify findings independently before taking action, especially for security-related checks like ARP spoofing detection or rogue DHCP server alerts.

## Open source

netglance is open source under the MIT licence. You are free to inspect the code, report issues, and contribute. The source is available at [github.com/timainge/netglance](https://github.com/timainge/netglance).
