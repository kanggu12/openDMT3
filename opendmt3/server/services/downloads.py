"""What the Download page says about the installer it hands out: its size, when it was put in the downloads folder, its
version, and the name it is handed out under.

The version is read from the file's own version resource (the numbers Windows shows under Properties, Details), by
walking the Windows program's headers to it: every offset is checked against the file before it is followed, and
anything unexpected gives no version (the page then leaves it out) instead of a wrong one.
"""

import os
import re
import struct

# The resource type of a program's version (RT_VERSION), and the mark its fixed part starts with.
RT_VERSION = 16
FIXED_SIGNATURE = 0xFEEF04BD
# The version resource is a few hundred bytes; a resource directory a few dozen entries.
VERSION_MOST = 64 * 1024
ENTRIES_MOST = 4096


def download_name(host, port):
    """The installer's name as it is handed out: the server's address in it, every character other than a letter,
    a digit, a dot or a dash made a dash (openDMT3-win-Setup-dmt.example.org-443.exe), as OpenDMTQ names its own."""
    return "openDMT3-win-Setup-" + re.sub(r"[^A-Za-z0-9.-]", "-", "%s-%s" % (host, port)) + ".exe"


def facts(path):
    """{"size": bytes, "at": when the file was put there (its modification time), "version": "0.1.0" or None},
    or None when there is no installer."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return {"size": st.st_size, "at": int(st.st_mtime), "version": version(path)}


def version(path):
    """The product version in a Windows program's version resource ("0.1.0"; a fourth number only when it is not
    0), or None when the file has none or cannot be read as one."""
    try:
        with open(path, "rb") as f:
            return _version(f, os.fstat(f.fileno()).st_size)
    except (OSError, struct.error, ValueError):
        return None


def _read(f, size, offset, length):
    """`length` bytes at `offset`, all of them inside the file, or ValueError."""
    if offset < 0 or length < 0 or offset + length > size:
        raise ValueError("outside the file")
    f.seek(offset)
    data = f.read(length)
    if len(data) != length:
        raise ValueError("cut short")
    return data


def _version(f, size):
    # The DOS header names where the PE header is.
    if _read(f, size, 0, 2) != b"MZ":
        return None
    pe = struct.unpack("<I", _read(f, size, 0x3C, 4))[0]
    if _read(f, size, pe, 4) != b"PE\0\0":
        return None
    # The COFF header: how many sections, and how long the optional header is.
    sections, optional_size = struct.unpack("<2xH12xH2x", _read(f, size, pe + 4, 20))
    optional = pe + 24
    magic = struct.unpack("<H", _read(f, size, optional, 2))[0]
    # Where the data directories are counted and start: PE32 and PE32+ differ.
    if magic == 0x10B:
        count_at, directories = 92, 96
    elif magic == 0x20B:
        count_at, directories = 108, 112
    else:
        return None
    if struct.unpack("<I", _read(f, size, optional + count_at, 4))[0] <= 2:
        # No resource directory among them (it is the third).
        return None
    resources_rva = struct.unpack("<I", _read(f, size, optional + directories + 2 * 8, 4))[0]
    if not resources_rva:
        return None
    # The sections map an address in memory (RVA) to a place in the file.
    table = []
    for i in range(sections):
        virtual_size, address, raw_size, raw_at = struct.unpack(
            "<4I", _read(f, size, optional + optional_size + 40 * i + 8, 16))
        table.append((address, max(virtual_size, raw_size), raw_at))

    def at(rva):
        for address, length, raw_at in table:
            if address <= rva < address + length:
                return raw_at + rva - address
        raise ValueError("an address in no section")

    base = at(resources_rva)

    def entries(offset):
        """A resource directory's entries: (name or ID word, its data word)."""
        named, ids = struct.unpack("<12xHH", _read(f, size, base + offset, 16))
        if named + ids > ENTRIES_MOST:
            raise ValueError("too many entries")
        data = _read(f, size, base + offset + 16, 8 * (named + ids))
        return [struct.unpack_from("<II", data, 8 * i) for i in range(named + ids)]

    # Three levels: the type (RT_VERSION), the resource's name, its language; each the first there is below the type.
    level = [e for e in entries(0) if e[0] == RT_VERSION]
    for depth in range(2):
        if not level or not level[0][1] & 0x80000000:
            # A directory was expected here.
            return None
        level = entries(level[0][1] & 0x7FFFFFFF)
    if not level or level[0][1] & 0x80000000:
        # Data was expected here.
        return None
    data_rva, length = struct.unpack("<II", _read(f, size, base + level[0][1], 8))
    if not 92 <= length <= VERSION_MOST:
        return None
    info = _read(f, size, at(data_rva), length)
    # VS_VERSIONINFO: its key, then (on a 4-byte boundary) the fixed part with the numbers.
    value_length = struct.unpack_from("<H", info, 2)[0]
    if info[6:38].decode("utf-16-le", "replace") != "VS_VERSION_INFO\0" or value_length < 52:
        return None
    signature, _, _, _, product_ms, product_ls = struct.unpack_from("<6I", info, 40)
    if signature != FIXED_SIGNATURE:
        return None
    numbers = [product_ms >> 16, product_ms & 0xFFFF, product_ls >> 16, product_ls & 0xFFFF]
    # Three numbers as the project writes them; a fourth only when it says something.
    return ".".join(str(n) for n in (numbers if numbers[3] else numbers[:3]))
