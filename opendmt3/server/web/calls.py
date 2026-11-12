"""The API's calls in one table: every route under /api/v1, with who may make it, what it takes, the main fields of its
answer (or the file it gives) and its own errors. The OpenAPI document (GET /api/v1/openapi.json, openapi() below) is
made from this table, and tests/server/test_api.py reads it too, beside the routes api.py serves and the guide docs/api.md:
each call must be all three, with the same who, the same parameters and the same errors, so none can drift from the
others. docs/api.md stays written by hand for people; this table is for programs.

Paths are written as the guide writes them ({name} for a part of the path, without Starlette's converters); a call's
area is the guide's heading it sits under. Only the standard library: the tests read it without the web libraries.
"""

import re

# Who may make a call, as the guide's Who column says it: without a token, with any account's, with an admin's.
WHO = ("anyone", "signed in", "admin")
# JSON's types, the only ones a parameter or a field has here ("null" for a field that may be, or always is, null).
TYPES = ("string", "integer", "boolean", "array", "object", "number", "null")


class Param:
    """A value a call takes: its name, where it goes (path, query or body), its JSON type, what it is, whether the call
    needs it, and the only values it takes (enum)."""

    def __init__(self, name, where, type, doc, required=False, enum=None):
        self.name, self.where, self.type, self.doc = name, where, type, doc
        # A part of the path is always there; a query's or a body's field when the call says so.
        self.required = required or where == "path"
        self.enum = list(enum) if enum else None


def path(name, type, doc, enum=None):
    """A part of the call's path."""
    return Param(name, "path", type, doc, enum=enum)


def query(name, type, doc, enum=None):
    """A value of the call's query (?name=...), never needed."""
    return Param(name, "query", type, doc, enum=enum)


def body(name, type, doc, required=False, enum=None):
    """A field of the call's JSON body."""
    return Param(name, "body", type, doc, required, enum)


class Call:
    """One route of the API: its method and path, who may make it, the guide's heading it sits under (area), what it
    does (summary), what it takes (params), its answer's main fields ({name: type}; a name ending in ? is only in some
    answers; a type may be "integer|null"), or the file it gives instead (files: its content type), the body it takes
    as a file (upload: its content type), its status when it works, and its own errors [(status, code)]."""

    def __init__(self, method, route, who, area, summary, params=(), answer=None, files=None, upload=None, status=200,
                 errors=(), body_needed=None):
        self.method, self.path, self.who, self.area, self.summary = method, route, who, area, summary
        self.params, self.answer, self.files, self.upload = list(params), dict(answer or {}), files, upload
        self.status, self.errors = status, list(errors)
        # Whether the call needs a body at all: a file to upload does, a JSON body when a field is needed; a call that
        # also works without one (the song list's import reads the game folder again) says False.
        self.body_needed = body_needed

    def where(self, place):
        """The call's parameters of one place (path, query or body), in the table's order."""
        return [p for p in self.params if p.where == place]

    @property
    def name(self):
        """The call's operationId: its method and its path after /api/v1/, in words joined by underscores."""
        return "%s_%s" % (self.method.lower(), "_".join(re.findall(r"[a-z0-9]+", self.path[len(BASE):].lower())))


# Where every call of the table is.
BASE = "/api/v1/"
# The guide's headings under Calls, in its order: each call's area is one of them.
AREAS = ("The server, signing in and out", "Your account", "Records", "Downloads", "The admin's players",
         "The admin's cabinets, status, notice and logs", "The admin's backups")
SERVER, ACCOUNT, RECORDS, DOWNLOADS, PLAYERS, ADMIN, BACKUPS = AREAS

# What an account is, as GET /api/v1/me gives it and many changes answer it.
ACCOUNT_FIELDS = {"login_id": "string", "dj_name": "string", "card": "string", "is_admin": "boolean",
                  "player": "integer", "dj_card": "object"}
# The words of an answer meant for people, in English or in Korean.
LANG = query("lang", "string", "The words meant for people in the answer: English, or Korean with ko.",
             enum=("en", "ko"))
