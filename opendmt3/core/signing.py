"""openDMT3's signature on its update packages, so a launcher puts in only updates the project made.

A launcher can take its updates from the server it plays on (that server's /updates/), and that address is often
plain HTTP on a home network. Velopack checks a package against the hash in the same feed it came with, so whoever
answers for that address (the server, or anyone between it and the PC) could hand over any program. Each package
the release build makes therefore comes with <package>.sig, the project's Ed25519 signature over the package's
name and SHA-256, and the launcher puts in an update only when that signature checks out against a key built into
it (updates.py). A server hands the .sig out with the package; it cannot make one.

An update that comes as a delta package is put together on the PC from the package installed and the delta (Velopack's
own way), and that package holds the same files but is zipped again: its bytes are not the signed ones. So the .sig
also signs the package's content, the SHA-256 of every file in it by its name (content_sha256), and a package rebuilt
from deltas is put in when its files are the ones signed. A delta package has a .sig of its own, and the launcher
checks it by its bytes before the installed Update.exe reads the delta (updates.py).

A launcher built for a test also takes the keys its build wrote into update-test-keys.txt beside this module
(OPENDMT3_TEST_UPDATE_KEY, packaging/windows/build.sh): the Wine tests sign their made-up updates with a key made for
the run and thrown away after it, never the project's. A release's file is empty (packaging/release.sh checks).

Ed25519 as RFC 8032 defines it, in plain Python (the launcher bundles no cryptography library): one check takes
a few hundredths of a second, once per update.

  python -m opendmt3.core.signing new-key KEY_FILE        make a signing key (kept off the repository), print its public key
  python -m opendmt3.core.signing sign KEY_FILE PACKAGE... write PACKAGE.sig beside each package
  python -m opendmt3.core.signing check [--key PUBLIC] PACKAGE...  check each PACKAGE.sig against the keys built in and PUBLIC
"""

import hashlib
import json
import os
import re
import sys
import zipfile

# The public keys whose signatures a launcher takes (hex). The signing key itself stays with whoever builds the
# releases; a new key is added here before it signs anything, so launchers already out there keep updating.
KEYS = ("689a658f9d9ef28f1bb2cbc0807f9198aa592625208a2a8ccd62d513f9300d94",)
# The keys a test build takes besides: one public key (hex) a line, written beside this module by the build that was
# given OPENDMT3_TEST_UPDATE_KEY. A release's file is empty, and a copy of the repository has none.
TEST_KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-test-keys.txt")
# A public key as it is written: 32 bytes in hex.
_KEY_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
FORMAT = 1
# A .sig is a few hundred bytes; anything far longer is not one.
SIG_LIMIT = 4096

# ---- Ed25519 (RFC 8032, section 5.1), on points in extended coordinates (X, Y, Z, T): x = X/Z, y = Y/Z, xy = T/Z
_P = 2 ** 255 - 19
# The order of the base point.
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
# A square root of -1, for recovering x from y.
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    """The sum of two points (the formula is complete: it also doubles a point added to itself)."""
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    pa = (y1 - x1) * (y2 - x2) % _P
    pb = (y1 + x1) * (y2 + x2) % _P
    pc = t1 * 2 * _D * t2 % _P
    pd = z1 * 2 * z2 % _P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _times(n, point):
    """n times a point, by doubling and adding (n is never secret where this runs as a check)."""
    out = (0, 1, 1, 0)
    while n > 0:
        if n & 1:
            out = _add(out, point)
        point = _add(point, point)
        n >>= 1
    return out


def _same(a, b):
    """True when two points in extended coordinates are the same point."""
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _x_from(y, sign):
    """The x of the point with this y and x's lowest bit, or None when there is no such point."""
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    return _P - x if (x & 1) != sign else x


