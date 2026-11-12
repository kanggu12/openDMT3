"""./dmt3 setup's wizard (packaging/docker/wizard.py): its pages as functions of the answers (what comes next, what
each answer means, what keeps a page), the setup's lines as it runs, and the plain numbered prompts for a terminal
that cannot draw. Nothing here runs Docker or draws a screen: the environment is made up (FakeEnv)."""

import importlib.util
import os
import re
import tempfile
import unittest
from unittest import mock

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    """The wizard's module, from its path (it sits beside the Docker files, outside the package)."""
    spec = importlib.util.spec_from_file_location("dmt3_wizard_test", os.path.join(ROOT, "packaging", "docker",
                                                                                   "wizard.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wizard = load()
# What a path is, as the front door's look() gives it (the words are tested in tests/server/test_sources.py): a game
# folder with every part there, one whose DJ cards are not, nothing of the game, an archive holding the game (one with a
# password among them), and a song list the launcher saved.
WHOLE = {"kind": "folder", "ready": True, "path": "/games/made-up", "key": "source.folder",
         "line": "Game folder, original PC client, 3 songs: ready",
         "parts": [(True, "song list: 3 songs"), (True, "jackets: 2 of 3 songs"),
                   (True, "DJ cards: 4 icons, 5 plates, 6 patterns")]}
NO_CARDS = dict(WHOLE, path="/games/no-cards", parts=WHOLE["parts"][:2] + [
    (False, "DJ cards: not yet, every DJ card keeps the basic icon and plate. The game's files have no DJ cards.")])
NOTHING = {"kind": "folder", "ready": False, "path": "/games/nothing", "key": "error.source.nothing",
           "line": "This is neither a game folder nor an archive holding one.", "parts": []}
ARCHIVE = {"kind": "archive", "ready": True, "path": "/games/technika.7z", "key": "source.archive",
           "line": "A game folder in an archive: ready (the server takes out only what it needs)", "parts": []}
LOCKED = dict(ARCHIVE, path="/games/locked.7z", ready=False, key="error.source.password",
              line="This archive has a password. Enter it.")
SONG_LIST = {"kind": "song list", "ready": True, "path": "/files/openDMT3-song-list.zip", "key": "source.song_list",
             "line": "Song list saved by openDMT3, 3 songs: ready", "parts": [(True, "song list: 3 songs")]}


def lines(found):
    """A look's lines, as the front door gives them: its one line, then its parts."""
    return [(found["ready"], found["line"])] + list(found["parts"])


class FakeEnv:
    """What the pages look at and do, made up: Docker's checks, addresses, accounts, game folders, the installer, and
    the setup's commands, each with the output a test gives it."""

    def __init__(self, checks=None, accounts=0, built=None, outputs=None, check=None, readable=True):
        self.checks = checks or [("docker", True, "docker is installed", None), ("port", True, "port 4725 is free",
                                                                                 None)]
        self.accounts_found, self.built, self.readable = accounts, built, readable
        self.surveys = {"/games/made-up": WHOLE, "/games/no-cards": NO_CARDS, "/games/technika.7z": ARCHIVE,
                        "/games/locked.7z": LOCKED, ("/games/locked.7z", "made-up"): dict(ARCHIVE, path="/games/locked.7z"),
                        "/files/openDMT3-song-list.zip": SONG_LIST}
        # The output and exit code of each step by its key; the check's lines.
        self.outputs = outputs or {}
        self.checked = check if check is not None else [(True, "the site answers")]
        self.kept, self.ran = [], []
        # The address kept for the server, and how many times Docker was looked at.
        self.address, self.looks = None, 0

    def docker_checks(self):
        self.looks += 1
        # A list of lists: one set of checks a look, the last for every look after it (a problem fixed between two).
        if self.checks and isinstance(self.checks[0], list):
            return self.checks[min(self.looks, len(self.checks)) - 1]
        return self.checks

    def addresses(self):
        return [("192.168.0.20", "eth0"), ("127.0.0.1", "this PC only")]

    def accounts(self):
        return self.accounts_found

    def survey(self, path, password=None):
        return self.surveys.get((path, password)) or self.surveys.get(path, NOTHING)

    def lines(self, found):
        return lines(found)

    def mounts(self, path):
        return [path, "/elsewhere/pack"], [], self.readable

    def found_games(self):
        return [WHOLE, NO_CARDS]

    def default_installer(self):
        return self.built

    def installer_info(self, path):
        return {"size": 3 * 1048576, "version": "0.13.0"} if path in ("/build/setup.exe", "/files/setup.exe") \
            else None

    def build_command(self):
        return ["build"]

    def plan(self, a):
        steps = [("image", "", ["build"]), ("data", "", ["data"])]
        if a.accounts == 0:
            steps.append(("account", "", ["account"]))
        if a.game_path():
            steps.append(("catalog", "", ["catalog"]))
        if a.installer != wizard.NONE:
            steps.append(("installer", "", ["installer"]))
        return steps + [("server", "", ["server"])]

    def keep_game(self, folder):
        self.kept.append(folder)

    def keep_address(self, address):
        self.address = address

    def stream(self, cmd, on_line):
        self.ran.append(cmd[0])
        code, text = self.outputs.get(cmd[0], (0, ""))
        for line in text.splitlines():
            on_line(line)
        return code, text.splitlines()

    def check(self):
        return self.checked


def page(cls):
    """The wizard's page of this class."""
    return next(p for p in wizard.pages() if isinstance(p, cls))


def looked(pg, a, env, times=4):
    """A page's look-ups run, as the screen runs them when the typing stops."""
    for _ in range(times):
        look = pg.pending(a, env)
        if not look:
            return
        look()


class PagesTest(unittest.TestCase):
    def test_the_pages_in_order_one_question_each(self):
        names = [p.name for p in wizard.pages()]
        self.assertEqual(names, ["Welcome", "Docker", "Address", "Admin", "Password", "Game", "Installer", "Confirm",
                                 "Setup", "Done"])
        a, env = wizard.Answers(), FakeEnv()
        for p in wizard.pages():
            looked(p, a, env) if not isinstance(p, wizard.Progress) else None
            # No page asks more than one thing (the password typed twice is one answer).
            self.assertLessEqual(len({f.attr for f in p.fields(a, env)} - {"again", "installer_file"}), 1, p.name)

    def test_next_and_back_skip_the_password_when_the_database_has_accounts(self):
        ordered = wizard.pages()
        a = wizard.Answers()
        at_admin = [p.name for p in ordered].index("Admin")
        self.assertEqual(ordered[wizard.step(at_admin, ordered, a)].name, "Password")
        a.accounts = 2
        self.assertEqual(ordered[wizard.step(at_admin, ordered, a)].name, "Game")
        self.assertEqual(ordered[wizard.step(at_admin + 2, ordered, a, forward=False)].name, "Admin")
        # Never past either end.
        self.assertEqual(wizard.step(0, ordered, a, forward=False), 0)
        self.assertEqual(wizard.step(len(ordered) - 1, ordered, a), len(ordered) - 1)

    def test_docker_problems_keep_the_page_with_their_fix_but_an_image_not_built_does_not(self):
        p, a = page(wizard.Docker), wizard.Answers()
        env = FakeEnv(checks=[("docker", True, "docker is installed", None),
                              ("image", False, "the server image is not built", "./dmt3 up"),
                              ("port", False, "port 4730 is taken by another program", "stop that program")])
        self.assertEqual(p.leave(a, env), "Docker is still being looked at.")
        looked(p, a, env)
        body = p.body(a, env)
        self.assertIn(("port 4730 is taken by another program", "bad"), body)
        self.assertIn(("      fix: stop that program", "dim"), body)
        # No key is named in the page's words: the plain prompts have no r and no Esc.
        self.assertEqual(p.preview(a, env), [("The server cannot start until these are fixed.", "bad")])
        self.assertEqual(p.leave(a, env), "The server cannot start until the problems above are fixed.")
        # r looks again; with the port free only the image is left, which the setup builds.
        self.assertTrue(p.key(a, env, "r"))
        self.assertIsNone(a.docker)
        env.checks = env.checks[:2]
        looked(p, a, env)
        self.assertIsNone(p.leave(a, env))
        self.assertEqual(p.preview(a, env)[0][1], "ok")

    def test_the_address_preview_is_the_site_and_the_game_at_it(self):
        p, a, env = page(wizard.Address), wizard.Answers(), FakeEnv()
        looked(p, a, env)
        self.assertEqual(a.address, "192.168.0.20")
        self.assertEqual(p.preview(a, env), [("The site: http://192.168.0.20:4730/", "ok"),
                                             ("The game: 192.168.0.20:4725", "ok")])
        a.address = "127.0.0.1"
        self.assertIn("Only this PC", p.preview(a, env)[-1][0])

    def test_the_admins_id_is_checked_by_the_accounts_rules(self):
        p, a, env = page(wizard.AdminId), wizard.Answers(), FakeEnv()
        looked(p, a, env)
        self.assertIsNone(p.leave(a, env))
        self.assertEqual(p.preview(a, env)[-1], ("Signs in as BOSS (IDs are kept in capitals).", "dim"))
        a.admin = "owner"
        self.assertIn("OWNER", p.preview(a, env)[-1][0])
        for wrong, why in (("", "1 to 8 characters"), ("TOOLONGID", "1 to 8 characters"),
                           ("BO SS", "only letters and digits")):
            a.admin = wrong
            self.assertEqual(p.leave(a, env), why, wrong)
            self.assertIn((why, "bad"), p.preview(a, env))

    def test_a_database_with_accounts_asks_for_no_id(self):
        p, a, env = page(wizard.AdminId), wizard.Answers(), FakeEnv(accounts=3)
        looked(p, a, env)
        self.assertEqual(p.fields(a, env), [])
        self.assertIsNone(p.leave(a, env))
        self.assertEqual(p.body(a, env)[0][0], "Accounts in the server's database already: 3.")

    def test_the_password_is_made_or_typed_twice_by_the_rules(self):
        p, a, env = page(wizard.Password), wizard.Answers(), FakeEnv()
        self.assertEqual(p.preview(a, env), [("A password is made for you and shown once at the end.", "ok")])
        self.assertIsNone(p.leave(a, env))
        self.assertTrue(all(f.secret for f in p.fields(a, env)))
        a.password, a.again = "abc", "abc"
        self.assertEqual(p.leave(a, env), "6 to 16 characters")
        a.password, a.again = "pass1234", "pass1235"
        self.assertEqual(p.leave(a, env), "typed the same twice")
        a.password, a.again = "pass-123", "pass-123"
        self.assertEqual(p.leave(a, env), "only letters and digits")
        a.password, a.again = "pass1234", "pass1234"
        self.assertIsNone(p.leave(a, env))
        self.assertEqual({tone for _, tone in p.preview(a, env)}, {"ok"})

    def test_the_game_folder_is_looked_at_as_typed_with_its_parts_and_links(self):
        p, a, env = page(wizard.Game), wizard.Answers(), FakeEnv(readable=False)
        # Empty: none now, said with how to import it later.
        self.assertIsNone(p.leave(a, env))
        self.assertIn("./dmt3 catalog", p.preview(a, env)[0][0])
        looked(p, a, env)
        self.assertEqual([item["path"] for item in a.found], ["/games/made-up", "/games/no-cards"])
        # What was found, each with its one line, as the site's Song list tab shows it.
        self.assertIn(("      Game folder, original PC client, 3 songs: ready", "ok"), p.body(a, env))
        # Down and Up put one found in the box.
        self.assertTrue(p.key(a, env, "down"))
        self.assertEqual(a.game, "/games/made-up")
        self.assertTrue(p.key(a, env, "down"))
        self.assertEqual(a.game, "/games/no-cards")
        self.assertEqual(p.leave(a, env), "It is still being looked at.")
        looked(p, a, env)
        preview = p.preview(a, env)
        self.assertEqual(preview[0], ("Game folder, original PC client, 3 songs: ready", "ok"))
        self.assertIn(("song list: 3 songs", "ok"), preview)
        # A missing optional part is a line of its own, and does not keep the page.
        self.assertIn(("DJ cards: not yet, every DJ card keeps the basic icon and plate. The game's files have no DJ "
                       "cards.", "bad"), preview)
        self.assertIn(("links inside it are followed (more folders mounted read-only: 1)", "ok"), preview)
        self.assertIn("not offered", preview[-1][0])
        self.assertIsNone(p.leave(a, env))
        # A folder with no game in it keeps the page with its one line.
        a.game = "/games/nothing"
        looked(p, a, env)
        self.assertEqual(p.leave(a, env), "This is neither a game folder nor an archive holding one.")
        self.assertEqual(p.preview(a, env), [(NOTHING["line"], "bad")])

    def test_an_archive_or_a_song_list_is_taken_too_and_a_password_asked_only_when_there_is_one(self):
        p, a, env = page(wizard.Game), wizard.Answers(), FakeEnv()
        a.found = []
        a.game = "/games/technika.7z"
        looked(p, a, env)
        self.assertEqual(p.preview(a, env)[0], (ARCHIVE["line"], "ok"))
        self.assertIn("only the files the server needs are taken out", p.preview(a, env)[1][0])
        # An archive is read once: never kept mounted.
        self.assertIsNone(a.kept())
        self.assertEqual([f.attr for f in p.fields(a, env)], ["game"])
        self.assertIsNone(p.leave(a, env))
        # One with a password: the page asks for it, and keeps the answer until the right one is typed.
        a.game = "/games/locked.7z"
        looked(p, a, env)
        self.assertEqual(p.leave(a, env), "This archive has a password. Enter it.")
        self.assertEqual([f.attr for f in p.fields(a, env)], ["game", "archive_password"])
        self.assertTrue(p.fields(a, env)[1].secret)
        a.archive_password = "made-up"
        looked(p, a, env)
        self.assertIsNone(p.leave(a, env))
        # A song list the launcher saved.
        a.game, a.archive_password = "/files/openDMT3-song-list.zip", ""
        looked(p, a, env)
        self.assertEqual(p.preview(a, env)[:2], [(SONG_LIST["line"], "ok"), ("song list: 3 songs", "ok")])
        self.assertIsNone(p.leave(a, env))

    def test_the_installer_is_the_builds_a_file_or_none(self):
        p, a = page(wizard.Installer), wizard.Answers()
        env = FakeEnv(built="/build/setup.exe")
        p.body(a, env)
        self.assertEqual(a.installer, wizard.BUILD)
        self.assertEqual(p.preview(a, env), [("version 0.13.0, 3.0 MB", "ok")])
        self.assertIsNone(p.leave(a, env))
        # A file: its box shows, and a file that is not there keeps the page.
        a.installer = wizard.FILE
        self.assertEqual([f.attr for f in p.fields(a, env) if f.shown(a)], ["installer", "installer_file"])
        a.installer_file = "/files/nothing.exe"
        self.assertEqual(p.preview(a, env), [("no such file: /files/nothing.exe", "bad")])
        self.assertIsNotNone(p.leave(a, env))
        a.installer_file = "/files/setup.exe"
        self.assertIsNone(p.leave(a, env))
        a.installer = wizard.NONE
        self.assertEqual([f.attr for f in p.fields(a, env) if f.shown(a)], ["installer"])
        self.assertIsNone(p.leave(a, env))
        # Without a build, none is the first choice.
        b = wizard.Answers()
        p.body(b, FakeEnv())
        self.assertEqual(b.installer, wizard.NONE)
        self.assertEqual([v for v, _ in p.options(b, FakeEnv())], [wizard.FILE, wizard.NONE])

    def test_the_confirm_page_shows_every_answer_numbered_to_go_back_to(self):
        a, env = wizard.Answers(), FakeEnv()
        a.address, a.admin, a.game, a.installer, a.accounts = "192.168.0.20", "boss", "/games/no-cards", "none", 0
        looked(page(wizard.Game), a, env)
        body = [text for text, _ in page(wizard.Confirm).body(a, env)]
        self.assertIn("2  Address           http://192.168.0.20:4730/", body)
        self.assertIn("3  Admin             BOSS, password made for you", body)
        # Where the song list comes from (the look's path), its line and its parts under it.
        self.assertIn("4  Song list from    /games/no-cards", body)
        self.assertTrue(any("DJ cards: not yet" in line for line in body))
        self.assertIn("5  Installer         none for now", body)
        self.assertEqual(sorted(wizard.CHANGE), ["1", "2", "3", "4", "5"])

    def test_paths_typed_or_pasted_become_this_pcs(self):
        self.assertEqual(wizard.clean_path('  "/games/made up"  '), "/games/made up")
        self.assertEqual(wizard.clean_path("~/x"), os.path.expanduser("~/x"))
        with mock.patch.object(wizard.os.path, "isdir", lambda p: p == "/mnt/d"):
            self.assertEqual(wizard.clean_path("D:\\Games\\TECHNIKA 3"), "/mnt/d/Games/TECHNIKA 3")
        # A drive that is not mounted stays as typed.
        with mock.patch.object(wizard.os.path, "isdir", lambda p: False):
            self.assertEqual(wizard.clean_path("Q:\\x"), "Q:\\x")

    def test_tab_completes_a_path_as_far_as_the_matches_agree(self):
        with tempfile.TemporaryDirectory() as top:
            for name in ("Desktop", "Documents", "Downloads.txt", ".hidden"):
                path = os.path.join(top, name)
                os.mkdir(path) if not name.endswith(".txt") else open(path, "w").close()
            self.assertEqual(wizard.complete(os.path.join(top, "Des")), (os.path.join(top, "Desktop") + os.sep,
                                                                         ["Desktop"]))
            self.assertEqual(wizard.complete(os.path.join(top, "D")),
                             (os.path.join(top, "D"), ["Desktop", "Documents", "Downloads.txt"]))
            self.assertEqual(wizard.complete(os.path.join(top, "Do")),
                             (os.path.join(top, "Do"), ["Documents", "Downloads.txt"]))
            # Letter case does not matter when nothing matches as typed; hidden names only after a dot.
            self.assertEqual(wizard.complete(os.path.join(top, "desk"))[0], os.path.join(top, "Desktop") + os.sep)
            self.assertEqual(wizard.complete(os.path.join(top, ".h"))[1], [".hidden"])
            self.assertEqual(wizard.complete(os.path.join(top, "nothing")), (os.path.join(top, "nothing"), []))


class SetupRunTest(unittest.TestCase):
    def answers(self, **kw):
        a = wizard.Answers()
        a.address, a.installer = "192.168.0.20", wizard.NONE
        for name, value in kw.items():
            setattr(a, name, value)
        return a

    def test_each_step_has_its_line_the_catalogs_three_parts_and_the_password_made(self):
        env = FakeEnv(outputs={"account": (0, "made BOSS, DJ name BOSS, admin pages, password 1a2b3c4d\n"),
                               "catalog": (0, "song list: 3 songs\njackets: 2 of 3 songs\nDJ cards: not yet, every DJ "
                                              "card keeps the basic icon and plate. The game's files have no DJ "
                                              "cards.\n")})
        a = self.answers(game="/games/no-cards")
        looked(page(wizard.Game), a, env)
        drawn = []
        self.assertTrue(wizard.run_setup(a, env, lambda: drawn.append(dict(a.progress))))
        self.assertEqual(env.ran, ["build", "data", "account", "catalog", "server"])
        self.assertEqual(a.made_password, "1a2b3c4d")
        self.assertEqual(a.progress["songs"], ("ok", "song list: 3 songs"))
        self.assertEqual(a.progress["jackets"], ("ok", "jackets: 2 of 3 songs"))
        self.assertEqual(a.progress["cards"][0], "bad")
        self.assertEqual(a.progress["installer"], ("skip", "none for now"))
        self.assertEqual(a.progress["check"][0], "ok")
        self.assertTrue(a.done)
        # Shown as it went: the image's line while it ran.
        self.assertIn(("run", ""), [d.get("image") for d in drawn])
        # The game folder kept mounted for the site's Read again, before the server started.
        self.assertEqual(env.kept, ["/games/no-cards"])
        body = [text for text, _ in page(wizard.Progress).body(a, env)]
        self.assertEqual(len(body), len(wizard.STEPS))
        done = [text for text, _ in page(wizard.Done).body(a, env)]
        self.assertIn("  password  1a2b3c4d", done)
        self.assertIn("  from other PCs:  http://192.168.0.20:4730/", done)
        # The address chosen is kept for the server before it starts, and is the one to open: the accounts first
        # (each gives its message), then the messages, which carry the Download page.
        self.assertEqual(env.address, "192.168.0.20")
        self.assertLess(env.ran.index("build"), env.ran.index("server"))
        self.assertEqual(done[done.index("Next:") + 1:], [
            "  1. Open http://192.168.0.20:4730/ and sign in.",
            "  2. Make the players' accounts on Admin, Players: each gives a message to send.",
            "  3. Send each player their message: it has the Download page and the steps."])

    def test_an_address_of_this_pc_alone_is_said_as_one_no_other_pc_reaches(self):
        env = FakeEnv()
        a = self.answers(address="127.0.0.1")
        wizard.run_setup(a, env, lambda: None)
        done = [text for text, _ in page(wizard.Done).body(a, env)]
        self.assertIn("      from other PCs:  not reachable at this address (./dmt3 setup again to choose another)", done)
        # Nobody else to make an account for or to send a message to: the one step is to sign in.
        self.assertEqual(done[done.index("Next:") + 1:], ["  1. Open http://127.0.0.1:4730/ and sign in."])
        self.assertNotIn("Download page", "\n".join(done))

    def test_no_page_says_friends_or_names_a_key_the_plain_prompts_do_not_have(self):
        env = FakeEnv(checks=[("docker", False, "docker is not installed", "install Docker")], accounts=2,
                      built="/build/setup.exe")
        a = self.answers(game="/games/made-up")
        a.failed = "Server image"
        said = []
        for p in wizard.pages():
            for _ in range(4):
                look = p.pending(a, env)
                # The setup itself is not run here: its page is read as it stands after a step failed.
                if not look or isinstance(p, wizard.Progress):
                    break
                look()
            said += [text for text, _ in p.body(a, env) + p.preview(a, env)]
        text = "\n".join(said)
        self.assertGreater(len(said), 40)
        self.assertNotIn("friend", text.lower())
        # The keys are said where they work: the drawn pages' bottom line, the plain prompts' own prompt.
        self.assertIsNone(re.search(r"\bEsc\b|press r\b|\(s\)", text), text)

    def test_a_folder_the_server_cannot_read_is_not_kept_mounted(self):
        env = FakeEnv(readable=False)
        a = self.answers(game="/games/made-up")
        looked(page(wizard.Game), a, env)
        wizard.run_setup(a, env, lambda: None)
        self.assertEqual(env.kept, [])

    def test_a_step_that_fails_stops_the_setup_with_its_last_line(self):
        env = FakeEnv(outputs={"data": (1, "Error response from daemon: made up\n")})
        a = self.answers()
        self.assertFalse(wizard.run_setup(a, env, lambda: None))
        self.assertEqual(a.failed, "Data folder")
        self.assertEqual(a.progress["data"], ("bad", "Error response from daemon: made up"))
        self.assertNotIn("server", env.ran)
        progress = page(wizard.Progress)
        self.assertTrue(progress.can_back(a))
        self.assertIn("stopped at Data folder", progress.preview(a, env)[0][0])
        # Enter tries again from the start.
        self.assertEqual(progress.leave(a, env), "Trying again.")
        self.assertEqual(a.progress, {})

    def test_a_check_that_fails_is_said(self):
        env = FakeEnv(check=[(False, "http://127.0.0.1:4730/health does not answer")], accounts=1)
        a = self.answers()
        self.assertFalse(wizard.run_setup(a, env, lambda: None))
        self.assertEqual(a.failed, "Check")
        # No account made: its line says why.
        self.assertEqual(a.progress["account"], ("skip", "the database has accounts"))


class PlainPromptsTest(unittest.TestCase):
    def run_plain(self, replies, env=None, secrets=("", "")):
        """The plain prompts with these replies; (exit code, every line printed, the answers)."""
        replies, secrets, printed = list(replies), list(secrets), []

        def ask(prompt):
            printed.append(prompt)
            if not replies:
                raise EOFError
            return replies.pop(0)

        def secret(prompt):
            printed.append(prompt)
            return secrets.pop(0)
        a = wizard.Answers()
        code = wizard.run_plain(env or FakeEnv(), ask=ask, secret=secret, out=printed.append, a=a)
        return code, printed, a

    def test_a_whole_setup_answered_with_numbers_and_lines(self):
        # Welcome, Docker, the second address, the ID, (two passwords), the game folder, none, start, done.
        env = FakeEnv(outputs={"catalog": (0, "song list: 3 songs\njackets: 2 of 3 songs\n"
                                              "DJ cards: 4 icons, 5 plates, 6 patterns\n")})
        code, printed, a = self.run_plain(["", "", "1", "nova", "/games/made-up", "2", "", ""], env=env,
                                          secrets=("pass1234", "pass1234"))
        self.assertEqual(code, 0)
        self.assertEqual((a.address, a.admin, a.password, a.game, a.installer),
                         ("192.168.0.20", "nova", "pass1234", "/games/made-up", wizard.NONE))
        text = "\n".join(printed)
        for title in ("Set up an openDMT3 server", "Docker and ports", "This server's address", "The song list",
                      "Ready to set up", "Setting up", "Your server is running"):
            self.assertIn(title, text)
        # Each step's line, once done, and the preview of each answer.
        self.assertIn("ok  Song list           song list: 3 songs", text)
        self.assertIn("ok  DJ cards            DJ cards: 4 icons, 5 plates, 6 patterns", text)
        # The setup's title comes before its lines.
        self.assertLess(text.index("Setting up"), text.index("ok  Server image"))
        self.assertIn("ok  The site: http://192.168.0.20:4730/", text)
        self.assertIn("  ID        NOVA", text)

    def test_b_goes_back_and_a_wrong_answer_is_asked_again(self):
        code, printed, a = self.run_plain(["", "b", "", "", "1", "BO SS", "BOSS"])
        self.assertEqual(code, 1)
        text = "\n".join(printed)
        # Back from Docker to Welcome: the welcome page twice.
        self.assertEqual(text.count("Set up an openDMT3 server"), 2)
        self.assertIn("!!  only letters and digits", text)
        self.assertEqual(a.admin, "BOSS")

    def test_enter_on_the_docker_page_checks_again_until_the_problem_is_fixed(self):
        broken = [("docker", True, "docker is installed", None),
                  ("port", False, "port 4730 is taken by another program", "stop that program")]
        fixed = [("docker", True, "docker is installed", None), ("port", True, "port 4730 is free", None)]
        # Looked at when the page opens, again at the first Enter (still taken), again at the second (free now):
        # the third Enter goes on to the address.
        env = FakeEnv(checks=[broken, broken, fixed])
        code, printed, a = self.run_plain(["", "", "", ""], env=env)
        text = "\n".join(printed)
        self.assertEqual(env.looks, 3)
        # The page's own prompt says what Enter does there, and no key the plain prompts lack is named.
        self.assertEqual(text.count("[Enter checks again, b goes back] "), 2)
        self.assertNotIn("press r", text)
        self.assertNotIn("Esc", text)
        # Each look printed once, the failing line once a look (it was printed twice, the page for ever).
        self.assertEqual(text.count("no  port 4730 is taken by another program"), 2)
        self.assertEqual(text.count("no  The server cannot start until these are fixed."), 2)
        self.assertIn("ok  port 4730 is free", text)
        self.assertIn("This server's address", text)
        # b on the failing page goes back instead of looking again.
        env = FakeEnv(checks=[broken])
        code, printed, a = self.run_plain(["", "b"], env=env)
        self.assertEqual(("\n".join(printed).count("Set up an openDMT3 server"), env.looks), (2, 1))

    def test_the_end_of_input_stops_without_a_traceback(self):
        code, printed, _ = self.run_plain([])
        self.assertEqual((code, printed[-1]), (1, "Setup stopped."))

    def test_the_plain_prompts_are_used_where_curses_cannot_draw(self):
        with mock.patch.dict(os.environ, {"TERM": "dumb"}):
            self.assertFalse(wizard.can_draw())
        with mock.patch.dict(os.environ, {"TERM": "xterm"}), \
                mock.patch.object(wizard.importlib.util, "find_spec", return_value=None):
            self.assertFalse(wizard.can_draw())
        with mock.patch.dict(os.environ, {"TERM": "dumb"}), \
                mock.patch.object(wizard, "run_plain", return_value=0) as plain:
            self.assertEqual(wizard.run(FakeEnv()), 0)
        plain.assert_called_once()


class ScreenKeysTest(unittest.TestCase):
    """The curses screen's keys on a page, without a terminal: a made-up window that keeps what is drawn."""

    def screen(self, env=None):
        window = mock.Mock()
        window.getmaxyx.return_value = (34, 100)
        fake = mock.Mock(A_BOLD=1, A_DIM=2, A_NORMAL=0, A_REVERSE=4, A_UNDERLINE=8, KEY_UP=259, KEY_DOWN=258,
                         KEY_BTAB=353, KEY_BACKSPACE=263, KEY_ENTER=343, KEY_RESIZE=410, error=Exception)
        with mock.patch.dict("sys.modules", {"curses": fake}):
            s = wizard.Screen(window, env or FakeEnv(), wizard.Answers())
        return s, window

    def test_typing_backspace_tab_and_enter_on_a_text_box(self):
        s, _ = self.screen()
        s.at = [p.name for p in s.ordered].index("Admin")
        s.a.accounts = 0
        for k in ("backspace", "backspace", "backspace", "backspace", "N", "O", "V", "A"):
            s.act(k)
        self.assertEqual(s.a.admin, "NOVA")
        s.act("clear")
        self.assertEqual(s.a.admin, "")
        # Enter with an empty ID stays, with the reason.
        s.act("enter")
        self.assertEqual((s.page.name, s.error), ("Admin", "1 to 8 characters"))
        s.a.admin = "NOVA"
        s.act("enter")
        self.assertEqual(s.page.name, "Password")
        # Up and Down move between the two boxes; Esc goes back.
        s.act("down")
        self.assertEqual(s.focus, 1)
        s.act("esc")
        self.assertEqual(s.page.name, "Admin")

    def test_a_choice_moves_with_up_and_down_and_the_confirm_numbers_go_back(self):
        s, _ = self.screen()
        s.a.addresses = FakeEnv().addresses()
        s.a.address = "192.168.0.20"
        s.at = [p.name for p in s.ordered].index("Address")
        s.act("down")
        self.assertEqual(s.a.address, "127.0.0.1")
        s.act("down")
        self.assertEqual(s.a.address, "192.168.0.20")
        s.at = [p.name for p in s.ordered].index("Confirm")
        s.act("4")
        self.assertEqual(s.page.name, "Game")

    def test_enter_says_what_it_does_on_the_page_it_is_pressed_on(self):
        broken = [("docker", True, "docker is installed", None),
                  ("port", False, "port 4730 is taken by another program", "stop that program")]
        s, window = self.screen(FakeEnv(checks=[broken]))

        def bottom():
            """The keys' line as drawn: the last row of the made-up window."""
            window.addnstr.reset_mock()
            s.draw()
            return [call.args[2] for call in window.addnstr.call_args_list if call.args[0] == 33][-1]

        # The Docker page while something stops the setup: Enter checks again (as r does), and says so.
        s.at = [p.name for p in s.ordered].index("Docker")
        s.a.docker = broken
        self.assertEqual(bottom(), "r  checks again   Esc  back   Enter  check again   Ctrl-C  quit")
        s.act("enter")
        self.assertEqual((s.page.name, s.a.docker, s.error), ("Docker", None, ""))
        # Once it passes, Enter goes on.
        s.a.docker = [("docker", True, "docker is installed", None)]
        self.assertEqual(bottom(), "r  checks again   Esc  back   Enter  next   Ctrl-C  quit")
        s.act("enter")
        self.assertEqual(s.page.name, "Address")
        # The setup stopped at a step: Enter tries again; the last page: Enter closes.
        s.at = [p.name for p in s.ordered].index("Setup")
        s.a.progress, s.a.failed = {"image": ("bad", "no network")}, "Server image"
        self.assertEqual(bottom(), "Esc  back   Enter  try again   Ctrl-C  quit")
        s.at = [p.name for p in s.ordered].index("Done")
        s.a.failed, s.a.done = None, True
        self.assertEqual(bottom(), "Enter  close")

    def test_the_progress_and_done_pages_have_no_back(self):
        s, _ = self.screen()
        s.at = [p.name for p in s.ordered].index("Setup")
        s.a.progress = {"image": ("run", "")}
        s.act("esc")
        self.assertEqual(s.page.name, "Setup")
        s.act("enter")
        self.assertEqual(s.error, "The setup is still running.")
        s.at = [p.name for p in s.ordered].index("Done")
        self.assertEqual(s.act("enter"), "quit")


if __name__ == "__main__":
    unittest.main()
