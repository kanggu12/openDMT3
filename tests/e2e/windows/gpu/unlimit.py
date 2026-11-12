"""A copy of the client with its 60 a second limiter taken out, for measuring the game alone as fast as it goes
(gpu/measure.sh). The game folder's own client is never written.

    python3 unlimit.py CLIENT.exe OUT.exe

The PC build's patch section holds every frame at 17, 17 and 16 ms, entered by a jump written over the first
instruction of the game's per-frame function at 0x455430. The copy gets that function's own first bytes back, exactly
as openDMT3's layer does in memory for even pacing and OPENDMT3_INGAME_UNLOCK (native/cardreader/hooks.c,
take_out_limiter), and only when the bytes are exactly the jump measured there. Exit 1 when they are not.
"""
import struct
import sys

# The per-frame function's address, the jump to the limiter with the nop after it, and the function's own first bytes.
AT = 0x455430
JUMP = bytes([0xE9, 0x63, 0xD9, 0xA0, 0x19, 0x90])
PROLOGUE = bytes([0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x0C])


def file_offset(data, va):
    """Where a virtual address of the PE image lies in its file, from its section table (None: in no section)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    optional = struct.unpack_from("<H", data, pe + 20)[0]
    # A 32-bit image's base sits 28 bytes into its optional header.
    base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
    rva = va - base
    table = pe + 24 + optional
    for i in range(sections):
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, table + 40 * i + 8)
        if vaddr <= rva < vaddr + max(vsize, rawsize) and rva - vaddr < rawsize:
            return rawptr + rva - vaddr
    return None


def main(src, out):
    data = bytearray(open(src, "rb").read())
    at = file_offset(data, AT)
    if at is None or bytes(data[at:at + len(JUMP)]) != JUMP:
        print("unlimit: the limiter's jump is not at 0x%x in %s: nothing written" % (AT, src))
        return 1
    data[at:at + len(PROLOGUE)] = PROLOGUE
    open(out, "wb").write(bytes(data))
    print("unlimit: the limiter taken out at file offset 0x%x: %s" % (at, out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
