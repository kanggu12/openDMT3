"""Tests for uploading a backup: a database file the admin brings from elsewhere, on the Backups tab and through its API
twin, written into backups/ as it comes and checked before it is kept (an SQLite file, its integrity check, this
project's tables, a version this server opens), then kept under a backup's own name and restored as any other. What is
refused says why in words, and leaves nothing behind. The site's 64 KiB body limit stays for every other request.

The service's checks need nothing more; the pages and the API need the web libraries (skipped without them).
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from opendmt3.server import db
from opendmt3.server.services import accounts, backups
# A database as an older openDMT3 left it, with one account and one play (tests/server/test_db.py).
from tests.server.test_db import older
# The site, its forms and the API's calls with a token, on a temporary data folder (tests/server/test_api.py).
from tests.server.test_api import ApiBase
from tests.server.test_web import WEB


def database_file(folder, login_id="RIO"):
    """A backup made by another server (its own data folder in `folder`), with one account: its file's bytes."""
    path = os.path.join(folder, "openDMT3.sqlite")
    connection = db.connect(path)
    try:
        accounts.Accounts(connection).create(login_id, "pass1234")
    finally:
        connection.close()
    name = backups.make(path, folder)
    with open(os.path.join(folder, "backups", name), "rb") as f:
        return f.read()


