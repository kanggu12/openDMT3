"""The libraries a Windows program loads by name when it starts: the import table of a PE file, read with struct.

openDMT3 runs its copy of the game's client from its own folder, with the game folder as the current folder. Windows
then looks for the client's libraries in the client's folder first and in System32 before the current folder, so a
library of the same name in System32 (Wine has its own D3DX 9, a PC may have the DirectX runtime's or an old game's
Bink) would be loaded in place of the game's. Measured under Wine: run that way, the client took Wine's own
d3dx9_40.dll and stopped at its first sound. So the client's libraries that are in the game folder are copied beside
the client copy, found here by name from the client's import table and from theirs in turn.
"""

import struct

# The import table's entry in the optional header's data directories, and one descriptor's size.
IMPORT_DIRECTORY = 1
DESCRIPTOR = 20
# More than any real program imports (the client imports 27 libraries): past this the table is not a program's.
MOST_IMPORTS = 512


class PeError(ValueError):
    """Not a PE file, or one whose import table cannot be read."""


def _u16(data, at):
    return struct.unpack_from("<H", data, at)[0]


def _u32(data, at):
    return struct.unpack_from("<I", data, at)[0]


def _sections(data, pe):
    """(virtual address, virtual size, raw size, raw offset) of each section."""
    count = _u16(data, pe + 6)
    opt_size = _u16(data, pe + 20)
    table = pe + 24 + opt_size
    out = []
    for i in range(count):
        s = table + 40 * i
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, s + 8)
        out.append((va, max(vsize, raw_size), raw_size, raw_ptr))
    return out


def _offset(sections, rva):
    """The file offset of a relative virtual address (the section that holds it), or None."""
    for va, size, raw_size, raw_ptr in sections:
        if va <= rva < va + size and rva - va < raw_size:
            return raw_ptr + rva - va
    return None


def _name(data, at):
    """A zero-ended ASCII name at a file offset (a library's name is short; 260 bytes at most)."""
    end = data.find(b"\x00", at, at + 260)
    if end < 0:
        raise PeError("a library name without its end")
    return data[at:end].decode("ascii", "replace")


def imports(data):
    """The names of the libraries a PE file imports, in the order its import table lists them, each once (a table
    rebuilt by a dumper lists KERNEL32.DLL more than once). PeError when it is no PE file."""
    try:
        if data[:2] != b"MZ":
            raise PeError("not a program (no MZ)")
        pe = _u32(data, 0x3C)
        if data[pe:pe + 4] != b"PE\x00\x00":
            raise PeError("not a program (no PE header)")
        magic = _u16(data, pe + 24)
        # The data directories follow the optional header's fixed part: 96 bytes in PE32, 112 in PE32+.
        directories = pe + 24 + (96 if magic == 0x10B else 112)
        rva = _u32(data, directories + 8 * IMPORT_DIRECTORY)
        if not rva:
            return []
        sections = _sections(data, pe)
        at = _offset(sections, rva)
        if at is None:
            raise PeError("the import table is outside the file")
        names = []
        for i in range(MOST_IMPORTS):
            d = at + DESCRIPTOR * i
            name_rva = _u32(data, d + 12)
            # The descriptor of zeros ends the table.
            if not name_rva and not _u32(data, d + 16):
                return names
            where = _offset(sections, name_rva)
            if where is None:
                raise PeError("a library name outside the file")
            name = _name(data, where)
            if name.lower() not in (n.lower() for n in names):
                names.append(name)
        raise PeError("an import table without its end")
    except struct.error:
        raise PeError("a program cut short") from None
