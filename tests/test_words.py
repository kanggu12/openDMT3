"""The words people read keep to the project's terms (the design of what openDMT3 takes from the game, its term table):
the launcher's and the site's words, the errors' words, the site's pages, the server's lines for a path, the setup
wizard, the command lines' help, the README and the guides in docs/ never say the words that misled before or name the
game's files. The thing a server takes is "the song list" (it holds the jackets and the DJ cards too); the game's own
files are "the game's files"; no "game data", "server files", "assets", "archive" for the game's own files, "disc
pictures", a "song list file" or a game file's name. The one sentence allowed to say "game data" is the notice that
openDMT3's software contains none.

Code spans and code blocks in the guides are not prose (a path such as client/assets/ is a path), nor are comments and
docstrings in the code (they are for people changing it). "layer" is the in-game layer in the guides for contributors;
in what a player or an owner reads it is never a word for the game's files.

The concept is a rule of the design, never words on a screen: who a server is for ("friends") and where it stands ("at
home") are its owner's own business, so no sentence a person reads says either (a server has players; a PC has other
PCs on its network).

The files of prose are listed once (PROSE): a new guide or template joins the check by its place there.
"""

import ast
import glob
import os
import re
import unittest

from opendmt3.client import i18n
from opendmt3.core import errors
from opendmt3.server.services import sources
from opendmt3.server.web import strings

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The words never said, as patterns (any letter case), with what each is instead.
BANNED = [
    (r"\bgame data\b", "the song list, or the game's files"),
    (r"게임 데이터", "곡 목록, 또는 게임 파일"),
    (r"\bserver files?\b", "name the thing by what it is"),
    (r"서버 파일", "이름은 그것이 무엇인지로"),
    (r"\bassets?\b", "name the thing by what it is"),
    (r"에셋", "이름은 그것이 무엇인지로"),
    (r"아카이브", "게임 파일, 또는 압축 파일"),
    (r"\bpatch archives?\b", "the game's files"),
    (r"\bdisc pictures?\b", "jackets"),
    (r"디스크 그림", "자켓"),
    (r"맞춘 폴더", "전에 openDMT3가 바꾼 파일"),
    (r"\bset up by openDMT3\b", "openDMT3 changed files here before"),
    (r"\bsong list files?\b", "the song list"),
    (r"곡 목록 파일", "곡 목록"),
    # The game's own file names: never in a sentence a person reads.
    (r"\b(?:config|discinfo|discimg|script|icon|emblem)(?:\d\d)?\.pak\b", "the file with the song list, ..."),
    (r"\bdiscstock\.csv\b", "the song list"),
]
# The concept words: never in a sentence a person reads, in either language.
CONCEPT = [
    (r"\bfriends?\b", "players, or the other PCs"),
    (r"\bat home\b", "on this network"),
    (r"지인|친구", "플레이어, 또는 다른 PC"),
    # Hangul has no word breaks: "집" inside another word ("편집에서") is not the house.
    (r"(?<![가-힣])집 안|같은 집|(?<![가-힣])집에서", "같은 네트워크"),
]
# The files of prose people read, as patterns from the repository's top: the README, the guides, how to contribute,
# and what GitHub shows a visitor (the security policy, the code of conduct, the pull request's and the issues'
# templates). Add a file's pattern here when it comes.
PROSE = ("README.md", "CONTRIBUTING.md", "docs/*.md", ".github/*.md", ".github/ISSUE_TEMPLATE/*.yml")
# Only in what a player or an owner reads (never the game's files' layers there).
LAYER = (r"\blayers?\b", "the in-game layer is the one layer, and only in the guides for contributors")
# The guides for contributors, where the in-game layer is described in full (and the game's messages, beside it).
CONTRIBUTORS = ("architecture.md", "testing.md", "test-cases.md", "protocol.md")
# The one sentence that may say "game data": the notice that the software holds none (both languages).
ALLOWED = ("openDMT3's software contains no game data", "openDMT3 소프트웨어에는 게임 데이터가 들어 있지 않습니다")


def found(text, patterns):
    """The banned words a text says, as (the word said, what to say instead). The in-game layer is the one layer a
    person may read about anywhere."""
    for allowed in ALLOWED:
        text = text.replace(allowed, "")
    text = re.sub(r"in-game\s+layers?", "", text, flags=re.I)
    out = []
    for pattern, instead in patterns:
        out += [(m.group(0), instead) for m in re.finditer(pattern, text, re.I)]
    return out


def code_strings(path):
    """Every string a Python file holds that a person may read (help, printed lines, words), without its docstrings."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def prose(text):
    """A guide's text without its code: fenced blocks and inline code spans."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "", text)


