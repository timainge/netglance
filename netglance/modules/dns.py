"""DNS health & leak detection.

Provides resolver benchmarking, consistency checks, DNSSEC validation,
and DNS hijack detection by comparing answers across multiple resolvers.
"""

import time

import dns.flags
import dns.name
import dns.rdatatype
import dns.resolver

from netglance.store.models import DnsHealthReport, DnsResolverResult

DEFAULT_RESOLVERS: dict[str, str] = {
    "1.1.1.1": "Cloudflare",
    "8.8.8.8": "Google",
    "9.9.9.9": "Quad9",
}

# A domain that should resolve to a well-known NXDOMAIN.  Used for hijack detection.
_HIJACK_CANARY = "this-domain-should-not-exist-netglance.example.invalid"

# Default domains used when benchmarking resolvers.
_BENCHMARK_DOMAINS = ["example.com", "google.com", "cloudflare.com"]


def _make_resolver(nameserver: str, lifetime: float = 5.0) -> dns.resolver.Resolver:
    """Create a dns.resolver.Resolver pointed at a single nameserver."""
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = [nameserver]
    r.lifetime = lifetime
    return r


# ---------------------------------------------------------------------------
# Thin wrapper around dns.resolver -- easy to mock in tests
# ---------------------------------------------------------------------------


def _dns_resolve(nameserver: str, domain: str, rdtype: str, lifetime: float = 5.0):
    """Thin wrapper that performs a DNS resolution via dns.resolver.

    Creates a resolver pointed at *nameserver* and queries *domain* for
    *rdtype*.  Returns the raw dns.resolver.Answer object.  Isolated
    here so callers can inject a replacement for testing.
    """
    res = _make_resolver(nameserver, lifetime)
    return res.resolve(domain, rdtype)


def query_resolver(
    resolver: str,
    domain: str,
    rdtype: str = "A",
    resolver_name: str | None = None,
    *,
    _resolve_fn=None,
) -> DnsResolverResult:
    """Query a single DNS resolver for *domain* and return a DnsResolverResult.

    Parameters
    ----------
    resolver:
        IP address of the resolver to query.
    domain:
        Domain name to look up.
    rdtype:
        DNS record type (default ``"A"``).
    resolver_name:
        Human-friendly name for the resolver.  Falls back to *resolver*.
    _resolve_fn:
        Injectable replacement for the DNS resolve call (for testing).
        Signature: ``(nameserver, domain, rdtype, lifetime) -> Answer``.
    """
    resolve = _resolve_fn or _dns_resolve
    name = resolver_name or DEFAULT_RESOLVERS.get(resolver, resolver)
    try:
        start = time.monotonic()
        answer = resolve(resolver, domain, rdtype)
        elapsed_ms = (time.monotonic() - start) * 1000
        records = sorted(rdata.to_text() for rdata in answer)
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=records,
            response_time_ms=round(elapsed_ms, 2),
        )
    except dns.resolver.NXDOMAIN:
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=[],
            error="NXDOMAIN",
        )
    except dns.resolver.NoAnswer:
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=[],
            error="NoAnswer",
        )
    except dns.resolver.NoNameservers:
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=[],
            error="NoNameservers",
        )
    except dns.exception.Timeout:
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=[],
            error="Timeout",
        )
    except Exception as exc:  # pragma: no cover – safety net
        return DnsResolverResult(
            resolver=resolver,
            resolver_name=name,
            query=domain,
            answers=[],
            error=str(exc),
        )


