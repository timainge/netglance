# DNS Health

> Verify that your DNS resolvers are healthy, fast, consistent, and not being hijacked.

## What it does

DNS translates human-readable domain names (like `example.com`) into IP addresses that your devices can connect to. Your router or ISP provides DNS resolvers, or you can use public resolvers like Google, Cloudflare, or Quad9. If your DNS isn't working properly, nothing on the internet will work.

The **DNS Health** tool runs five key checks on your configured resolvers:

1. **Resolver health** — Does each resolver respond? How fast?
2. **Consistency** — Do different resolvers agree on the same answers? Disagreement can signal hijacking.
3. **DNSSEC validation** — Does your resolver validate DNSSEC signatures to detect tampering?
4. **DNS hijacking** — Is something intercepting or rewriting your DNS queries?
5. **Resolver benchmarking** — Which resolver is fastest for your network?

Use this tool when you suspect DNS problems (slow internet, inability to reach certain sites), want to verify your resolver setup, or check whether your ISP is tampering with DNS.

## Quick start

**Check the health of your default resolvers:**
```bash
netglance dns check example.com
```

**Benchmark three major public resolvers:**
```bash
netglance dns benchmark
```

**Check for DNS hijacking (are query results being intercepted?):**
```bash
netglance dns hijack
```

**Resolve a domain across all configured resolvers:**
```bash
netglance dns resolve google.com
```

**Add a custom resolver to any check:**
```bash
netglance dns check example.com --resolver 208.67.222.222
```

## Commands

### `netglance dns check`

Run all DNS health checks for a domain.

**Arguments:**
- `domain` — Domain to check (default: `example.com`)

**Options:**
- `--resolver`, `-r` — Extra resolver IP (can be used multiple times to add custom resolvers)

**Example:**
```bash
netglance dns check google.com -r 208.67.222.222 -r 1.0.0.1
```

### `netglance dns resolve`

Resolve a domain across multiple resolvers and display results.

**Arguments:**
- `domain` — Domain to resolve (required)

**Options:**
- `--resolver`, `-r` — Extra resolver IP (can be used multiple times)

**Example:**
```bash
netglance dns resolve cloudflare.com --resolver 8.8.4.4
```

### `netglance dns benchmark`

Benchmark resolver response times by querying multiple public resolvers against a standard set of domains (`example.com`, `google.com`, `cloudflare.com`).

**Options:**
- `--resolver`, `-r` — Extra resolver IP to include in benchmark (can be used multiple times)

**Example:**
```bash
netglance dns benchmark -r 1.1.1.1 -r 9.9.9.9
```

### `netglance dns hijack`

Check for DNS hijacking by querying a canary domain that should never resolve. If any resolver returns an answer for this non-existent domain, it indicates DNS interception.

**Options:**
- `--resolver`, `-r` — Extra resolver IP (can be used multiple times)

**Example:**
```bash
netglance dns hijack -r 192.168.1.1
```

## Understanding the output

### DNS Health Check (`dns check`)

The `dns check` command outputs:

- **Resolvers checked** — How many resolvers were queried
- **Consistency** — `CONSISTENT` (green) or `INCONSISTENT` (red). All resolvers should return the same answers for the same domain.
- **Fastest resolver** — Which resolver answered quickest (e.g., `Cloudflare (1.1.1.1)`)
- **DNSSEC supported** — `Yes` (green) if the resolver validates DNSSEC signatures, `No` (yellow) otherwise
- **Potential hijack** — `No` (green) or `YES` (red). Flagged when resolvers give conflicting answers.

The detailed table shows:
- **Resolver** — IP address
- **Name** — Human-friendly name (Cloudflare, Google, Quad9, etc.)
- **Answers** — IP address(es) returned, or `-` if the domain doesn't exist
- **Time (ms)** — Response time in milliseconds
- **Error** — Any error (`NXDOMAIN`, `Timeout`, `NoAnswer`, etc.)

### DNS Benchmark (`dns benchmark`)

Shows response times for three standard test domains queried against each resolver:

- **Resolver / Name / Domain** — Which resolver answered which query
- **Time (ms)** — How long the query took
- **Error** — Any error encountered

Below the table, an **Average response times** summary ranks resolvers by speed.

### DNS Hijack Detection (`dns hijack`)

Attempts to resolve a non-existent canary domain (`this-domain-should-not-exist-netglance.example.invalid`):

- **OK** (green) — Resolver correctly returned `NXDOMAIN` (domain doesn't exist)
- **HIJACKED** (red) — Resolver returned an answer for a domain that shouldn't exist; DNS is being intercepted
- **Error** (yellow) — Timeout, network error, or other issue

### What Good vs Bad Looks Like

**Green (healthy DNS):**
- Consistency: `CONSISTENT`
- Potential hijack: `No`
- DNSSEC supported: `Yes`
- All resolvers respond with the same answers
- Response times under 50 ms
- Hijack check: all resolvers show `OK`

**Yellow (minor issues):**
- DNSSEC not supported (resolver doesn't validate DNSSEC)
- Some resolvers slower than others (50–200 ms)
- One or two resolvers with timeouts (transient network issues)

**Red (serious problems):**
- Consistency: `INCONSISTENT` (resolvers disagree)
- Potential hijack: `YES`
- Hijack check: one or more resolvers show `HIJACKED`
- All resolvers timing out (resolver down or network unreachable)
- Very high response times (>500 ms, indicating upstream problems)

## Related concepts

- [DNS Explained](../../guide/concepts/dns-explained.md) — How DNS works, resolver chains, caching, DNSSEC, and common attack vectors

## Troubleshooting

### DNS over HTTPS/TLS not detected

netglance queries DNS over plain UDP/TCP. If your router or ISP uses DNS over HTTPS (DoH) or DNS over TLS (DoT), netglance will not detect this directly. Check your router settings or use a tool like `tcpdump` to confirm whether DNS traffic is encrypted. DoH/DoT is actually a *good* sign for privacy.

### Corporate or ISP DNS redirects

Some corporate networks or ISPs redirect all DNS queries to their own resolver, even if you configure a different one. This can cause false positives in hijack detection (netglance may report "HIJACKED" when the ISP is simply redirecting). Contact your IT department or ISP to confirm their DNS policy. You can also test from a different network to see whether the behavior changes.

### Slow resolution

If all resolvers are slow (response times >200 ms):
- **Network issue** — Your connection to the resolver's servers may be slow. Test from a different network.
- **Upstream resolver problem** — The resolver itself may be overloaded or geographically far from you. Try a different resolver.
- **Misconfigured resolver** — The IP you're querying may not be a valid DNS resolver. Double-check the address.

If only one resolver is slow, it's likely a network path issue specific to that resolver. Consider switching to a faster alternative.

### DNSSEC validation failures

If DNSSEC is not supported, it means the resolver doesn't validate DNSSEC signatures. This is not critical but reduces protection against DNS tampering. Consider switching to a resolver that supports DNSSEC (Cloudflare 1.1.1.1, Quad9 9.9.9.9, and Google 8.8.8.8 all support it).

### Timeouts on some domains

If only specific domains time out while others resolve fine:
- The domain's authoritative nameservers may be slow or unreachable.
- Try the same domain with a different resolver to rule out local network issues.
- Some overly restrictive firewalls may block certain domain queries.
