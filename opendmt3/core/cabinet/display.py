"""The display fix for the PC client: a borderless window over the whole screen, and a mouse that hits.

The client always draws a 1280x768 back buffer. In a window it has two problems:
  * it reads the cursor with GetCursorPos (screen coordinates) and then calls ClientToScreen, which adds the
    window's client origin instead of subtracting it, so clicks land off unless the window sits at 0,0;
  * its window is exactly the back buffer's size, so on a large or scaled monitor it is small.

The fix appends one page of code to the last section and points six call sites at it:
  * the main window's AdjustWindowRect call goes through a helper that, for a borderless (WS_POPUP) window,
    asks Windows to treat the process as DPI aware and sizes the window to the primary monitor; the back
    buffer stays 1280x768 and Direct3D 9 stretches it when it presents;
  * the four GetCursorPos calls go through a helper that returns game coordinates: the client origin taken
    off and the point scaled from the client size to 1280x768;
  * the faulty ClientToScreen call is replaced by the stack cleanup it would have done.
The executable is also marked large-address aware, so the 32-bit game may use up to 4 GB of addresses on a
64-bit system instead of 2 GB. Without it the game ran out of addresses under Wine soon after a card login (the
next screen's data no longer fit, and an allocation that failed was written to).

Helper code (32-bit, assembled once; the bytes are in HELPERS below):

    hook_gcp(POINT* p):                      ; stands in for GetCursorPos
        GetCursorPos(p)                      ; [0x751488]
        if hwnd = [0x19A0BC18]:              ; the window the input code keeps
            o = {0,0}; ClientToScreen(hwnd, &o)          ; [0x751430]
            p -= o
            if GetClientRect(hwnd, &rc) and rc.right > 0 and rc.bottom > 0:   ; [0x75144C]
                p.x = p.x * 1280 / rc.right; p.y = p.y * 768 / rc.bottom
        return 1
    cave_adjust(RECT* r, DWORD style, BOOL menu):        ; stands in for AdjustWindowRect
        if style & WS_POPUP:
            f = GetProcAddress(GetModuleHandleA("user32.dll"), "SetProcessDPIAware"); if f: f()
            *r = {0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)}
        return AdjustWindowRect(r, style, menu)          ; [0x7513C4]

Only the PC build is known (and the fix an earlier openDMT3 made from it, which only lacks the flag); any
other input is refused, and the output is checked against the one result this patch can give.
"""

import hashlib

from opendmt3.core import game as g

PAGE = 0x1000

# File offset -> new bytes. The PE header first, then the six call sites.
EDITS = [
    (0x1C9, "50"),               # SizeOfImage 0x19A64000 -> 0x19A65000 (one more page)
    (0x3B8, "0064"),             # last section's VirtualSize 0x52C2 -> 0x6400
    (0x3C1, "64"),               # last section's SizeOfRawData 0x5400 -> 0x6400
    (0x25FC51, "e83a2c801990"),  # AdjustWindowRect at 0x660851 -> call cave_adjust
    (0x30E0C7, "e83447751990"),  # GetCursorPos at 0x70ECC7 -> call hook_gcp
    (0x30E0E1, "83c408909090"),  # ClientToScreen at 0x70ECE1 -> add esp, 8
    (0x30E650, "e8ab41751990"),  # GetCursorPos at 0x70F250 -> call hook_gcp
    (0x30E939, "e8c23e751990"),  # GetCursorPos at 0x70F539 -> call hook_gcp
    (0x30E94A, "e8b13e751990"),  # GetCursorPos at 0x70F54A -> call hook_gcp
]

# The helpers, loaded at 0x19E63400 (hook_gcp) and 0x19E63490 (cave_adjust), then two strings at +0x300.
HELPERS = bytes.fromhex(
    "5589e583ec18ff7508ff158814750085c074778b0d18bca01985c97468c745f800000000c745fc000000008d45f85051ff15"
    "301475008b4d088b45f829018b45fc2941048d45e850ff3518bca019ff154c14750085c0742d8b4d08837df0007e24837df4"
    "007e1e8b0169c00005000099f77df089018b410469c00003000099f77df4894104b80100000089ec5dc204005589e5f7450c"
    "00000080742ee83c0000006a00ff150c1475008b4d08c70100000000c74104000000008941086a01ff150c1475008b4d0889"
    "410cff7510ff750cff7508ff15c41375005dc20c00680037e619ff150c11750085c07412680b37e61950ff151012750085c0"
    "7402ffd0c3"
)
STRINGS_AT = 0x300
STRINGS = b"user32.dll\x00SetProcessDPIAware\x00"
# The PE header's Characteristics (e_lfanew 0x178 + 0x16) and its large-address-aware bit.
CHARACTERISTICS_AT = 0x18E
LARGE_ADDRESS_AWARE = 0x20


class PatchError(Exception):
    pass


def large_address_aware(data):
    """A program with the large-address-aware flag set and nothing else changed (the flag is a bit of the PE header's
    Characteristics, found through the header's own pointer, so it fits any build). A modified PC client gets this
    alone: the screen fit's places are the PC build's, but without the flag a 32-bit client has 2 GB of addresses
    (measured under Wine: a modified client without it stopped 30 s after TOUCH to START, reading the title's video;
    with it, it played). PatchError for what is no program."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PatchError("not a program")
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if pe + 0x18 > len(data) or data[pe:pe + 4] != b"PE\x00\x00":
        raise PatchError("not a program")
    out = bytearray(data)
    # The COFF header follows the signature: Characteristics is its last field, 18 bytes in.
    out[pe + 4 + 18] |= LARGE_ADDRESS_AWARE
    return bytes(out)


def patch(data):
    """The fixed client, from the bytes of the PC client or of the fix an earlier openDMT3 made."""
    digest = hashlib.sha256(data).hexdigest()
    out = bytearray(data)
    if digest == g.PC_BUILD:
        for offset, new in EDITS:
            b = bytes.fromhex(new)
            out[offset:offset + len(b)] = b
        page = bytearray(PAGE)
        page[:len(HELPERS)] = HELPERS
        page[STRINGS_AT:STRINGS_AT + len(STRINGS)] = STRINGS
        out += page
    elif digest != g.PC_BUILD_DISPLAY_FIX_EARLIER:
        raise PatchError("not the PC client build this fix is made for")
    out[CHARACTERISTICS_AT] |= LARGE_ADDRESS_AWARE
    if hashlib.sha256(out).hexdigest() != g.PC_BUILD_DISPLAY_FIX:
        raise PatchError("the fixed client came out different from the expected result")
    return bytes(out)
