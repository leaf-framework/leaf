"""Checks that flag external connections configured without credentials or encryption."""

from urllib.parse import urlsplit

# A connection that never leaves this machine is not worth a warning.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_local(host: str | None) -> bool:
    """True for a loopback host or a unix socket path."""
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    return host.startswith("/")


def mqtt_warnings(what: str, broker: str, username: str | None, tls: bool) -> list[str]:
    """Issues of an MQTT connection to broker; what names the module, e.g. "MQTT output"."""
    if is_local(broker):
        return []
    issues: list[str] = []
    if not username:
        issues.append(f"{what} to {broker}: no username/password, anyone on the network can connect")
    if not tls:
        if username:
            issues.append(f"{what} to {broker}: password sent unencrypted, set tls: true")
        else:
            issues.append(f"{what} to {broker}: traffic unencrypted, set tls: true")
    return issues


def http_warnings(what: str, url: str) -> list[str]:
    """Issue of a plain http:// URL to another machine."""
    parts = urlsplit(url)
    if parts.scheme != "http" or is_local(parts.hostname):
        return []
    return [f"{what} to {parts.hostname}: plain http://, use https://"]
