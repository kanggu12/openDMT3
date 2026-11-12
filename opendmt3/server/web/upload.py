"""Receiving a file the admin uploads (a database on the Backups tab, a song list on the Song list tab), as a form
(multipart/form-data) and through each one's API twin (the file itself is the request's body): written to its own file
as it comes, never held in memory whole, and counted, so an upload past its limit stops at that byte.

The wall in app.py leaves these two routes' bodies alone (its BODY_LIMIT is for every other request); the reading here
is their limit. Starlette's own form reader is not used: it keeps a file in memory or in the system's temporary folder,
not in backups/, and reads the whole body before the form's token can be looked at.
"""

import hmac

from starlette.concurrency import run_in_threadpool

# python-multipart's streaming parser, the one Starlette's own form reader is built on (named multipart before 0.0.13).
try:
    import python_multipart as multipart
    from python_multipart.multipart import parse_options_header
except ModuleNotFoundError:  # pragma: no cover  (the older name)
    import multipart
    from multipart.multipart import parse_options_header

from opendmt3.server.services import backups as bak

# What a form's body may hold besides its file: the token, each part's headers and the boundaries between them.
FORM_ROOM = 64 * 1024
# A form's own fields beside the file (its token): this many at most, each this many bytes at most.
FIELDS_MOST = 4
FIELD_BYTES = 1024
# Bytes gathered before they are written, on a worker thread: the event loop the game server shares never waits on the
# disk, and the thread pool is not asked for every piece the network brings.
WRITE_EVERY = 1 << 20


class FormExpired(Exception):
    """The form's token was missing or wrong before its file came (a form from another site, or an old page): the file
    is not read at all."""


class Malformed(Exception):
    """A body that is no form this page sends (no boundary, two files, a field too long): read no further."""


def declared_too_large(request, most):
    """True when the request says beforehand (Content-Length) that its body is longer than `most` bytes, or says it in
    a way that cannot be read: refused before a byte of it is read."""
    declared = request.headers.get("content-length")
    if declared is None:
        # Sent in pieces without a length: counted as it comes instead.
        return False
    return not declared.isdigit() or int(declared) > most


class _Writer:
    """Bytes gathered and written to an open file WRITE_EVERY at a time, counted against a limit."""

    def __init__(self, out, most, too_large=bak.too_large):
        self.out, self.most, self.too_large = out, most, too_large
        # How many bytes came, and those not written yet.
        self.size, self.pending = 0, bytearray()

    def add(self, data):
        """Count `data` and keep it for the next write; the refusal (too_large) once the count passes the limit."""
        self.size += len(data)
        if self.size > self.most:
            raise self.too_large()
        self.pending += data

    async def flush(self, everything=False):
        """Write what was gathered, once there is WRITE_EVERY of it (or all of it at the end), on a worker thread."""
        if self.pending and (everything or len(self.pending) >= WRITE_EVERY):
            data, self.pending = bytes(self.pending), bytearray()
            await run_in_threadpool(self.out.write, data)


async def body_to(request, out, most, too_large=bak.too_large):
    """The API's upload: the request's body, which is the file, written to `out` (a file open for writing) as it comes;
    returns its size. too_large() is raised once it passes `most` bytes, before the rest is read (a backup's refusal
    by default)."""
    writer = _Writer(out, most, too_large)
    async for chunk in request.stream():
        writer.add(chunk)
        await writer.flush()
    await writer.flush(everything=True)
    return writer.size


async def form_to(request, out, most, token, too_large=bak.too_large, named=False):
    """A tab's upload: a multipart form whose file (the field `file`) is written to `out` as it comes, its other fields
    read into memory; returns the file's size (0 when the form came without one), with named also the name the file
    came with ((size, name)).

    The form's token (the field `csrf`, which the page puts before its file, as browsers send fields in the page's
    order) must have come, and be `token`, before the file's first byte: FormExpired otherwise, and nothing of the file
    is written. too_large() once the file passes `most` bytes (a backup's refusal by default); Malformed for a body this
    page never sends."""
    kind, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if kind != b"multipart/form-data" or not boundary:
        raise Malformed("not a multipart form")
    writer = _Writer(out, most, too_large)
    # The part being read: its headers as they come, its name, and whether it is the file.
    part = {"field": b"", "value": b"", "disposition": b"", "name": "", "file": False, "data": bytearray()}
    # The text fields by name, the file's field (one at most), and whether the form's last boundary came.
    fields, files, ended = {}, [], []

    def on_part_begin():
        # A new part: nothing of the last one carries over.
        part.update(field=b"", value=b"", disposition=b"", name="", file=False, data=bytearray())

    def on_header_field(data, start, end):
        part["field"] += data[start:end]

    def on_header_value(data, start, end):
        part["value"] += data[start:end]

    def on_header_end():
        # Only the part's Content-Disposition says what it is (its name, and a file's name).
        if part["field"].lower() == b"content-disposition":
            part["disposition"] = part["value"]
        part["field"], part["value"] = b"", b""

    def on_headers_finished():
        _, says = parse_options_header(part["disposition"])
        part["name"] = says.get(b"name", b"").decode("utf-8", "replace")
        if b"filename" in says:
            # The file: one, in the field the page names, and only after the right token.
            if part["name"] != "file" or files:
                raise Malformed("a file in another field, or a second file")
            if not hmac.compare_digest(fields.get("csrf", ""), token):
                raise FormExpired()
            part["file"] = True
            # The file's own name, as the browser sent it (only shown, never used as a path).
            files.append(says.get(b"filename", b"").decode("utf-8", "replace"))
        elif len(fields) >= FIELDS_MOST:
            raise Malformed("more fields than the page's form has")

    def on_part_data(data, start, end):
        if part["file"]:
            # The file's bytes, counted against the limit and gathered for the next write.
            writer.add(data[start:end])
            return
        part["data"] += data[start:end]
        if len(part["data"]) > FIELD_BYTES:
            raise Malformed("a field longer than the page's form sends")

    def on_part_end():
        if not part["file"]:
            # A field of text (the token): kept by its name, as the form sent it.
            fields[part["name"]] = part["data"].decode("utf-8", "replace")

    def on_end():
        # The closing boundary: the form came whole (a body cut short never says so).
        ended.append(True)

    parser = multipart.MultipartParser(boundary, {
        "on_part_begin": on_part_begin, "on_part_data": on_part_data, "on_part_end": on_part_end,
        "on_header_field": on_header_field, "on_header_value": on_header_value, "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished, "on_end": on_end})
    try:
        async for chunk in request.stream():
            # The callbacks above run inside write(): the file's bytes are gathered there, written here.
            parser.write(chunk)
            await writer.flush()
        parser.finalize()
    except multipart.exceptions.FormParserError as e:
        # The library's own word for a body that is no multipart form (our callbacks' refusals pass through as raised).
        raise Malformed(str(e)) from e
    if not ended:
        raise Malformed("the form was cut short")
    await writer.flush(everything=True)
    if not files and not hmac.compare_digest(fields.get("csrf", ""), token):
        # No file at all, and not this site's form either: the form expired (as every other form says it).
        raise FormExpired()
    return (writer.size, files[0] if files else None) if named else writer.size
