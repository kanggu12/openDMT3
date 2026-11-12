"""Tests for the API's named tokens (OpenDMTQ's API tokens): made on the Account page or through the API with a name and
a scope, shown once, kept as a hash only, listed with when each was made and last used, revoked. A token acts as its
owner: a read-only one makes GET calls only and none of an admin's (403 read_only); a write one has its owner's rights.
Changes made with one are logged as "LOGIN (token NAME)". The sign-in tokens work as before.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import hashlib
import html
import os
import re
import unittest

# The API's calls with a token, the site's forms, and the plays put in as the game server puts them (tests/server/test_api.py).
from tests.server.test_api import ApiBase
from tests.server.test_reset import asking_forms
from tests.server.test_web import WEB


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class NamedTokensTest(ApiBase):

    def named(self, name="bot", scope="write", token=None):
        """A named token made through the API with a sign-in token of NOVA's (or `token`): the token itself."""
        r = self.call("POST", "/api/v1/tokens", token or self.token(), json={"name": name, "scope": scope})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["token"]

    def rows(self):
        """The api_tokens table as the database holds it."""
        from opendmt3.server import db
        connection = db.connect(self.site.db_path)
        try:
            return [dict(r) for r in connection.execute("SELECT * FROM api_tokens ORDER BY created_at, id")]
        finally:
            connection.close()

    def test_a_player_makes_a_token_on_the_account_page_sees_it_once_and_revokes_it(self):
        self.make()
        self.sign_in(self.client)
        token = self.form_token(self.client, "/account")
        page = self.client.post("/account", data={"csrf": token, "action": "token_make", "name": "chat bot",
                                                  "scope": "read"}).text
        shown = re.search(r'<textarea id="made-token" class="message token" readonly rows="2">(.*?)</textarea>', page)
        self.assertIsNotNone(shown, "the token is not shown")
        made = shown.group(1)
        self.assertRegex(made, r"^odt3_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$")
        self.assertIn("The token chat bot, shown this once:", page)
        # It works with the API at once, as its owner.
        self.assertEqual(self.call("GET", "/api/v1/me", made).json()["login_id"], "NOVA")
        # Shown once: the page again lists it by its name, scope, when made and last used, never the token.
        page = self.client.get("/account").text
        self.assertNotIn(made, page)
        listed = page.split('<table class="table tokens">', 1)[1].split("</table>", 1)[0]
        self.assertIn('<td class="token-name">chat bot</td>', listed)
        self.assertIn(">Read only</span>", listed)
        # When made and when last used, each cell with its column's name for a phone's stacked rows.
        self.assertEqual(listed.count('<td class="muted" data-label="Made">'), 1)
        self.assertEqual(listed.count('<td class="muted" data-label="Last used">'), 1)
        self.assertNotIn(">never<", listed)
        # Revoked after the site's own question: the form asks first, in the site's dialog.
        revoke = [f for f in asking_forms(page) if f["data-ask-yes"] == "Revoke"]
        self.assertEqual([f["data-ask"] for f in revoke], ["Revoke the token chat bot?"])
        self.assertTrue(revoke[0]["data-ask-title"] and revoke[0]["data-ask-detail"])
        token_id = re.search(r'value="token_revoke"><input type="hidden" name="id" value="([0-9a-f]{12})"',
                             page).group(1)
        # Another site's form (no token): nothing changes.
        self.client.post("/account", data={"action": "token_revoke", "id": token_id})
        self.assertEqual(self.call("GET", "/api/v1/me", made).status_code, 200)
        page = self.client.post("/account", data={"csrf": token, "action": "token_revoke", "id": token_id}).text
        self.assertIn("The token chat bot is revoked.", page)
        self.assertIn("No token yet.", page)
        self.refused(self.call("GET", "/api/v1/me", made), 401, "sign_in")
        self.assertEqual(self.changes()[:2], ["revoked the API token chat bot of NOVA",
                                              "made the API token chat bot (read) for NOVA"])
        # In Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/account").text
        self.assertIn("API 토큰", page)
        self.assertIn("아직 토큰이 없습니다.", page)

    def test_only_a_hash_is_kept_and_the_token_is_written_nowhere(self):
        self.make()
        made = self.named("nightly backup")
        rows = self.rows()
        self.assertEqual([(r["name"], r["scope"], r["hash"]) for r in rows],
                         [("nightly backup", "write", hashlib.sha256(made.encode()).hexdigest())])
        # Neither the token nor its secret is in the database's files or in the change log.
        # odt3_<id>_<secret>: the secret is token_urlsafe, which may hold "_" itself, so it is all after the second one.
        secret = made.split("_", 2)[2].encode()
        for name in os.listdir(self.tmp):
            if name.startswith("openDMT3.sqlite"):
                with open(os.path.join(self.tmp, name), "rb") as f:
                    self.assertNotIn(secret, f.read(), name)
        self.assertFalse(any(secret.decode() in line for line in self.changes()))
        # The list never gives the token or its hash.
        listed = self.call("GET", "/api/v1/tokens", made).json()["tokens"]
        self.assertEqual(sorted(listed[0]), ["created_at", "id", "name", "scope", "used_at"])

    def test_a_read_only_token_reads_and_changes_nothing(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        self.play(self.make("RIO", dj="RIO"), 1, 1, 500)
        player_read = self.named("dashboard", "read")
        admin_read = self.named("status page", "read", token=self.token("BOSS"))
        for read in (player_read, admin_read):
            with self.subTest(owner="player" if read is player_read else "admin"):
                # What a player may read, it reads.
                for path in ("/api/v1/me", "/api/v1/plays?everyone=1", "/api/v1/rankings", "/api/v1/songs",
                             "/api/v1/tokens", "/api/v1/notice", "/api/v1/cabinets"):
                    self.assertEqual(self.call("GET", path, read).status_code, 200, path)
                self.assertEqual(self.call("HEAD", "/api/v1/me", read).status_code, 200)
                # Every change is refused, its own revoke and a sign-out included.
                for method, path, body in (("POST", "/api/v1/me/dj_name", {"dj_name": "X"}),
                                           ("POST", "/api/v1/tokens", {"name": "more", "scope": "write"}),
                                           ("DELETE", "/api/v1/session", None),
                                           ("POST", "/api/v1/notice", {"text": "x"}),
                                           ("DELETE", "/api/v1/plays", None)):
                    self.refused(self.call(method, path, read, json=body), 403, "read_only")
        # An admin's read-only token makes none of an admin's calls, nor sees an admin's part of a call.
        for path in ("/api/v1/players", "/api/v1/server", "/api/v1/backups", "/api/v1/log", "/api/v1/cabinets?all=1"):
            self.refused(self.call("GET", path, admin_read), 403, "read_only")
        self.call("POST", "/api/v1/notice", self.token("BOSS"), json={"text": "Hello"})
        self.assertNotIn("by", self.call("GET", "/api/v1/notice", admin_read).json()["notice"])
        # A player's read-only token gets the player's answer to an admin's call.
        self.refused(self.call("GET", "/api/v1/players", player_read), 403, "admin_only")
        # The refusal's words.
        r = self.call("POST", "/api/v1/me/dj_name", player_read, json={"dj_name": "X"})
        self.assertEqual(r.json()["error"]["message"], "a read-only token makes GET calls only, and none of an admin's")
        # Nothing changed.
        self.assertEqual(self.call("GET", "/api/v1/me", player_read).json()["dj_name"], "DJ NOVA")

    def test_a_write_token_has_its_owners_rights_and_its_changes_are_logged_by_its_name(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        player, admin = self.named("my bot"), self.named("nightly backup", token=self.token("BOSS"))
        # A player's write token changes the player's own things, and none of an admin's.
        self.assertEqual(self.call("POST", "/api/v1/me/dj_name", player, json={"dj_name": "NOVA X"}).status_code, 200)
        self.assertEqual(self.changes()[0], "named NOVA NOVA X")
        self.refused(self.call("GET", "/api/v1/players", player), 403, "admin_only")
        # An admin's write token makes an admin's calls, logged as "LOGIN (token NAME)".
        self.assertEqual(self.call("POST", "/api/v1/backups", admin).status_code, 201)
        from opendmt3.server import db
        connection = db.connect(self.site.db_path)
        try:
            who = [r[0] for r in connection.execute("SELECT who FROM changes ORDER BY id DESC LIMIT 2")]
        finally:
            connection.close()
        self.assertEqual(who, ["BOSS (token nightly backup)", "NOVA (token my bot)"])
        # The admin's part of a call comes with a write token (the cabinets' addresses; who set the notice).
        self.call("POST", "/api/v1/notice", admin, json={"text": "Hello"})
        self.assertEqual(self.call("GET", "/api/v1/notice", admin).json()["notice"]["by"],
                         "BOSS (token nightly backup)")
        self.assertEqual(self.call("GET", "/api/v1/cabinets?all=1", admin).status_code, 200)
        # A sign-in token's changes are logged by the ID alone, as before.
        self.call("POST", "/api/v1/me/dj_name", self.token(), json={"dj_name": "DJ NOVA"})
        self.assertEqual(self.changes()[0], "named NOVA DJ NOVA")
        # The list says when each was last used.
        listed = {t["name"]: t for t in self.call("GET", "/api/v1/tokens", admin).json()["tokens"]}
        self.assertIsNotNone(listed["nightly backup"]["used_at"])

    def test_what_ends_a_token_and_what_only_stops_it(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        boss = self.token("BOSS")
        made = self.named()
        # Disabled: it stops, and works again once enabled.
        self.call("POST", "/api/v1/players/NOVA/disable", boss)
        self.refused(self.call("GET", "/api/v1/me", made), 401, "sign_in")
        self.call("POST", "/api/v1/players/NOVA/enable", boss)
        self.assertEqual(self.call("GET", "/api/v1/me", made).status_code, 200)
        # Revoked through the API (by its id) or by signing out with it: ended for good.
        token_id = made.split("_")[1]
        self.assertEqual(self.call("DELETE", "/api/v1/tokens/" + token_id, made).json(),
                         {"revoked": token_id, "name": "bot"})
        self.refused(self.call("GET", "/api/v1/me", made), 401, "sign_in")
        other = self.named("other")
        self.assertEqual(self.call("DELETE", "/api/v1/session", other).json(), {"signed_out": True})
        self.refused(self.call("GET", "/api/v1/me", other), 401, "sign_in")
        # A new password ends every one of the account's tokens, the admin's for the player and the player's own.
        first, second = self.named("first"), self.named("second")
        self.call("POST", "/api/v1/players/NOVA/password", boss)
        for token in (first, second):
            self.refused(self.call("GET", "/api/v1/me", token), 401, "sign_in")
        self.assertEqual(self.rows(), [])
        # A deleted account's tokens go with it.
        self.make("RIO", dj="RIO")
        rio = self.named("rio's", token=self.token("RIO"))
        self.call("DELETE", "/api/v1/players/RIO", boss)
        self.assertEqual(self.rows(), [])
        self.refused(self.call("GET", "/api/v1/me", rio), 401, "sign_in")

    def test_refusals_are_in_words_and_tokens_that_are_not_ours_sign_in_nobody(self):
        from opendmt3.server.services import tokens
        self.make()
        self.make("RIO", dj="RIO")
        signed = self.token()
        for body in ({"name": "", "scope": "read"}, {"name": "x" * 41, "scope": "read"},
                     {"name": "a\x07b", "scope": "read"}, {"name": "bot", "scope": "admin"}, {"name": "bot"}):
            with self.subTest(body=body):
                self.refused(self.call("POST", "/api/v1/tokens", signed, json=body), 400, "refused")
        self.refused(self.call("POST", "/api/v1/tokens", signed, content=b"not json"), 400, "bad_request")
        # Forty characters are fine; MOST tokens at most (made with one sign-in: sign-ins have a limit a minute).
        for n in range(tokens.MOST):
            self.named("%02d" % n + "x" * 38, token=signed)
        r = self.call("POST", "/api/v1/tokens", signed, json={"name": "one more", "scope": "read"})
        self.refused(r, 400, "refused")
        self.assertEqual(r.json()["error"]["message"],
                         "an account holds at most %d tokens: revoke one first" % tokens.MOST)
        # Another account's token, or one revoked already: not one of the caller's.
        rio = self.named("rio's", token=self.token("RIO"))
        self.refused(self.call("DELETE", "/api/v1/tokens/" + rio.split("_")[1], signed), 404, "unknown_token")
        self.refused(self.call("DELETE", "/api/v1/tokens/000000000000", signed), 404, "unknown_token")
        self.assertEqual(self.call("GET", "/api/v1/me", rio).status_code, 200)
        # A token of the right shape that the database does not hold, or with a wrong secret, signs in nobody.
        wrong = rio[:-1] + ("A" if rio[-1] != "A" else "B")
        for token in (wrong, "odt3_000000000000_" + "A" * 43, "odt3_", "odt3_x"):
            self.refused(self.call("GET", "/api/v1/me", token), 401, "sign_in")
        # Who may: nobody without a token.
        for method, path in (("GET", "/api/v1/tokens"), ("POST", "/api/v1/tokens"), ("DELETE", "/api/v1/tokens/x")):
            self.refused(self.call(method, path), 401, "sign_in")
        # The Account page says the same in Korean.
        self.sign_in(self.client)
        self.client.cookies.set("opendmt3_lang", "ko")
        token = self.form_token(self.client, "/account")
        page = self.client.post("/account", data={"csrf": token, "action": "token_make", "name": "",
                                                  "scope": "read"}).text
        self.assertIn("토큰 이름은 1~40자입니다.", html.unescape(page))
        page = self.client.post("/account", data={"csrf": token, "action": "token_revoke", "id": "nope"}).text
        self.assertIn("이 계정에 그런 토큰이 없습니다: nope", page)

    def test_sign_in_tokens_and_the_launchers_sign_out_work_as_before(self):
        self.make()
        signed, made = self.token(), self.named()
        # A sign-in token signs out as before (its own id kept), and a named token of the account goes on.
        self.assertEqual(self.call("DELETE", "/api/v1/session", signed).json(), {"signed_out": True})
        self.refused(self.call("GET", "/api/v1/me", signed), 401, "sign_in")
        self.assertEqual(self.call("GET", "/api/v1/me", made).status_code, 200)
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