# The parts of a path that name the same thing in many calls.
LOGIN_ID = path("login_id", "string", "An account's ID, in any letter case.")
BACKUP = path("name", "string", "A backup's file name, as GET /api/v1/backups lists it.")
SONG = path("number", "integer", "A song's number.")
# The plays log's filter, read by the log's page of plays and by its file.
LOG_FILTER = (query("player", "integer", "Only this account's plays (its number)."),
              query("days", "integer", "Only the last 1, 7 or 30 days.", enum=(1, 7, 30)),
              query("q", "string", "Only songs whose title has this word, or the song of this number."))

CALLS = [
    # ------------------------------------------------------------------------- the server, signing in and out
    Call("GET", "/api/v1/status", "anyone", SERVER,
         "That this is openDMT3, its version, the game's port, and whether it hands out the launcher's updates.",
         answer={"server": "string", "version": "string", "game_port": "integer", "updates": "boolean"}),
    Call("GET", "/api/v1/openapi.json", "anyone", SERVER,
         "This document: every call of the API, made from the table the guide and the routes are checked against.",
         answer={"openapi": "string", "info": "object", "paths": "object", "components": "object"}),
    Call("POST", "/api/v1/session", "anyone", SERVER, "Sign in with an ID and a password: the account and a token.",
         params=(body("login_id", "string", "The account's ID.", required=True),
                 body("password", "string", "Its password.", required=True)),
         answer=dict(ACCOUNT_FIELDS, token="string"),
         errors=((400, "bad_request"), (401, "wrong_sign_in"), (429, "too_many_tries"))),
    Call("DELETE", "/api/v1/session", "signed in", SERVER,
         "Sign out: the token sent ends (a named token is revoked), and no other.", answer={"signed_out": "boolean"}),
    Call("GET", "/api/v1/licenses", "anyone", SERVER,
         "openDMT3's own licence, the parts the server and the launcher it hands out are made with and their licences, "
         "and the fonts the site serves, each licence with the faces it covers and its text in full.",
         params=(LANG,), answer={"own": "object", "parts": "array", "licenses": "array"}),
    # ---------------------------------------------------------------------------------------- your account
    Call("GET", "/api/v1/me", "signed in", ACCOUNT, "The account the token signs in.", answer=ACCOUNT_FIELDS),
    Call("POST", "/api/v1/me/dj_name", "signed in", ACCOUNT, "A new DJ name for the account.",
         params=(body("dj_name", "string", "The new name, 1 to 8 characters.", required=True),),
         answer=ACCOUNT_FIELDS, errors=((400, "bad_request"), (400, "refused"))),
    Call("POST", "/api/v1/me/password", "signed in", ACCOUNT,
         "A new password and a new card; the account's other tokens end, and the answer has a new one.",
         params=(body("password", "string", "The current password.", required=True),
                 body("new_password", "string", "The new one: 6 to 16 letters and digits.", required=True)),
         answer=dict(ACCOUNT_FIELDS, token="string"),
         errors=((400, "bad_request"), (400, "refused"), (403, "wrong_password"), (429, "too_many_tries"))),
    Call("POST", "/api/v1/me/dj_card", "signed in", ACCOUNT,
         "The DJ card's icon, plate, pattern and comment (any of them).",
         params=(body("icon", "integer", "An icon's number from GET /api/v1/dj_cards."),
                 body("plate", "integer", "A plate's number from GET /api/v1/dj_cards."),
                 body("pattern", "integer", "A pattern's number from GET /api/v1/dj_cards."),
                 body("comment", "string", "One line over the plate, up to 12 characters.")),
         answer=ACCOUNT_FIELDS, errors=((400, "bad_request"), (400, "refused"))),
    Call("GET", "/api/v1/dj_cards", "signed in", ACCOUNT,
         "The DJ card's choices this server has pictures for, and the comment's length.",
         answer={"icon": "array", "plate": "array", "pattern": "array", "comment_max": "integer"}),
    Call("GET", "/api/v1/dj_cards/{kind}/{number}.png", "signed in", ACCOUNT, "One choice's picture.",
         params=(path("kind", "string", "What the picture is.", enum=("icon", "plate", "pattern")),
                 path("number", "integer", "The choice's number.")),
         files="image/png", errors=((404, "not_found"),)),
    Call("GET", "/api/v1/tokens", "signed in", ACCOUNT,
         "The account's named tokens, newest first, with when each was made and last used; never the tokens.",
         answer={"tokens": "array"}),
    Call("POST", "/api/v1/tokens", "signed in", ACCOUNT,
         "A new named token for the account: the token itself is in this answer only.",
         params=(body("name", "string", "What it is for: 1 to 40 characters on one line.", required=True),
                 body("scope", "string", "read: GET calls only, none of an admin's; write: every call the account "
                                         "may make.", required=True, enum=("read", "write"))),
         answer={"id": "string", "name": "string", "scope": "string", "created_at": "integer", "used_at": "null",
                 "token": "string"},
         status=201, errors=((400, "bad_request"), (400, "refused"))),
    Call("DELETE", "/api/v1/tokens/{id}", "signed in", ACCOUNT,
         "One of the account's named tokens revoked for good (it may be the one calling).",
         params=(path("id", "string", "The token's id: the 12 hex digits after odt3_."),),
         answer={"revoked": "string", "name": "string"}, errors=((404, "unknown_token"),)),
    # ------------------------------------------------------------------------------------------ records
    Call("GET", "/api/v1/plays", "signed in", RECORDS,
         "The newest 50 plays, yours or everyone's, each marked when it beat its player's best; or the newest records.",
         params=(query("everyone", "boolean", "Everyone's plays (1), not only yours."),
                 query("records", "boolean", "The newest records (1): plays that beat their player's best.")),
         answer={"plays": "array", "total?": "integer"}),
    Call("GET", "/api/v1/rankings", "signed in", RECORDS,
         "One mode's ranking: by total, by the best 30's average, or this month's with the months before it.",
         params=(query("mode", "integer", "The mode, 0 to 255 (0 is STAR); without it, the first mode played."),
                 query("by", "string", "What it ranks by.", enum=("total", "best30", "month"))),
         answer={"mode": "integer", "name": "string", "modes": "array", "by": "string", "rows": "array",
                 "start?": "integer", "past?": "array"},
         errors=((400, "bad_request"),)),
    Call("GET", "/api/v1/songs", "signed in", RECORDS,
         "Every song with what was played on it, or those whose title, composer or number Find matches.",
         params=(query("q", "string", "A word of the title or the composer, or a song's number."),),
         answer={"songs": "array", "total": "integer"}),
    Call("GET", "/api/v1/songs/{number}", "signed in", RECORDS, "One song's boards, one per chart.", params=(SONG,),
         answer={"number": "integer", "title": "string", "genre": "string", "composer": "string", "charts": "array",
                 "jacket": "boolean"},
         errors=((404, "unknown_song"),)),
    Call("GET", "/api/v1/songs/{number}/jacket.png", "signed in", RECORDS, "The song's picture.", params=(SONG,),
         files="image/png", errors=((404, "not_found"),)),
    Call("GET", "/api/v1/djs/{player}", "signed in", RECORDS,
         "A player's records: the DJ card, counts, best scores, recent plays, activity and places.",
         params=(path("player", "integer", "The player's account number."),),
         answer={"player": "integer", "dj_name": "string", "dj_card": "object", "summary": "object", "bests": "array",
                 "recent": "array", "activity": "object", "places": "array"},
         errors=((404, "unknown_player"),)),
    Call("GET", "/api/v1/cabinets", "signed in", RECORDS,
         "The cabinets connected now and who plays on each; with all, every cabinet seen (an admin's).",
         params=(query("all", "boolean", "Every cabinet seen (1), for an admin's token."),),
         answer={"cabinets": "array"}, errors=((403, "admin_only"), (403, "read_only"))),
    # ---------------------------------------------------------------------------------------- downloads
    Call("GET", "/api/v1/download", "signed in", DOWNLOADS,
         "The installer's facts, the address the launcher asks for, and the name the installer comes under.",
         answer={"installer": "object|null", "address": "string", "file": "string"}),
    Call("GET", "/api/v1/download/windows", "signed in", DOWNLOADS,
         "The installer with this server's address on its end.", files="application/octet-stream",
         errors=((404, "no_installer"),)),
    # ------------------------------------------------------------------------------------ the admin's players
    Call("GET", "/api/v1/players", "admin", PLAYERS, "Every account, with whether it is disabled and its last login.",
         answer={"players": "array"}),
    Call("POST", "/api/v1/players", "admin", PLAYERS,
         "An account made, with its password (made by the server when none is sent) and the message to send.",
         params=(body("login_id", "string", "The new account's ID.", required=True),
                 body("password", "string", "Its password; without one the server makes one."),
                 body("dj_name", "string", "Its DJ name; without one, the ID."),
                 body("is_admin", "boolean", "Whether it opens the admin pages too."), LANG),
         answer=dict(ACCOUNT_FIELDS, password="string", message="string"), status=201,
         errors=((400, "bad_request"), (400, "refused"))),
    Call("POST", "/api/v1/players/{login_id}/password", "admin", PLAYERS,
         "A new password (and card) the server makes, with the message to send.", params=(LOGIN_ID, LANG),
         answer={"login_id": "string", "password": "string", "message": "string"}, errors=((404, "unknown_player"),)),
    Call("POST", "/api/v1/players/{login_id}/dj_name", "admin", PLAYERS, "A player's DJ name.",
         params=(LOGIN_ID, body("dj_name", "string", "The new name, 1 to 8 characters.", required=True)),
         answer={"login_id": "string", "dj_name": "string"},
         errors=((400, "bad_request"), (400, "refused"), (404, "unknown_player"))),
    Call("POST", "/api/v1/players/{login_id}/admin", "admin", PLAYERS, "Admin rights given.", params=(LOGIN_ID,),
         answer={"login_id": "string", "is_admin": "boolean"}, errors=((404, "unknown_player"),)),
    Call("DELETE", "/api/v1/players/{login_id}/admin", "admin", PLAYERS,
         "Admin rights taken (never from the only enabled admin).", params=(LOGIN_ID,),
         answer={"login_id": "string", "is_admin": "boolean"}, errors=((400, "refused"), (404, "unknown_player"))),
    Call("POST", "/api/v1/players/{login_id}/disable", "admin", PLAYERS,
         "The account disabled (never the only enabled admin).", params=(LOGIN_ID,),
         answer={"login_id": "string", "disabled": "boolean"}, errors=((400, "refused"), (404, "unknown_player"))),
    Call("POST", "/api/v1/players/{login_id}/enable", "admin", PLAYERS, "The account enabled again.",
         params=(LOGIN_ID,), answer={"login_id": "string", "disabled": "boolean"}, errors=((404, "unknown_player"),)),
    Call("DELETE", "/api/v1/players/{login_id}", "admin", PLAYERS, "The account deleted, its plays with it.",
         params=(LOGIN_ID,), answer={"deleted": "string"}, errors=((400, "refused"), (404, "unknown_player"))),
    Call("DELETE", "/api/v1/players/{login_id}/plays", "admin", PLAYERS,
         "The player's plays reset after a backup; the account, its DJ card and its settings stay.",
         params=(LOGIN_ID,), answer={"login_id": "string", "plays": "integer", "kept_as": "string"},
         errors=((404, "unknown_player"),)),
    Call("DELETE", "/api/v1/plays", "admin", PLAYERS,
         "Every player's plays reset after a backup; accounts, DJ cards and settings stay.",
         answer={"plays": "integer", "kept_as": "string"}),
    # ----------------------------------------------------------------- the admin's cabinets, status, notice, logs
    Call("POST", "/api/v1/cabinets/{id}/name", "admin", ADMIN, "The name the admin pages show for a cabinet.",
         params=(path("id", "integer", "The cabinet's number, as GET /api/v1/cabinets?all=1 gives it."),
                 body("name", "string", "Its name; empty, its address again.", required=True)),
         answer={"cabinets": "array"}, errors=((400, "bad_request"), (404, "unknown_cabinet"))),
    Call("GET", "/api/v1/server", "admin", ADMIN,
         "The Status page: the version, the numbers, the last backup, maintenance, and what may want a look.",
         params=(LANG,),
         answer={"version": "string", "game_port": "integer", "started": "integer|null", "connected": "integer",
                 "accounts": "object", "cabinets": "integer", "today": "object", "week": "object", "month": "object",
                 "database_bytes": "integer", "last_backup": "integer|null", "maintenance": "boolean",
                 "look": "array", "song_list": "object"}),
    Call("GET", "/api/v1/server/song_list", "admin", ADMIN,
         "The Song list tab: the song list's state, the game's files found on the server PC with their lines, the "
         "places looked in, and whether the server shows its PC's other folders.",
         params=(LANG,), answer={"song_list": "object", "found": "array", "places": "array", "browse": "boolean"}),
    Call("POST", "/api/v1/server/song_list", "admin", ADMIN,
         "Import the song list (with its jackets and the DJ cards): from the game folder the server was given (no "
         "body), from a path on the server PC (a game folder, an archive holding one, or a song list), or a song list "
         "as the body, up to 64 MB.",
         params=(body("path", "string", "A game folder, an archive holding one, or a song list on the server PC."),),
         upload="application/zip", body_needed=False, answer={"song_list": "object", "lines": "array"},
         errors=((400, "bad_request"), (400, "refused"), (404, "no_game_folder"), (409, "busy"), (409, "not_read"),
                 (413, "too_large"))),
    Call("GET", "/api/v1/server/folders", "admin", ADMIN,
         "The Song list tab's folder browser: a folder of the server PC and the folders in it.",
         params=(query("path", "string", "The folder (the top, /, when not given)."),),
         answer={"path": "string", "up": "string|null", "folders": "array"}, errors=((400, "refused"),)),
    Call("GET", "/api/v1/notice", "signed in", ADMIN, "The notice at the top of every page, or null.",
         answer={"notice": "object|null"}),
    Call("POST", "/api/v1/notice", "admin", ADMIN, "Set the notice (an empty text clears it).",
         params=(body("text", "string", "One line of up to 200 characters.", required=True),),
         answer={"notice": "object|null"}, errors=((400, "bad_request"), (400, "refused"))),
    Call("DELETE", "/api/v1/notice", "admin", ADMIN, "Clear the notice.", answer={"notice": "null"}),
    Call("GET", "/api/v1/maintenance", "signed in", ADMIN,
         "Whether the server is in maintenance (the game server refuses card logins), since when, and by whom.",
         answer={"on": "boolean", "at?": "integer", "by?": "string"}),
    Call("POST", "/api/v1/maintenance", "admin", ADMIN,
         "Maintenance on: the game server refuses every card login; cabinets online stay connected.",
         answer={"on": "boolean", "at": "integer", "by": "string"}),
    Call("DELETE", "/api/v1/maintenance", "admin", ADMIN, "Maintenance off: the cabinets log in again.",
         answer={"on": "boolean"}),
    Call("GET", "/api/v1/log", "admin", ADMIN, "The newest changes and game messages, and how many there are.",
         answer={"changes": "array", "messages": "array", "counts": "object"}),
    Call("GET", "/api/v1/log/plays", "admin", ADMIN,
         "Every play the filter leaves, 50 a page, newest first, with what it leaves counted.",
         params=LOG_FILTER + (query("page", "integer", "The page, from 1."),),
         answer={"plays": "array", "totals": "object", "older": "boolean", "newer": "boolean", "page": "integer",
                 "people": "array"},
         errors=((400, "bad_request"),)),
    Call("GET", "/api/v1/log/plays.csv", "admin", ADMIN, "Every play the filter leaves, all its pages, as CSV.",
         params=LOG_FILTER, files="text/csv", errors=((400, "bad_request"),)),
    # ------------------------------------------------------------------------------------ the admin's backups
    Call("GET", "/api/v1/backups", "admin", BACKUPS, "Every backup, newest first, and how many of each kind stay.",
         answer={"backups": "array", "keep": "integer"}),
    Call("POST", "/api/v1/backups", "admin", BACKUPS, "Back the database up now.", answer={"made": "string"},
         status=201),
    Call("POST", "/api/v1/backups/upload", "admin", BACKUPS,
         "A database file kept as a backup of the kind upload once it passes the checks, up to 256 MB.",
         upload="application/octet-stream", answer={"uploaded": "string"}, status=201,
         errors=((400, "refused"), (413, "too_large"))),
    Call("GET", "/api/v1/backups/{name}", "admin", BACKUPS, "A backup's file.", params=(BACKUP,),
         files="application/vnd.sqlite3", errors=((404, "unknown_backup"),)),
    Call("DELETE", "/api/v1/backups/{name}", "admin", BACKUPS, "A backup deleted.", params=(BACKUP,),
         answer={"deleted": "string"}, errors=((404, "unknown_backup"),)),
    Call("POST", "/api/v1/backups/{name}/restore", "admin", BACKUPS,
         "The database put back to a backup, the current one backed up first.", params=(BACKUP,),
         answer={"restored": "string", "kept_as": "string"}, errors=((400, "refused"), (404, "unknown_backup"))),
]