def check_consistency(
    domain: str,
    resolvers: dict[str, str] | None = None,
    *,
    _resolve_fn=None,
) -> DnsHealthReport:
    """Query *domain* across multiple resolvers and check whether they agree.

    Returns a :class:`DnsHealthReport` summarising consistency, speed, and
    potential hijacking indicators.

    Parameters
    ----------
    _resolve_fn:
        Injectable replacement for the DNS resolve call, passed through to
        ``query_resolver`` and ``check_dnssec``.
    """
    resolvers = resolvers or DEFAULT_RESOLVERS
    results: list[DnsResolverResult] = []
    for ip, name in resolvers.items():
        results.append(query_resolver(ip, domain, resolver_name=name, _resolve_fn=_resolve_fn))

    # Determine consistency – all non-error results should have the same answers.
    good = [r for r in results if r.error is None]
    answer_sets = [tuple(r.answers) for r in good]
    consistent = len(set(answer_sets)) <= 1

    # Fastest resolver (among successful ones).
    fastest: str | None = None
    if good:
        fastest_result = min(good, key=lambda r: r.response_time_ms)
        fastest = f"{fastest_result.resolver_name} ({fastest_result.resolver})"

    # DNSSEC support for the domain.
    dnssec_ok = check_dnssec(domain, resolver=list(resolvers.keys())[0], _resolve_fn=_resolve_fn)

    # Simple hijack heuristic: if answers diverge, flag it.
    potential_hijack = not consistent and len(good) > 1

    return DnsHealthReport(
        resolvers_checked=len(results),
        consistent=consistent,
        fastest_resolver=fastest,
        dnssec_supported=dnssec_ok,
        potential_hijack=potential_hijack,
        details=results,
    )


def check_dnssec(domain: str, resolver: str = "1.1.1.1", *, _resolve_fn=None) -> bool:
    """Return ``True`` if the resolver response for *domain* has the AD flag set.

    Parameters
    ----------
    _resolve_fn:
        Injectable replacement for the DNS resolve call (for testing).
        When provided, EDNS configuration is skipped (the caller is
        responsible for returning an answer with appropriate flags).
    """
    if _resolve_fn is not None:
        try:
            answer = _resolve_fn(resolver, domain, "A")
            return bool(answer.response.flags & dns.flags.AD)
        except Exception:
            return False

    res = _make_resolver(resolver)
    try:
        res.use_edns(edns=0, ednsflags=dns.flags.DO, payload=4096)
        answer = res.resolve(domain, "A")
        return bool(answer.response.flags & dns.flags.AD)
    except Exception:
        return False


def benchmark_resolvers(
    resolvers: dict[str, str] | None = None,
    domains: list[str] | None = None,
    *,
    _resolve_fn=None,
) -> list[DnsResolverResult]:
    """Benchmark *resolvers* against *domains* and return per-query results.

    Parameters
    ----------
    _resolve_fn:
        Injectable replacement for the DNS resolve call, passed through to
        ``query_resolver``.
    """
    resolvers = resolvers or DEFAULT_RESOLVERS
    domains = domains or _BENCHMARK_DOMAINS
    results: list[DnsResolverResult] = []
    for domain in domains:
        for ip, name in resolvers.items():
            results.append(query_resolver(ip, domain, resolver_name=name, _resolve_fn=_resolve_fn))
    return results


def detect_dns_hijack(
    resolvers: dict[str, str] | None = None,
    *,
    _resolve_fn=None,
) -> dict:
    """Detect potential DNS hijacking.

    Queries a canary domain that *should* be NXDOMAIN.  If any resolver
    returns actual addresses, something is intercepting or rewriting DNS
    responses.

    Returns a dict with keys ``hijack_detected`` (bool) and
    ``details`` (list of :class:`DnsResolverResult`).

    Parameters
    ----------
    _resolve_fn:
        Injectable replacement for the DNS resolve call, passed through to
        ``query_resolver``.
    """
    resolvers = resolvers or DEFAULT_RESOLVERS
    results: list[DnsResolverResult] = []
    hijack_detected = False
    for ip, name in resolvers.items():
        result = query_resolver(ip, _HIJACK_CANARY, resolver_name=name, _resolve_fn=_resolve_fn)
        results.append(result)
        if result.answers:
            # Answers for a domain that should not exist = hijack indicator.
            hijack_detected = True
    return {
        "hijack_detected": hijack_detected,
        "details": results,
    }