class CheckUploadTest(unittest.TestCase):
    """backups.upload_part, check_upload and keep_upload: what is kept, what is refused, and that nothing refused
    stays."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        # Files made for a test, apart from the server's data folder.
        self.made = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.data)
        shutil.rmtree(self.made)

    def uploaded(self, content):
        """An upload of `content` as the routes write it (upload_part), then kept (keep_upload): the backup's name."""
        out, part = backups.upload_part(self.data)
        with out:
            out.write(content)
        return backups.keep_upload(self.data, part)

    def leftovers(self):
        """Every file in backups/ that is not a backup the list shows: an upload's file left behind, a journal."""
        where = backups.folder(self.data)
        listed = {b["name"] for b in backups.all_backups(self.data)}
        return sorted(n for n in os.listdir(where) if n not in listed) if os.path.isdir(where) else []

    def refused(self, content, key):
        """`content` refused by the checks with the words of `key`, and nothing of it left in backups/."""
        with self.assertRaises(backups.BackupError) as caught:
            self.uploaded(content)
        self.assertEqual(caught.exception.key, key)
        self.assertEqual((backups.all_backups(self.data), self.leftovers()), ([], []))
        return caught.exception

    def file_of(self, make):
        """The bytes of an SQLite file `make(connection)` fills in."""
        path = os.path.join(self.made, "made-%d.sqlite" % len(os.listdir(self.made)))
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            make(connection)
        finally:
            connection.close()
        with open(path, "rb") as f:
            return f.read()

    def test_a_backup_of_another_server_is_kept_and_restores(self):
        content = database_file(self.made)
        name = self.uploaded(content)
        listed = backups.all_backups(self.data)
        self.assertEqual([(b["name"], b["kind"], b["size"]) for b in listed], [(name, "upload", len(content))])
        self.assertEqual(self.leftovers(), [])
        if os.name != "nt":
            # A backup's file is its owner's alone, an uploaded one too.
            self.assertEqual(os.stat(os.path.join(self.data, "backups", name)).st_mode & 0o777, 0o600)
        # Restored as any other backup: the other server's account is here now.
        path = os.path.join(self.data, "openDMT3.sqlite")
        db.connect(path).close()
        backups.restore(path, self.data, name)
        connection = db.connect(path)
        try:
            self.assertEqual([r[0] for r in connection.execute("SELECT login_id FROM accounts")], ["RIO"])
        finally:
            connection.close()

    def test_every_older_version_and_a_live_databases_own_file_are_kept(self):
        for version in range(1, db.VERSION):
            with self.subTest(version=version):
                path = os.path.join(self.made, "v%d.sqlite" % version)
                older(path, version)
                with open(path, "rb") as f:
                    name = self.uploaded(f.read())
                self.assertTrue(name.endswith("-upload.sqlite"))
        # A server's own database file, copied while it was stopped: in write-ahead log mode (its header says so).
        path = os.path.join(self.made, "openDMT3.sqlite")
        db.connect(path).close()
        with open(path, "rb") as f:
            content = f.read()
        self.assertEqual(content[18:20], b"\x02\x02")
        self.uploaded(content)
        # Reading the files left no journal beside them.
        self.assertEqual(self.leftovers(), [])

    def test_what_is_no_backup_is_refused_in_words_and_leaves_nothing(self):
        backup = database_file(self.made)
        self.refused(b"", "error.backup.not_sqlite")
        self.refused(b"a text file, not a database" * 10, "error.backup.not_sqlite")
        # SQLite's header, then nothing a database has.
        self.refused(backups.SQLITE_HEADER + os.urandom(8192), "error.backup.damaged")
        # A real backup cut short, and one with a page written over.
        self.refused(backup[:len(backup) // 2], "error.backup.damaged")
        broken = bytearray(backup)
        broken[4096 + 8:4096 + 64] = os.urandom(56)
        self.refused(bytes(broken), "error.backup.damaged")
        # Another program's database (version 0), one whose version says ours but whose tables are not, a column
        # missing, and our tables with a trigger or a view this project never makes.
        self.refused(self.file_of(lambda c: c.execute("CREATE TABLE notes (text)")), "error.backup.not_ours")

        def renamed_table(c):
            older_tables(c)
            c.execute("ALTER TABLE plays RENAME TO games")
        self.refused(self.file_of(renamed_table), "error.backup.not_ours")

        def missing_column(c):
            older_tables(c, skip="ALTER TABLE accounts ADD COLUMN comment")
        self.refused(self.file_of(missing_column), "error.backup.not_ours")

        def with_trigger(c):
            older_tables(c)
            c.execute("CREATE TRIGGER t AFTER INSERT ON plays BEGIN DELETE FROM accounts; END")
        self.refused(self.file_of(with_trigger), "error.backup.not_ours")

        def with_view(c):
            older_tables(c)
            c.execute("CREATE VIEW v AS SELECT * FROM accounts")
        self.refused(self.file_of(with_view), "error.backup.not_ours")
        # A database from a newer openDMT3: its version named, and the most this server opens.

        def newer(c):
            older_tables(c)
            c.execute("PRAGMA user_version=%d" % (db.VERSION + 1))
        error = self.refused(self.file_of(newer), "error.backup.too_new")
        self.assertEqual(error.params, {"version": db.VERSION + 1, "most": db.VERSION})

    def test_an_uploads_file_left_by_a_stopped_server_goes_after_a_day(self):
        where = backups.folder(self.data)
        os.makedirs(where)
        # One left a day and more ago, one of an upload coming in now (an hour old).
        old, new = (os.path.join(where, backups.UPLOAD_PREFIX + n + backups.UPLOAD_SUFFIX) for n in ("old", "new"))
        for path, age in ((old, backups.UPLOAD_STALE + 60), (new, 3600)):
            with open(path, "wb") as f:
                f.write(b"x")
            moment = os.path.getmtime(path) - age
            os.utime(path, (moment, moment))
        out, part = backups.upload_part(self.data)
        out.close()
        self.assertEqual((os.path.exists(old), os.path.exists(new), os.path.exists(part)), (False, True, True))
        # The list never shows an upload's file.
        self.assertEqual(backups.all_backups(self.data), [])


def older_tables(connection, skip=None):
    """This version's tables, as the steps make them (one statement left out when `skip` starts it), and the version."""
    for step in db.STEPS:
        for statement in step:
            if not (skip and statement.startswith(skip)):
                connection.execute(statement)
    connection.execute("PRAGMA user_version=%d" % db.VERSION)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class UploadRoutesTest(ApiBase):
    """The Backups tab's upload and its API twin."""

    def setUp(self):
        super().setUp()
        # A backup made by another server, in a folder of its own.
        self.other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.other)
        self.content = database_file(self.other)

    def page_post(self, fields, files=None, **kwargs):
        """The Backups tab's upload form, as a browser sends it (the token first, then the file)."""
        return self.client.post("/admin/backups/upload", data=fields, files=files, **kwargs)

    def kept(self):
        """The kinds of the backups the list shows, and the upload files left in backups/ (none, ever)."""
        where = backups.folder(self.tmp)
        left = [n for n in os.listdir(where) if n.startswith(backups.UPLOAD_PREFIX)] if os.path.isdir(where) else []
        return [b["kind"] for b in backups.all_backups(self.tmp)], left

    def test_the_admin_uploads_a_backup_on_the_page_and_restores_it(self):
        self.admin()
        page = self.client.get("/admin/backups").text
        form = page.split('action="/admin/backups/upload"', 1)[1].split("</form>", 1)[0]
        # A multipart form whose token comes before its file, with the limit for the page's own check.
        self.assertIn('enctype="multipart/form-data"', form)
        self.assertLess(form.index('name="csrf"'), form.index('type="file"'))
        self.assertIn('data-upload-most="%d"' % backups.UPLOAD_MOST, form)
        token = self.form_token(self.client, "/admin/backups")
        r = self.page_post({"csrf": token},
                           {"file": ("from-elsewhere.sqlite", self.content, "application/vnd.sqlite3")})
        name = backups.all_backups(self.tmp)[0]["name"]
        self.assertEqual(r.status_code, 200)
        self.assertIn("Uploaded and checked: %s" % name, r.text)
        self.assertEqual(self.kept(), (["upload"], []))
        self.assertIn(">Uploaded</span>", r.text)
        self.assertEqual(self.changes()[0], "uploaded a backup as %s (%d bytes)" % (name, len(self.content)))
        # The page shown names its own address: the language switch comes back to the Backups tab, and its forms
        # post there.
        self.assertIn('href="/lang/ko?next=/admin/backups"', r.text)
        self.assertEqual(r.text.count('<form method="post" action="/admin/backups"'), 3)
        # Restored as any other: the other server's account is here, and BOSS (made since) is gone.
        self.client.post("/admin/backups", data={"csrf": token, "action": "restore", "name": name})
        store = self.site.accounts()
        try:
            self.assertEqual([row["login_id"] for row in store.all()], ["RIO"])
        finally:
            store.db.close()

    def test_the_pages_upload_refuses_in_words_and_keeps_nothing(self):
        self.admin()
        token = self.form_token(self.client, "/admin/backups")
        # Not a database; a form without its file.
        r = self.page_post({"csrf": token}, {"file": ("notes.txt", b"not a database", "text/plain")})
        self.assertIn("The file is not an SQLite database.", r.text)
        r = self.page_post({"csrf": token}, {"file": ("", b"", "application/octet-stream")})
        self.assertIn("No database file came with the upload.", r.text)
        # Another site's form (no token, or another before the file): not read at all.
        r = self.page_post({}, {"file": ("a.sqlite", self.content, "application/octet-stream")})
        self.assertIn("The form expired; try again.", r.text)
        r = self.page_post({"csrf": "made-up"}, {"file": ("a.sqlite", self.content, "application/octet-stream")})
        self.assertIn("The form expired; try again.", r.text)
        # A body that is no form at all.
        r = self.client.post("/admin/backups/upload", content=self.content,
                             headers={"Content-Type": "application/octet-stream"})
        self.assertIn("No database file came with the upload.", r.text)
        self.assertEqual(self.kept(), ([], []))
        # In Korean: the refusal, then an upload kept, with its kind's name.
        self.client.cookies.set("opendmt3_lang", "ko")
        r = self.page_post({"csrf": token}, {"file": ("notes.txt", b"not a database", "text/plain")})
        self.assertIn("SQLite 데이터베이스 파일이 아닙니다.", r.text)
        r = self.page_post({"csrf": token}, {"file": ("a.sqlite", self.content, "application/octet-stream")})
        self.assertIn("올리고 검사했습니다", r.text)
        self.assertIn(">올린 백업</span>", r.text)
        self.assertEqual(self.kept(), (["upload"], []))

    def test_an_upload_past_its_limit_stops_there(self):
        self.admin()
        token = self.form_token(self.client, "/admin/backups")
        player_token = self.token("BOSS")
        # A body that says beforehand it is too long: refused before it is read, with the limit in words.
        declared = {"Content-Length": str(backups.UPLOAD_MOST + 1)}
        r = self.call("POST", "/api/v1/backups/upload", player_token, content=b"", headers=declared)
        self.refused(r, 413, "too_large")
        self.assertEqual(r.json()["error"]["message"], "an uploaded backup is at most 256 MB")
        # A smaller limit for this test: a body in pieces without a length is counted as it comes, and stops there.
        with mock.patch.object(backups, "UPLOAD_MOST", 4096):
            pieces = (self.content[i:i + 1000] for i in range(0, len(self.content), 1000))
            self.refused(self.call("POST", "/api/v1/backups/upload", player_token, content=pieces), 413, "too_large")
            r = self.page_post({"csrf": token}, {"file": ("a.sqlite", self.content, "application/octet-stream")})
            self.assertEqual(r.status_code, 413)
            self.assertIn("An uploaded backup is at most", r.text)
        self.assertEqual(self.kept(), ([], []))

    def test_the_api_takes_the_file_as_its_body_for_admins_only(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        boss, player = self.token("BOSS"), self.token("NOVA")
        self.refused(self.call("POST", "/api/v1/backups/upload", content=self.content), 401, "sign_in")
        self.refused(self.call("POST", "/api/v1/backups/upload", player, content=self.content), 403, "admin_only")
        self.assertEqual(self.kept(), ([], []))
        r = self.call("POST", "/api/v1/backups/upload", boss, content=self.content,
                      headers={"Content-Type": "application/vnd.sqlite3"})
        self.assertEqual(r.status_code, 201, r.text)
        name = r.json()["uploaded"]
        self.assertEqual(self.kept(), (["upload"], []))
        # What is no backup: 400 with the reason in words; an empty body says no file came.
        self.refused(self.call("POST", "/api/v1/backups/upload", boss, content=b"text"), 400, "refused")
        r = self.call("POST", "/api/v1/backups/upload", boss, content=b"")
        self.refused(r, 400, "refused")
        self.assertEqual(r.json()["error"]["message"], "no database file came with the upload")
        # "upload" is no backup's name for the other methods of a backup's address.
        self.refused(self.call("GET", "/api/v1/backups/upload", boss), 404, "unknown_backup")
        # It is in the list, downloads byte for byte, and restores (the other server's accounts come with it).
        listed = self.call("GET", "/api/v1/backups", boss).json()["backups"]
        self.assertEqual([(b["name"], b["kind"]) for b in listed], [(name, "upload")])
        self.assertEqual(self.call("GET", "/api/v1/backups/" + name, boss).content, self.content)
        self.assertEqual(self.call("POST", "/api/v1/backups/%s/restore" % name, boss).status_code, 200)
        # The other server's player signs in here now (token() checks the sign-in's answer).
        self.token("RIO")

    def test_only_these_routes_take_more_than_the_sites_body_limit(self):
        from opendmt3.server.web import app as web_app
        self.admin()
        big = backups.SQLITE_HEADER + bytes(web_app.BODY_LIMIT * 2)
        token = self.token("BOSS")
        # Past 64 KiB: the upload reads it (and refuses what it is not), any other route refuses its length.
        self.refused(self.call("POST", "/api/v1/backups/upload", token, content=big), 400, "refused")
        self.assertEqual(self.call("POST", "/api/v1/backups", token, content=big).status_code, 413)
        self.assertEqual(self.client.post("/admin/backups", content=big).status_code, 413)
        # Somebody signed out gets the sign-in page, a player the page that is not there: neither body is read.
        self.client.cookies.clear()
        r = self.page_post({"csrf": "x"}, {"file": ("a.sqlite", self.content, "application/octet-stream")},
                           follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin?next=/admin/backups/upload"))
        self.make()
        self.sign_in(self.client)
        r = self.page_post({"csrf": self.form_token(self.client, "/")},
                           {"file": ("a.sqlite", self.content, "application/octet-stream")})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.kept(), ([], []))


if __name__ == "__main__":
    unittest.main()
