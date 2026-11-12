"""Tests for the words of errors (errors.py).

Every error the package raises with a key must say in English exactly what its own sentence says (so English
readers see one text in the window, the console and the log), every key needs Korean words with the same gaps,
and the launcher and the site show an error in the reader's language.
"""

import ast
import os
import re
import string
import tempfile
import unittest

from opendmt3.core import errors
from opendmt3.core import game as g
from opendmt3.client import i18n, remote
from opendmt3.server.services import accounts
from opendmt3.server.web import strings

PACKAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "opendmt3")
# The exceptions built on errors.Worded.
WORDED = ("GameError", "AccountError", "HostingError", "RemoteError", "BackupError", "CardError", "UpdateError", "RepairError",
          "NoticeError", "TokenError", "SourceError", "SongListError")


def _english(call):
    """The call's sentence as str.format text, with each %-gap named after the keyword that carries its value."""
    message = call.args[0]
    if isinstance(message, ast.Constant):
        text, operands = message.value, []
    else:
        # "... %s ..." % value, or % (a, b): each operand must also be passed as a keyword, which names the gap.
        text = message.left.value
        right = message.right
        operands = [ast.unparse(e) for e in right.elts] if isinstance(right, ast.Tuple) else [ast.unparse(right)]
    names = {ast.unparse(k.value): k.arg for k in call.keywords if k.arg != "key"}
    gaps = iter(operands)
    # Braces are literal in the sentence; a str.format text writes them twice.
    text = text.replace("{", "{{").replace("}", "}}")

    def gap(match):
        if match.group(1) == "%":
            return "%"
        name = names[next(gaps)]
        return "{%s!r}" % name if match.group(1) == "r" else "{%s}" % name

    return re.sub(r"%([sdr%])", gap, text)


def raise_sites():
    """(where, key, English as str.format text) for every keyed Worded error the package makes, and the count of
    those whose sentence comes from elsewhere (the server's own, for an API code)."""
    sites, passed_on = [], 0
    for folder, _, names in os.walk(PACKAGE):
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if called not in WORDED or not call.args:
                    continue
                where = "%s:%d" % (os.path.relpath(path, PACKAGE), call.lineno)
                if not isinstance(call.args[0], (ast.Constant, ast.BinOp)):
                    # A sentence made elsewhere: remote.py passes on the server's, with its error code.
                    passed_on += 1
                    continue
                keyword = [k.value for k in call.keywords if k.arg == "key"]
                key = keyword[0] if keyword else (call.args[1] if len(call.args) > 1 else None)
                sites.append((where, key.value if isinstance(key, ast.Constant) else None, _english(call)))
    return sites, passed_on


def gaps(text):
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


