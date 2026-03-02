"""TLS certificate verification and interception detection."""

from __future__ import annotations

import hashlib
import socket
import ssl
from datetime import datetime, timezone

from netglance.store.models import CertInfo, TlsCheckResult

DEFAULT_HOSTS: list[str] = [
    "google.com",
    "github.com",
    "cloudflare.com",
    "amazon.com",
    "microsoft.com",
]

# Well-known trusted root CA organization names.  If a certificate's
# root CA does not appear in this set we flag potential interception.
TRUSTED_ROOT_CAS: set[str] = {
    "DigiCert Inc",
    "DigiCert",
    "Let's Encrypt",
    "ISRG",
    "Internet Security Research Group",
    "GlobalSign",
    "GlobalSign nv-sa",
    "Sectigo",
    "Comodo",
    "Comodo CA Limited",
    "GoDaddy",
    "Amazon",
    "Amazon Trust Services",
    "Google Trust Services LLC",
    "Google Trust Services",
    "Microsoft Corporation",
    "Microsoft",
    "Apple Inc.",
    "Entrust",
    "Entrust, Inc.",
    "Baltimore",
    "VeriSign",
    "Starfield Technologies",
    "Starfield Technologies, Inc.",
    "Thawte",
    "GeoTrust",
    "Certum",
    "IdenTrust",
    "USERTrust",
    "QuoVadis",
    "Buypass",
    "Actalis",
    "Trustwave",
    "SwissSign",
    "T-Systems",
    "Dhimyotis",
    "Certigna",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_dn_field(dn_tuples: tuple[tuple[tuple[str, str], ...], ...], field: str) -> str:
    """Extract a single field value from an ssl peer cert distinguished name."""
    for rdn in dn_tuples:
        for attr, value in rdn:
            if attr == field:
                return value
    return ""


def _parse_cert_dict(host: str, port: int, cert_dict: dict) -> CertInfo:
    """Convert the dict returned by ``SSLSocket.getpeercert()`` into a ``CertInfo``."""
    subject = _parse_dn_field(cert_dict.get("subject", ()), "commonName")
    issuer_cn = _parse_dn_field(cert_dict.get("issuer", ()), "commonName")
    issuer_org = _parse_dn_field(cert_dict.get("issuer", ()), "organizationName")

    san_list: list[str] = []
    for san_type, san_value in cert_dict.get("subjectAltName", ()):
        san_list.append(f"{san_type}:{san_value}")

    not_before_str = cert_dict.get("notBefore", "")
    not_after_str = cert_dict.get("notAfter", "")

    date_fmt = "%b %d %H:%M:%S %Y %Z"
    try:
        not_before = datetime.strptime(not_before_str, date_fmt)
    except (ValueError, TypeError):
        not_before = datetime.now(tz=timezone.utc)
    try:
        not_after = datetime.strptime(not_after_str, date_fmt)
    except (ValueError, TypeError):
        not_after = datetime.now(tz=timezone.utc)

    # Build a deterministic fingerprint from the serialNumber field (which is
    # the hex-encoded serial number of the certificate).  Real fingerprints
    # would need the DER-encoded cert, but getpeercert() doesn't give us that
    # in text mode, so we derive a pseudo-fingerprint.
    serial: str = cert_dict.get("serialNumber", "")
    fingerprint = hashlib.sha256(serial.encode()).hexdigest()

    return CertInfo(
        host=host,
        port=port,
        subject=subject,
        issuer=issuer_cn or issuer_org,
        root_ca=issuer_org,
        fingerprint_sha256=fingerprint,
        not_before=not_before,
        not_after=not_after,
        san=san_list,
        chain_length=1,  # getpeercert only returns the leaf
    )


def _is_trusted_ca(root_ca: str) -> bool:
    """Return True if *root_ca* appears to be a well-known public CA."""
    if not root_ca:
        return False
    for trusted in TRUSTED_ROOT_CAS:
        if trusted.lower() in root_ca.lower():
            return True
    return False


def _get_cert_chain(
    host: str,
    port: int = 443,
    timeout: float = 5.0,
    _create_context: ssl.SSLContext | None = None,
    _connect_func: object | None = None,
) -> list[dict]:
    """Fetch the full certificate chain for *host*.

    Returns a list of cert dicts (leaf first, root last).
    Dependency injection hooks (``_create_context`` and ``_connect_func``)
    are used for testing.
    """
    ctx = _create_context or ssl.create_default_context()
    if not isinstance(ctx, ssl.SSLContext):
        # _create_context was provided as a mock -- use it to get a context
        ctx = _create_context  # type: ignore[assignment]

    if _connect_func is not None:
        return _connect_func(host, port, ctx)  # type: ignore[return-value]

    # Real implementation: only leaf cert is available via getpeercert()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            leaf = ssock.getpeercert()  # type: ignore[union-attr]
    return [leaf] if leaf else []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_certificate(
    host: str,
    port: int = 443,
    timeout: float = 5.0,
    *,
    _context_factory: ssl.SSLContext | None = None,
) -> TlsCheckResult:
    """Check the TLS certificate for *host*.

    Parameters
    ----------
    host:
        Hostname to check.
    port:
        TCP port (default 443).
    timeout:
        Socket timeout in seconds.
    _context_factory:
        Optional SSLContext override for testing / dependency injection.

    Returns
    -------
    TlsCheckResult with certificate metadata, trust status, and interception flag.
    """
    ctx = _context_factory or ssl.create_default_context()

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert_dict = ssock.getpeercert()
        if not cert_dict:
            return TlsCheckResult(
                host=host,
                cert=CertInfo(host=host, port=port),
                is_trusted=False,
                is_intercepted=False,
                details="No certificate returned",
            )
    except ssl.SSLCertVerificationError as exc:
        return TlsCheckResult(
            host=host,
            cert=CertInfo(host=host, port=port),
            is_trusted=False,
            is_intercepted=False,
            details=f"Certificate verification failed: {exc}",
        )
    except (OSError, socket.timeout) as exc:
        return TlsCheckResult(
            host=host,
            cert=CertInfo(host=host, port=port),
            is_trusted=False,
            is_intercepted=False,
            details=f"Connection error: {exc}",
        )

    cert_info = _parse_cert_dict(host, port, cert_dict)
    trusted = _is_trusted_ca(cert_info.root_ca)
    intercepted = not trusted and bool(cert_info.root_ca)

    details_parts: list[str] = []
    if trusted:
        details_parts.append(f"Trusted CA: {cert_info.root_ca}")
    elif intercepted:
        details_parts.append(f"Possible interception - unknown CA: {cert_info.root_ca}")
    else:
        details_parts.append("Unable to determine root CA")

    now = datetime.now(tz=timezone.utc)
    if cert_info.not_after.replace(tzinfo=timezone.utc) < now:
        details_parts.append("Certificate has expired")
        trusted = False

    return TlsCheckResult(
        host=host,
        cert=cert_info,
        is_trusted=trusted,
        is_intercepted=intercepted,
        details="; ".join(details_parts),
    )


def check_multiple(
    hosts: list[str] | None = None,
    *,
    _context_factory: ssl.SSLContext | None = None,
) -> list[TlsCheckResult]:
    """Check TLS certificates for a list of hosts (default: ``DEFAULT_HOSTS``)."""
    targets = hosts or DEFAULT_HOSTS
    results: list[TlsCheckResult] = []
    for host in targets:
        results.append(
            check_certificate(host, _context_factory=_context_factory)
        )
    return results


def diff_fingerprints(
    current: list[TlsCheckResult],
    baseline: list[dict],
) -> list[dict]:
    """Compare *current* TLS results against a saved *baseline*.

    Parameters
    ----------
    current:
        List of ``TlsCheckResult`` from a fresh scan.
    baseline:
        List of dicts (as returned by ``Store.get_latest_baseline``), each
        containing at least ``host`` and ``fingerprint_sha256``.

    Returns
    -------
    A list of change dicts, one per host that differs.  Each dict contains
    ``host``, ``status`` (``"changed"`` or ``"match"``), ``old_fingerprint``,
    and ``new_fingerprint``.
    """
    baseline_map: dict[str, str] = {
        entry["host"]: entry.get("fingerprint_sha256", "") for entry in baseline
    }

    diffs: list[dict] = []
    for result in current:
        old_fp = baseline_map.get(result.host)
        new_fp = result.cert.fingerprint_sha256
        if old_fp is None:
            diffs.append(
                {
                    "host": result.host,
                    "status": "new",
                    "old_fingerprint": None,
                    "new_fingerprint": new_fp,
                }
            )
        elif old_fp != new_fp:
            diffs.append(
                {
                    "host": result.host,
                    "status": "changed",
                    "old_fingerprint": old_fp,
                    "new_fingerprint": new_fp,
                }
            )
        else:
            diffs.append(
                {
                    "host": result.host,
                    "status": "match",
                    "old_fingerprint": old_fp,
                    "new_fingerprint": new_fp,
                }
            )
    return diffs