def _encode(point):
    """A point as 32 bytes: y, little-endian, with x's lowest bit in the top bit."""
    zi = pow(point[2], _P - 2, _P)
    x, y = point[0] * zi % _P, point[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data):
    """The point 32 bytes stand for, or None when they stand for none."""
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _x_from(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


# The base point: y = 4/5, with an even x.
_BY = 4 * pow(5, _P - 2, _P) % _P
_B = (_x_from(_BY, 0), _BY, 1, _x_from(_BY, 0) * _BY % _P)


def _sha512_int(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def _expand(seed):
    """The secret scalar and the nonce prefix a 32-byte seed stands for."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    # The scalar's fixed bits (RFC 8032, 5.1.5): a multiple of 8, with bit 254 set.
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """The 32-byte public key of a 32-byte seed."""
    return _encode(_times(_expand(seed)[0], _B))


def sign(seed, message):
    """The 64-byte signature of a message with a 32-byte seed."""
    a, prefix = _expand(seed)
    public = _encode(_times(a, _B))
    r = _sha512_int(prefix, message) % _L
    big_r = _encode(_times(r, _B))
    k = _sha512_int(big_r, public, message) % _L
    return big_r + ((r + k * a) % _L).to_bytes(32, "little")


def verify(public, message, signature):
    """True when the signature is the holder of this public key's signature of the message."""
    if len(public) != 32 or len(signature) != 64:
        return False
    point_a, point_r = _decode(public), _decode(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    # A signature's s is below the order; a larger one is another spelling of the same signature.
    if s >= _L:
        return False
    k = _sha512_int(signature[:32], public, message) % _L
    return _same(_times(s, _B), _add(point_r, _times(k, point_a)))


# ---- the keys a launcher takes
def added_keys(path=None):
    """The public keys a test build wrote in (TEST_KEYS_FILE): every line of the file that is a key, in lower case;
    none without the file, with an empty one (a release's), or with one that cannot be read."""
    try:
        with open(path or TEST_KEYS_FILE, encoding="ascii") as f:
            # Split on any white space: one key a line, and a last line with or without its newline.
            lines = f.read().split()
    except (OSError, ValueError):
        # No such file (a copy of the repository), or bytes that are no text: no keys besides the project's.
        return ()
    # A line that is no key is left out, never taken for one: the hex compared below is always 64 digits.
    return tuple(line.lower() for line in lines if _KEY_HEX.match(line))


def trusted():
    """Every public key this launcher takes a signature from: the project's (KEYS), then a test build's own. Read at
    each check, so a test that swaps KEYS for its own key is checked against that key."""
    return tuple(KEYS) + added_keys()


# ---- signed packages
def statement(name, sha256):
    """What a package's signature signs: its file name (with its version, so an older package cannot pass for a
    newer one) and the SHA-256 of its bytes."""
    return ("openDMT3 update package\n%s\n%s\n" % (name, sha256.lower())).encode("utf-8")


def content_statement(name, digest):
    """What a package's second signature signs: its file name and the SHA-256 of its content (content_sha256)."""
    return ("openDMT3 update package content\n%s\n%s\n" % (name, digest.lower())).encode("utf-8")


def content_sha256(path):
    """The SHA-256 of what a package holds, whatever zipped it: a line for every file in it (its name with forward
    slashes, and the SHA-256 of its bytes), in the order of the names. None for a file that is not a zip.

    A package Velopack rebuilds from a delta package holds the same files as the one the release built (each patched
    to the same bytes, Velopack's own check), zipped again in another order and another compression."""
    try:
        with zipfile.ZipFile(path) as archive:
            lines = []
            for info in archive.infolist():
                if info.is_dir():
                    # A folder's own entry holds nothing (one zip writer lists them, another does not).
                    continue
                digest = hashlib.sha256()
                with archive.open(info) as f:
                    for piece in iter(lambda: f.read(1 << 20), b""):
                        digest.update(piece)
                lines.append("%s\0%s\n" % (info.filename.replace("\\", "/"), digest.hexdigest()))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        # Not a zip (or one cut short): nothing to sign or check by content.
        return None
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def sha256_of(path):
    """The SHA-256 of a file, read in pieces (packages are tens of megabytes)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def sign_package(seed, path):
    """The .sig of a package as a dict (written beside it by main())."""
    name, digest = os.path.basename(path), sha256_of(path)
    signed = {"format": FORMAT, "file": name, "sha256": digest, "key": public_key(seed).hex(),
              "signature": sign(seed, statement(name, digest)).hex()}
    content = content_sha256(path)
    if content is not None:
        # The second signature, over the package's files: what a package rebuilt from deltas is checked against.
        signed.update(content=content, content_signature=sign(seed, content_statement(name, content)).hex())
    return signed


def checks_out(sig, path, name, keys=None):
    """True when the .sig (bytes as fetched) is a signature of this file under this name by one of the keys (the
    ones this launcher takes, trusted(), unless others are given)."""
    keys = trusted() if keys is None else keys
    try:
        if len(sig) > SIG_LIMIT:
            return False
        data = json.loads(sig.decode("utf-8"))
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("file") != name:
            return False
        key, signature, digest = (bytes.fromhex(data["key"]), bytes.fromhex(data["signature"]),
                                  str(data["sha256"]).lower())
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return False
    if key.hex() not in keys:
        return False
    # The bytes on disk are what Velopack would put in; the signed hash must be theirs.
    if sha256_of(path) != digest:
        return False
    return verify(key, statement(name, digest), signature)


def content_checks_out(sig, path, name, keys=None):
    """True when the .sig signs the files this package holds (content_sha256) under this name, by one of the keys:
    a package Velopack rebuilt from delta packages, whose bytes are zipped again."""
    keys = trusted() if keys is None else keys
    try:
        if len(sig) > SIG_LIMIT:
            return False
        data = json.loads(sig.decode("utf-8"))
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("file") != name:
            return False
        key, signature, digest = (bytes.fromhex(data["key"]), bytes.fromhex(data["content_signature"]),
                                  str(data["content"]).lower())
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        # No content signature, or not a .sig at all.
        return False
    if key.hex() not in keys:
        return False
    if content_sha256(path) != digest:
        return False
    return verify(key, content_statement(name, digest), signature)


def _read_seed(path):
    with open(path, encoding="ascii") as f:
        seed = bytes.fromhex(f.read().strip())
    if len(seed) != 32:
        raise SystemExit("%s is not a signing key (64 hex digits)" % path)
    return seed


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "new-key":
        if os.path.exists(argv[1]):
            raise SystemExit("%s exists; a signing key is never written over" % argv[1])
        seed = os.urandom(32)
        # Readable by its owner only, from the moment it exists.
        fd = os.open(argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(seed.hex() + "\n")
        print(public_key(seed).hex())
        return 0
    if len(argv) >= 3 and argv[0] == "sign":
        seed = _read_seed(argv[1])
        for path in argv[2:]:
            with open(path + ".sig", "w", encoding="utf-8") as f:
                json.dump(sign_package(seed, path), f, indent=1)
            print("signed", os.path.basename(path))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        paths, keys = argv[1:], trusted()
        # --key PUBLIC_KEY, before the packages: a test build's key (the one its launcher takes besides the
        # project's), so the build that signed with it checks its own packages as that launcher will.
        while len(paths) >= 2 and paths[0] == "--key":
            if not _KEY_HEX.match(paths[1]):
                raise SystemExit("%s is not a public key (64 hex digits)" % paths[1])
            keys, paths = keys + (paths[1].lower(),), paths[2:]
        if not paths:
            # A key and no package: nothing was checked, which must not read as a pass.
            raise SystemExit("no package to check")
        bad = 0
        for path in paths:
            try:
                with open(path + ".sig", "rb") as f:
                    sig = f.read(SIG_LIMIT + 1)
                # Both signatures of a zip: its bytes, and its files (what a package rebuilt from deltas is checked by).
                good = checks_out(sig, path, os.path.basename(path), keys) and (
                    content_sha256(path) is None or content_checks_out(sig, path, os.path.basename(path), keys))
            except OSError:
                good = False
            print("%s: %s" % (os.path.basename(path), "signed" if good else "NOT SIGNED by a key built in"))
            bad += not good
        return 1 if bad else 0
    # Anything else: the three commands, as the module's description gives them.
    print("\n".join(__doc__.strip().splitlines()[-3:]))
    return 2


if __name__ == "__main__":
    sys.exit(main())