class WordsTest(unittest.TestCase):

    def check(self, where, texts, patterns):
        """Each text of a place checked; returns how many were looked at (the instrument's own count)."""
        said = []
        for text in texts:
            said += ["%s: %r (say: %s)" % (where, word, instead) for word, instead in found(text, patterns)]
        self.assertEqual(said, [], "\n".join(said))
        return len(texts)

    def test_the_words_of_the_launcher_the_site_the_errors_and_the_servers_lines(self):
        everything = BANNED + CONCEPT + [LAYER]
        looked = 0
        for where, table in (("launcher", i18n.TEXT), ("site", strings.TEXT), ("errors", errors.TEXT),
                             ("server's lines", sources.WORDS)):
            looked += self.check(where, [text for pair in table.values() for text in pair], everything)
        # Hundreds of words: a table that stopped being read would pass with none.
        self.assertGreater(looked, 900)

    def test_the_words_outside_the_tables(self):
        # The note a removal leaves in a game folder (both languages: client/leaving.py), and the console program's
        # lines when openDMT3.exe is missing (packaging/windows/console_modules.py: no table can be read then).
        from opendmt3.client import leaving
        notes = [text for words in leaving.WORDS.values() for text in words]
        self.assertGreater(len(notes), 8)
        self.check("the removal's note", notes, BANNED + CONCEPT + [LAYER])
        lines = code_strings(os.path.join(ROOT, "packaging", "windows", "console_modules.py"))
        # The check reads the lines it is for.
        self.assertTrue(any("choose Repair" in text for text in lines), lines)
        self.check("console_modules.py", lines, BANNED + CONCEPT + [LAYER])

    def test_the_sites_pages(self):
        pages = sorted(glob.glob(os.path.join(ROOT, "opendmt3", "server", "web", "templates", "*.html")))
        self.assertGreater(len(pages), 20)
        for path in pages:
            with open(path, encoding="utf-8") as f:
                # Template comments are for people changing the page.
                text = re.sub(r"\{#.*?#\}", "", f.read(), flags=re.S)
            self.check(os.path.basename(path), [text], BANNED + CONCEPT + [LAYER])

    def test_the_wizard_and_the_command_lines(self):
        for name in ("packaging/docker/wizard.py", "dmt3", "opendmt3/server/__main__.py", "opendmt3/client/cli.py"):
            texts = code_strings(os.path.join(ROOT, name))
            self.assertGreater(len(texts), 10, name)
            self.check(name, texts, BANNED + CONCEPT + [LAYER])

    def prose_files(self):
        """The files of prose (PROSE), each as (its path from the top, its text without code)."""
        paths = sorted(path for pattern in PROSE for path in glob.glob(os.path.join(ROOT, *pattern.split("/"))))
        # The README, the guides, how to contribute and GitHub's own files: a list that stopped finding them would
        # pass with nothing read.
        self.assertGreater(len(paths), 14)
        out = []
        for path in paths:
            with open(path, encoding="utf-8") as f:
                out.append((os.path.relpath(path, ROOT).replace(os.sep, "/"), prose(f.read())))
        return out

    def test_the_readme_and_the_guides(self):
        # (With how to contribute and what GitHub shows a visitor: PROSE. The name stays: the guides point at it.)
        for name, text in self.prose_files():
            # The guides for contributors describe the in-game layer in full.
            self.check(name, [text], BANNED + ([] if os.path.basename(name) in CONTRIBUTORS else [LAYER]))

    def test_no_guide_says_who_a_server_is_for_or_where_it_stands(self):
        # Apart from the terms' test above, so a guide that still says the concept shows as that one thing; every
        # file's words are said at once (a fix is made file by file).
        said = []
        for name, text in self.prose_files():
            for number, line in enumerate(text.splitlines(), start=1):
                said += ["%s: %r in %r (say: %s)" % (name, word, " ".join(line.split())[:90], instead)
                         for word, instead in found(line, CONCEPT)]
        self.assertEqual(said, [], "\n".join(said))

    def test_the_changelog(self):
        # Every release's notes, and the changes not released yet: each section is a release's notes on GitHub.
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        # Players read them: the layer in the game is said in their words, as on the launcher's pages.
        self.check("CHANGELOG.md", [prose(text)], BANNED + CONCEPT + [LAYER])

    def test_every_word_asked_for_by_name_is_in_its_table(self):
        # A key that is not in the table is shown as the key itself ("status.fix_first" on a window): every key the
        # launcher's code, the screens' test and the site's pages and code write out is looked up here. A key put
        # together from parts ("check." + name) is held to its first part: some word must begin with it.
        asked = re.compile(r"""\b(?:w|words)\(\s*(["'])([A-Za-z0-9_.: -]+)\1\s*([+%,)])""")
        places = (("the launcher", i18n.TEXT, ["opendmt3/client/*.py", "opendmt3/client/pages/*.py",
                                               "tests/e2e/ui/shots.py"]),
                  ("the site", strings.TEXT, ["opendmt3/server/web/*.py", "opendmt3/server/web/templates/*.html"]))
        missing, looked = [], 0
        for where, table, patterns in places:
            # The errors' words are asked for through the same tables' look-up of an error, never by name here.
            for pattern in patterns:
                for path in sorted(glob.glob(os.path.join(ROOT, *pattern.split("/")))):
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                    for _, key, after in asked.findall(text):
                        looked += 1
                        whole = after not in "+%"
                        if (key not in table) if whole else not any(k.startswith(key) for k in table):
                            missing.append("%s: %s asks for %r%s" % (where, os.path.relpath(path, ROOT), key,
                                                                    "" if whole else "..."))
        self.assertEqual(missing, [], "\n".join(missing))
        # Several hundred look-ups: a pattern that stopped finding them would pass with none.
        self.assertGreater(looked, 600)

    def test_the_instrument_finds_what_it_is_for(self):
        # Each banned word is found where it is said, and the allowed notice is not.
        self.assertEqual([w for w, _ in found("the Game data card, DiscInfo.pak and the 곡 목록 파일", BANNED)],
                         ["Game data", "곡 목록 파일", "DiscInfo.pak"])
        self.assertEqual(found(ALLOWED[0] + "; please use it only with game files", BANNED), [])
        # The concept words are found in both languages, and not inside other words.
        self.assertEqual([w for w, _ in found("A server for friends, for a Friend at home; 지인들과 집 안의 PC", CONCEPT)],
                         ["friends", "Friend", "at home", "지인", "집 안"])
        self.assertEqual(found("friendship, a cat home, 편집에서 고릅니다", CONCEPT), [])
        self.assertEqual(prose("a `client/assets/fonts` path\n```\nassets\n```\n"), "a  path\n\n")


if __name__ == "__main__":
    unittest.main()