class WordsOfErrorsTest(unittest.TestCase):

    def test_every_raise_site_has_a_key_and_says_its_sentence_in_english(self):
        sites, passed_on = raise_sites()
        # The instrument itself: it found the sites (24 keyed, the server's one passed on, when this was written).
        self.assertGreaterEqual(len(sites), 24)
        self.assertEqual(passed_on, 1)
        for where, key, english in sites:
            self.assertIsNotNone(key, "%s raises without a key" % where)
            self.assertIn(key, errors.TEXT, where)
            self.assertEqual(errors.TEXT[key][0], english, where)

    def test_every_word_is_used_and_has_korean_with_the_same_gaps(self):
        used = {key for _, key, _ in raise_sites()[0]}
        for key, (english, korean) in errors.TEXT.items():
            if not key.startswith("error.api."):
                self.assertIn(key, used, "%s is in TEXT but nothing raises it" % key)
            self.assertTrue(re.search("[가-힣]", korean), key)
            self.assertEqual(gaps(english), gaps(korean), key)

    def test_the_launcher_shows_an_account_error_in_the_players_language(self):
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.check_id("A B")
        error = caught.exception
        # The sentence itself, starting with a capital and ending with a full stop in a window.
        self.assertEqual(i18n.Words("en").error(error), "An ID is 1 to 8 letters or digits (what the game's keypad can type).")
        self.assertEqual(i18n.Words("ko").error(error), "ID는 영문자와 숫자로 1~8자입니다(게임 키패드로 입력할 수 있는 글자).")

    def test_a_game_folder_error_keeps_its_values(self):
        empty = tempfile.mkdtemp()
        try:
            with self.assertRaises(g.GameError) as caught:
                g.Game.find(empty)
        finally:
            os.rmdir(empty)
        said = i18n.Words("ko").error(caught.exception)
        self.assertTrue(said.startswith(empty + " 아래에 게임 폴더"), said)
        # The folder ends the English sentence: no full stop that would read as part of the path.
        self.assertEqual(i18n.Words("en").error(caught.exception), "N" + str(caught.exception)[1:])

    def test_an_address_error_quotes_what_was_typed(self):
        with self.assertRaises(remote.RemoteError) as caught:
            remote.normalize("host:99999")
        self.assertEqual(i18n.Words("ko").error(caught.exception), "주소로 읽을 수 없습니다: 'host:99999'")

    def test_a_sentence_starts_with_a_capital_but_not_an_address_or_the_name(self):
        self.assertEqual(errors.sentence("cannot reach it"), "Cannot reach it")
        self.assertEqual(errors.sentence("http://192.0.2.1:4730 is not an openDMT3 server"),
                         "http://192.0.2.1:4730 is not an openDMT3 server")
        self.assertEqual(errors.sentence("openDMT3's card reader is not part of this build"),
                         "openDMT3's card reader is not part of this build")
        self.assertEqual(errors.sentence("서버 주소를 입력해 주세요."), "서버 주소를 입력해 주세요.")

    def test_a_sentence_ends_with_a_full_stop_unless_a_value_ends_it(self):
        self.assertEqual(errors.closed("Sign in on the Online page first", {}), "Sign in on the Online page first.")
        # A bracket closes a remark, not the sentence.
        self.assertEqual(errors.closed("Cannot reach http://192.0.2.1:4730 (timed out)",
                                       {"base": "http://192.0.2.1:4730", "reason": "timed out"}),
                         "Cannot reach http://192.0.2.1:4730 (timed out).")
        # Its own end stays.
        self.assertEqual(errors.closed("서버 주소를 입력해 주세요.", {}), "서버 주소를 입력해 주세요.")
        # A value at the end stays bare, as it is and as it is quoted.
        self.assertEqual(errors.closed("No backup named before.db", {"name": "before.db"}), "No backup named before.db")
        self.assertEqual(errors.closed("Server address must be host:port, not 'x'", {"value": "x"}),
                         "Server address must be host:port, not 'x'")
        # A value that only appears earlier does not count.
        self.assertEqual(errors.closed("Port 4730 on this PC is taken (in use); close the other server",
                                       {"port": 4730, "error": "in use"}),
                         "Port 4730 on this PC is taken (in use); close the other server.")

    def test_a_server_code_has_the_launchers_words_and_an_unknown_one_its_sentence(self):
        wrong = remote.RemoteError("that ID and password do not match an account", "wrong_sign_in")
        self.assertEqual(i18n.Words("ko").error(wrong), "ID 또는 비밀번호가 맞지 않습니다.")
        newer = remote.RemoteError("a newer server's sentence", "brand_new_code")
        self.assertEqual(i18n.Words("ko").error(newer), "A newer server's sentence")
        # Anything else (an OSError, a library's own) reads as it is, with a capital.
        self.assertEqual(i18n.Words("ko").error(OSError("disk full")), "Disk full")

    def test_the_site_has_the_same_words(self):
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.check_password("ab")
        self.assertEqual(strings.words("ko").error(caught.exception), "비밀번호는 영문자와 숫자로 %d~%d자입니다."
                         % (accounts.PASSWORD_MIN, accounts.PASSWORD_MAX))
        self.assertEqual(strings.words("en").error(caught.exception), "A" + str(caught.exception)[1:] + ".")


if __name__ == "__main__":
    unittest.main()
