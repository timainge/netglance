# TLS Certificate Verification

## What it does

The `netglance tls` toolset checks the validity, trustworthiness, and integrity of TLS certificates on your network. It verifies that certificates come from trusted certificate authorities (CAs), detects expiration risks, and can identify potential man-in-the-middle (MITM) interception by comparing certificate fingerprints across vantage points.

## Quick start

Check the default set of well-known sites:
```bash
netglance tls verify
```

Check a specific host:
```bash
netglance tls verify example.com
```

Check a host on a non-standard HTTPS port:
```bash
netglance tls verify example.com --port 8443
```

Save current certificate fingerprints as a baseline:
```bash
netglance tls save
```

Compare current certificates against your saved baseline:
```bash
netglance tls diff
```

Inspect the full certificate details for a host:
```bash
netglance tls chain example.com
```

## Commands

### `netglance tls verify [HOST]`

Verify TLS certificates and check for trusted CAs and potential interception.

**Arguments:**
- `HOST` (optional): Hostname to check. If omitted, checks a default list of well-known sites (google.com, github.com, cloudflare.com, amazon.com, microsoft.com).

**Options:**
- `--port, -p`: TCP port to connect to (default: `443`)

**Output:** A table showing host, issuer, root CA, fingerprint (truncated), and trust status (TRUSTED, UNTRUSTED, or INTERCEPTED). Below the table, detailed status messages explain the result for each host.

### `netglance tls save`

Save the current certificate fingerprints for the default host list as a baseline for future comparison.

**Options:**
- `--db` (hidden): Override the default database path. Normally uses `~/.config/netglance/netglance.db`.

**Output:** Confirmation message with the number of hosts saved.

### `netglance tls diff`

Compare current certificate fingerprints against your saved baseline. Useful for detecting certificate changes, which may indicate MITM interception or legitimate certificate renewal.

**Options:**
- `--db` (hidden): Override the default database path.

**Output:** A table showing each host, its comparison status (match, CHANGED, or new), and the old/new fingerprints (truncated for readability).

### `netglance tls chain HOST`

Display detailed certificate information (subject, issuer, root CA, fingerprint, validity dates, SANs, chain length, and trust status).

**Arguments:**
- `HOST` (required): Hostname to inspect.

**Options:**
- `--port, -p`: TCP port (default: `443`)

**Output:** A two-column table with certificate fields and their values.

## Understanding the output

### Status indicators

- **[green]TRUSTED[/green]**: Certificate comes from a well-known, trusted CA and is currently valid.
- **[yellow]UNTRUSTED[/yellow]**: Certificate issuer is unknown or the certificate is invalid/expired.
- **[red]INTERCEPTED[/red]**: Certificate is signed by an unknown CA, suggesting potential MITM interception (e.g., corporate firewall inspection).

### Certificate fields

- **Subject**: The hostname or entity the certificate was issued for (Common Name).
- **Issuer**: The organization or entity that issued the certificate.
- **Root CA**: The root certificate authority in the chain. netglance checks this against a list of ~60 well-known, public CAs.
- **Fingerprint (SHA-256)**: A hash-based identifier unique to this certificate. If the fingerprint changes unexpectedly, it may indicate certificate replacement or interception.
- **Not Before / Not After**: The certificate's validity window (issued date and expiration date).
- **SAN (Subject Alternative Names)**: Additional hostnames the certificate covers (e.g., for wildcard or multi-domain certificates).
- **Chain Length**: The number of certificates in the full chain (netglance currently reports the leaf certificate; full chain inspection is planned).

### Comparison status (diff command)

- **match**: Fingerprint is identical to the baseline. Certificate has not changed.
- **CHANGED**: Fingerprint differs from the baseline. Certificate was renewed or replaced.
- **new**: Host was not in the baseline. First time seeing this certificate.

## Related concepts

- [TLS and Certificates](../../guide/concepts/tls-and-certificates.md) — Overview of certificate structure, trust models, and how MITM detection works.
- [HTTP Tool](./http.md) — Inspect HTTP headers and detect proxies that may be intercepting traffic.
- [VPN & Routing](./route.md) — Verify that traffic is taking the expected network path.

## Troubleshooting

### Self-signed certificates appear as UNTRUSTED

This is expected. Self-signed certificates (issued by the host itself, not a public CA) are not in netglance's trusted CA list and will show as UNTRUSTED or INTERCEPTED. If you trust a self-signed certificate (e.g., a local lab server), you can safely ignore the warning. To permanently trust it, add its root CA organization to the `TRUSTED_ROOT_CAS` set in `netglance/modules/tls.py`.

### Corporate firewall shows INTERCEPTED

Many corporate firewalls, proxies, and DLP systems perform SSL/TLS inspection by issuing their own certificates signed by a corporate CA. This is expected and normal in that environment. netglance will flag it as INTERCEPTED because the certificate is signed by a private CA, not a public one. If you're on a corporate network and expect this, you can safely ignore the flag.

### Certificate verification failed (connection error)

If you see "Certificate verification failed" or "Connection error," check:
- The hostname is correct and reachable from your network.
- The port is correct (standard HTTPS is 443; some services use 8443 or other ports).
- There is no firewall blocking outbound HTTPS connections.
- DNS resolution is working (try `netglance dns lookup example.com` first).

### SNI (Server Name Indication) errors

If a host hosts multiple TLS certificates on the same IP address, it relies on Server Name Indication (SNI) in the TLS handshake to serve the correct certificate. netglance sends the hostname via SNI, so this should work automatically. If you still see certificate mismatches, the server may not support SNI or may be misconfigured.

### Fingerprint changes after renewal

Certificates are renewed (issued anew) before expiration. The new certificate will have a different fingerprint than the old one. This is normal. Update your baseline by running `netglance tls save` after a renewal.
