"""Web guard (spec section 24).

Blocks fetches to localhost, private/link-local ranges, and cloud metadata
endpoints (SSRF protection), and enforces the http/https policy.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class WebDenied(Exception):
    pass


# Cloud metadata + obvious internal hostnames.
BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "localhost"}
METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or ip in METADATA_IPS)


def check_url(url: str, *, allow_http: bool, block_private: bool) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise WebDenied(f"unsupported scheme: {scheme!r}")
    if scheme == "http" and not allow_http:
        raise WebDenied("http blocked (WEB_ALLOW_HTTP=false); use https")
    host = parsed.hostname
    if not host:
        raise WebDenied("missing host")
    if host.lower() in BLOCKED_HOSTS:
        raise WebDenied(f"blocked host: {host}")
    if host in METADATA_IPS:
        raise WebDenied("blocked metadata endpoint")

    if block_private:
        # Resolve and reject if any address is private/loopback/link-local.
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise WebDenied(f"DNS resolution failed for {host}: {e}") from e
        for info in infos:
            ip = info[4][0]
            if _is_private_ip(ip):
                raise WebDenied(f"blocked private/internal address {ip} for host {host}")
    return url