# ------------------------------------------------------------------------------------------ the OpenAPI document

def _schema(type_name):
    """A field's JSON schema from the table's type: "integer", or "object|null" for a field that may be null."""
    types = type_name.split("|")
    return {"type": types[0] if len(types) == 1 else types}


def _answer_schema(fields):
    """An answer's main fields as an object's schema: those without ? are in every answer (required)."""
    properties = {name.rstrip("?"): _schema(kind) for name, kind in fields.items()}
    required = [name for name in fields if not name.endswith("?")]
    return {"type": "object", "properties": properties, "required": required}


def _refusals(call):
    """Every error a call can answer, by status: its own, then what every call with a token answers (401 sign_in), an
    admin's to another account's token (403 admin_only), and a read-only named token's (403 read_only)."""
    errors = list(call.errors)
    if call.who != "anyone":
        errors.append((401, "sign_in"))
    if call.who == "admin":
        errors.append((403, "admin_only"))
    if call.who != "anyone" and (call.who == "admin" or call.method not in ("GET", "HEAD")):
        errors.append((403, "read_only"))
    by_status = {}
    for status, code in errors:
        if code not in by_status.setdefault(status, []):
            by_status[status].append(code)
    return by_status


def openapi(version):
    """The OpenAPI 3.1 document of the API, made from CALLS: each call's method and path, who may make it (x-who, and
    no security for anyone), its parameters, its body (JSON, or a file), its answer's main fields or its file, and its
    errors."""
    paths = {}
    for call in CALLS:
        operation = {"operationId": call.name, "summary": call.summary, "tags": [call.area], "x-who": call.who}
        parameters = [{"name": p.name, "in": p.where, "required": p.required, "description": p.doc,
                       "schema": dict(_schema(p.type), **({"enum": p.enum} if p.enum else {}))}
                      for p in call.params if p.where in ("path", "query")]
        if parameters:
            operation["parameters"] = parameters
        fields = call.where("body")
        content = {}
        if fields:
            # A JSON object with the call's fields; those the call needs are required.
            content["application/json"] = {"schema": {
                "type": "object", "required": [p.name for p in fields if p.required], "properties": {
                    p.name: dict(_schema(p.type), description=p.doc, **({"enum": p.enum} if p.enum else {}))
                    for p in fields}}}
        if call.upload:
            # The file itself is the body.
            content[call.upload] = {"schema": {"type": "string", "format": "binary"}}
        if content:
            needed = call.body_needed
            if needed is None:
                # A file to upload is the body; a JSON body is needed when one of its fields is.
                needed = bool(call.upload) and not fields or any(p.required for p in fields)
            operation["requestBody"] = {"required": needed, "content": content}
        if call.files:
            answer = {"description": call.summary, "content": {call.files: {
                "schema": {"type": "string", "format": "binary"}}}}
        else:
            answer = {"description": call.summary, "content": {"application/json": {
                "schema": _answer_schema(call.answer)}}}
        operation["responses"] = {str(call.status): answer}
        for status, codes in sorted(_refusals(call).items()):
            operation["responses"][str(status)] = {"description": ", ".join(codes), "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Error"}}}}
        if call.who == "anyone":
            # No token needed.
            operation["security"] = []
        paths.setdefault(call.path, {})[call.method.lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {"title": "openDMT3 API", "version": version,
                 "description": "Everything the site shows and does, as JSON. Sign in with POST /api/v1/session, or "
                                "make a named token on My account, and send the token as Authorization: Bearer. "
                                "x-who says who may make each call: anyone, signed in (any account's token) or admin "
                                "(an admin account's). docs/api.md in the repository says the rest."},
        "paths": paths,
        "components": {
            "securitySchemes": {"token": {"type": "http", "scheme": "bearer",
                                          "description": "A sign-in token from POST /api/v1/session, or a named token "
                                                         "(odt3_...) made on My account."}},
            "schemas": {"Error": {"type": "object", "required": ["error"], "properties": {"error": {
                "type": "object", "required": ["code", "message"],
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}}}},
        },
        "security": [{"token": []}],
    }
