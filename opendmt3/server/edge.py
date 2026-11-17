"""The site over HTTPS on the internet or a closed network: the Caddyfile for Caddy, the reverse proxy in front of the
site that gets and renews its certificate by itself (Let's Encrypt, another ACME authority, or Caddy's own local
one), for ./dmt3 expose (Caddy in a container beside the server) and the server's own command line (expose, Caddy
run beside it). Plain Python, nothing to install: the front door reads it from this clone.

The game's port is not behind it: the game speaks its own protocol on TCP 4725, opened as it is.
"""

import ipaddress
import re
import urllib.parse

# Let's Encrypt's staging authority: real ACME, certificates no browser trusts, limits high enough to try a setup.
STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
# A host name: dot-separated labels of letters, digits and inner hyphens (no scheme, no port, no path).
NAME = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}"
                  r"[A-Za-z0-9])?)*$")


class EdgeError(ValueError):
    """A name or a choice the proxy cannot be set up with, said in one line."""


def check_name(name, local_ca=False):
    """The site's name as given, or EdgeError: a host name, or (with Caddy's local authority only, which signs
    anything) an IP address; public authorities sign a name the internet resolves to this PC."""
    name = (name or "").strip().rstrip(".").lower()
    try:
        ipaddress.ip_address(name)
        if local_ca:
            return name
        raise EdgeError("%s is an address, not a name: a public certificate needs a name (a DDNS name works), or "
                        "use --local-ca on a closed network" % name)
    except ValueError as e:
        if isinstance(e, EdgeError):
            raise
    if not NAME.match(name) or "." not in name and not local_ca:
        raise EdgeError("%r is not a host name like dmt3.example.org" % name)
    return name


def moved_address(address, old_port, new_port):
    """The players' address after the site's port moved: an http address on the old port, on the new one; any other
    (an https address through a proxy, an address with no port of the site's) as it was given. Used by ./dmt3 ports
    and by the server's own setup --web-port, so the invite, the banner and the message to send a player follow."""
    if not address:
        return address
    parts = urllib.parse.urlsplit(address)
    if parts.scheme != "http" or parts.port != old_port:
        return address
    # An IPv6 address keeps its brackets in an address.
    host = parts.hostname if ":" not in (parts.hostname or "") else "[%s]" % parts.hostname
    return urllib.parse.urlunsplit((parts.scheme, "%s:%d" % (host, new_port), parts.path, parts.query, parts.fragment))


def is_address(name):
    """True when the site's name is an IP address (a closed network with no names), not a host name."""
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def caddyfile(name, upstream, email=None, ca=None, ca_root=None, local_ca=False, admin=None):
    """The Caddyfile for the site at https://NAME/ in front of `upstream` (host:port of the site): its certificate
    from Let's Encrypt (email: the address it writes to about the certificate), from another ACME authority `ca`
    ("staging" for Let's Encrypt's staging one; ca_root: that authority's root certificate when it is a private one,
    as a test's is), or from Caddy's own local authority (local_ca), for a closed network. admin: (Caddy's port for
    it, the admin listener's host:port) puts the admin pages behind Caddy too (./dmt3 expose --admin-public), at the
    same name on a port of their own, with the same certificate; without it nothing of the admin site is here."""
    name = check_name(name, local_ca)
    if local_ca and (ca or email):
        raise EdgeError("--local-ca signs the certificate itself: no ACME authority or e-mail goes with it")
    lines = ["# Made by openDMT3 (./dmt3 expose, or opendmt3-server expose): the site over HTTPS at https://%s/." % name,
             "# Caddy gets the certificate and renews it by itself, and sends plain HTTP visits to HTTPS."]
    options = []
    if email:
        # The address the authority writes to before a certificate runs out unrenewed.
        options.append("    email %s" % email)
    if ca:
        options.append("    acme_ca %s" % (STAGING if ca == "staging" else ca))
    if ca_root:
        # A private authority's root (a test's): Caddy trusts it to reach the authority.
        options.append("    acme_ca_root %s" % ca_root)
    if is_address(name):
        # A client names no site in its handshake when it connects to an address (no SNI), and Caddy would then pick
        # a certificate by the address the connection came in on: behind Docker's port publishing that is the
        # container's own, never the one players use, and every handshake would fail. This one is the site's.
        options.append("    default_sni %s" % name)
    if options:
        lines += ["{"] + options + ["}", ""]
    lines += ["%s {" % name]
    if local_ca:
        # Caddy's own authority signs it; players' PCs trust its root certificate once (docs/closed-network.md).
        lines.append("    tls internal")
    lines += [
        # The visitor's address in X-Forwarded-For and the site's name in Host, as Caddy passes them by itself; the
        # server believes them from this proxy only (--proxy).
        "    reverse_proxy %s" % upstream,
        "}", ""]
    if admin:
        port, admin_upstream = admin
        # The admin site: the same name on its own port (HTTPS only: nothing plain is served there), its certificate
        # the site's, then the admin listener, which believes this proxy's forwarded headers as the site does.
        lines += ["%s:%d {" % (name, port)]
        if local_ca:
            lines.append("    tls internal")
        lines += ["    reverse_proxy %s" % admin_upstream, "}", ""]
    return "\n".join(lines)
