"""Tests for the final web review's findings (0.4.0) that the server's own answers show: the play-hours map's every step
drawn, a moment that never breaks from its date, the files a user saves named in lowercase with the tool, the kind and
the date, a made account no longer in the form that made it, counts that say what they count, one size and two decimals
for the machine's figures, the MAX points of a change line with separators, the doors' and the players' marks, and
the song list page without its guidance.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import os
import re
import time
import unittest

from tests.server.test_admin_site import AdminSiteBase
from tests.server.test_site_features import SiteBase
from tests.server.test_web import WEB

# The site's stylesheet, where every step of the maps has its colour.
CSS = os.path.join(os.path.dirname(__file__), "..", "..", "opendmt3", "server", "web", "static", "site.css")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class StepsTest(SiteBase):
    """Every step the maps of counts can draw has its colour in the stylesheet."""

    def steps(self, selector):
        """The steps the stylesheet colours for a map's cells (`.heat i.h3` -> 3); step 0 is the cell's own colour."""
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        return {0} | {int(n) for n in re.findall(re.escape(selector) + r"\.h(\d+)\b", css)}

    def drawn(self, html):
        return {int(n) for n in re.findall(r'class="h(\d+)"', html)}

    def test_the_play_hours_map_and_the_players_days_draw_only_steps_with_a_colour(self):
        from opendmt3.server.web import strings
        charts = self.site.templates.get_template("_charts.html").module
        w = strings.words("en")
        for most in (1, 2, 3, 4, 5, 7, 9, 10, 13, 100):
            # Every count from none to the most, the most itself included (the busiest hour of the month).
            counts = list(range(most + 1))
            grid = [(counts * 24)[:24] for _ in range(7)]
            heat = str(charts.heat({"grid": grid, "most": most, "days": 30}, w))
            self.assertLessEqual(self.drawn(heat), self.steps(".heat i"), most)
            # The busiest is the strongest step there is, never the empty one.
            self.assertIn(max(self.steps(".heat i")), self.drawn(heat), most)
            days = [time.time() - 86400 * i for i in range(len(counts))]
            # The Players tab's cells are made once for the page (insights.day_cells) and the macro shows them.
            from opendmt3.server.web import insights
            row = {"days": counts}
            insights.day_cells([row], days, most, w)
            cells = str(charts.cells(row))
            self.assertLessEqual(self.drawn(cells), self.steps(".daycells i"), most)


class WhenTest(unittest.TestCase):
    """A moment on a page never breaks inside its date nor away from it."""

    def test_the_time_stays_with_its_date(self):
        from opendmt3.server.web.app import JOINER, _when
        shown = _when(time.mktime((2026, 11, 5, 19, 23, 0, 0, 0, -1)))
        self.assertEqual(shown, "2026-%s11-%s05 19:23" % (JOINER, JOINER))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FileNamesTest(SiteBase):
    """The files a user saves are named in lowercase: the tool, the kind and the date (the release files' rule)."""

    def test_a_backup_is_named_in_lowercase_and_an_old_name_still_counts(self):
        from opendmt3.server.services import backups
        self.make()
        name = backups.make(self.site.db_path, self.tmp, "manual")
        self.assertRegex(name, r"^opendmt3-backup-\d{8}-\d{6}-manual\.sqlite$")
        # A backup made by an older openDMT3, under its old name, is still listed, restorable and deletable.
        old = "openDMT3-20261101-120000-daily.sqlite"
        with open(os.path.join(backups.folder(self.tmp), name), "rb") as f:
            data = f.read()
        with open(os.path.join(backups.folder(self.tmp), old), "wb") as f:
            f.write(data)
        listed = {b["name"]: b["kind"] for b in backups.all_backups(self.tmp)}
        self.assertEqual(listed[old], "daily")
        self.assertTrue(os.path.isfile(backups.path_of(self.tmp, old)))
        backups.restore(self.site.db_path, self.tmp, old)
        backups.delete(self.tmp, old)
        self.assertNotIn(old, os.listdir(backups.folder(self.tmp)))

    def test_the_csv_files_are_named_in_lowercase(self):
        self.admin()
        for path, kind in (("/admin/log/plays.csv", "plays"), ("/admin/log/requests.csv", "requests"),
                           ("/admin/players.csv", "players")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertRegex(r.headers["content-disposition"],
                             r'attachment; filename="opendmt3-%s-\d{8}\.csv"' % kind, path)

    def test_the_song_list_file_is_named_in_lowercase(self):
        from opendmt3.server.services import songlist
        self.assertEqual(songlist.NAME, "opendmt3-song-list.zip")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class MadeAccountTest(AdminSiteBase):
    """The Players page's form forgets the account it just made."""

    def test_the_form_is_empty_again_after_an_account_is_made(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        made = self.console.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "msg1",
                                                         "dj_name": "DJ MSG", "password": "", "is_admin": "on"}).text
        self.assertIn("MSG1", made)
        form = made.split('value="make"', 1)[1].split("</form>", 1)[0]
        self.assertRegex(form, r'name="login_id" value=""')
        self.assertRegex(form, r'name="dj_name" value=""')
        self.assertNotIn("checked", form.split('name="is_admin"', 1)[1].split(">", 1)[0])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class CountsTest(AdminSiteBase):
    """The Status page counts the accounts as the Players list does, and says what is in the count."""

    def test_the_accounts_figure_is_every_account_and_its_label_says_how_many_are_disabled(self):
        self.admin()
        for login_id in ("NOVA", "RIO", "HANA", "MILO"):
            self.make(login_id, dj=login_id)
        store = self.site.accounts()
        try:
            store.set_disabled("MILO", True)
        finally:
            store.db.close()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/status").text
        self.assertRegex(page, r'<span class="value">5</span><span class="label">Accounts · 1 disabled</span>')


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FiguresTest(AdminSiteBase):
    """The machine's figures: one way to say a size, a number with its unit kept together, loads with two decimals."""

    def test_a_size_keeps_its_unit_and_the_database_reads_the_same_on_both_cards(self):
        from opendmt3.server.web.app import _size_words
        self.assertEqual(_size_words(1363149), "1.3 MB")
        self.assertEqual(_size_words(5 * 1024), "5 KB")
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/status").text
        size = _size_words(sum(os.path.getsize(p) for p in (self.site.db_path, self.site.db_path + "-wal")
                               if os.path.isfile(p)))
        self.assertIn('<span class="value small-value">%s</span><span class="label">Database</span>' % size, page)

    def test_the_hours_and_minutes_keep_their_units(self):
        from opendmt3.server.web import strings
        w = strings.words("en")
        self.assertEqual(w("common.hours", h=3, m=12), "3 h 12 min")
        self.assertEqual(w("common.minutes", m=5), "5 min")

    def test_the_loads_have_two_decimals(self):
        from opendmt3.server.services import machine
        self.admin()
        self.sign_in(self.console, "BOSS")
        original = machine.read_load
        machine.read_load = lambda: [6.41, 4.2, 3.0]
        try:
            page = self.console.get("/admin/status").text
        finally:
            machine.read_load = original
        self.assertIn("6.41 4.20 3.00", page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class ChangeLineTest(SiteBase):
    """A change line's MAX points have their separators, as every other MAX figure."""

    def test_max_points_in_a_change_line_have_separators(self):
        from opendmt3.server.services import players as pl
        self.make()
        store = self.site.accounts()
        try:
            pl.Players(store.db).set_points("NOVA", 432098, who="BOSS")
            pl.Players(store.db).add_points(["NOVA"], -12345, who="BOSS")
            lines = [r[0] for r in store.db.execute("SELECT what FROM changes ORDER BY id")]
        finally:
            store.db.close()
        self.assertIn("set the MAX points of NOVA to 432,098", lines)
        self.assertIn("took 12,345 MAX points from NOVA", lines)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class MarksAndDoorsTest(AdminSiteBase):
    """The players' mark carries the version as the admin site's does; the admin door says who gives a password."""

    def test_the_players_mark_has_the_version_over_its_role_word(self):
        from opendmt3 import __version__
        tail = '<span class="tail"><i class="v">v%s</i><span class="s">SERVER</span></span>' % __version__
        self.assertIn(tail, self.client.get("/signin").text)
        self.make()
        self.sign_in(self.client, "NOVA")
        self.assertIn(tail, self.client.get("/").text)

    def test_the_admin_door_says_another_admin_gives_a_new_password(self):
        # A server with an account (with none, the door is the first run).
        self.admin()
        door = self.console.get("/signin").text
        self.assertIn("Forgot your password? Another admin can give you a new one.", door)
        self.assertNotIn("server&#39;s owner can give you", door)
        # The players' door keeps the owner's line.
        self.assertIn("The server&#39;s owner can give you a new one.", self.client.get("/signin").text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class SongListPageTest(AdminSiteBase):
    """The song list page shows what the server has and what can be done, no guidance (docs/admin.md has it)."""

    def test_no_paragraph_of_guidance_and_no_command_to_copy(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/song_list").text
        self.assertNotIn("From client data on the server PC", page)
        self.assertNotIn("Without it songs show as numbers", page)
        self.assertNotIn("run this on the server PC", page)
        self.assertNotIn("./dmt3 catalog", page)
        # The state of each part and the upload stay.
        self.assertIn('class="states"', page)
        self.assertIn('action="/admin/song_list/upload"', page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class WordsTest(SiteBase):
    """The review's words: a field named for what it takes, Korean as it is said, nothing that reads unfinished."""

    def test_the_review_words(self):
        from opendmt3.server.web import strings
        en, ko = strings.words("en"), strings.words("ko")
        self.assertEqual(en("me.card.count.icon", n=6), "6 icons")
        self.assertEqual(ko("me.card.count.icon", n=6), "아이콘 6개")
        self.assertNotIn("씁니다", ko("me.card.comment.hint", max=12) + ko("me.dj.hint", max=8))
        self.assertEqual(en("me.tokens.never"), "Never")
        self.assertEqual(en("admin.never"), "Never")
        self.assertIn("added", en("download.facts", size="3.0", when="2026-11-17"))
        self.assertIsNone(strings.TEXT.get("server.remove.backup"))
        self.assertEqual(en("me.picture.file"), "Picture file")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class CardEditorTest(SiteBase):
    """The card editor says the comment's limit under the comment, and its boxes of pictures are wells, not cut parts."""

    def test_the_comment_limit_is_under_the_comment(self):
        self.make()
        self.sign_in(self.client, "NOVA")
        page = self.client.get("/account").text
        field = page.split('class="field comment-field"', 1)[1].split("</div>", 1)[0]
        self.assertIn('id="comment-hint"', field)
        self.assertIn("Up to 12 characters.", field)

    def test_no_box_of_choices_carries_a_class_the_cut_parts_have(self):
        from types import SimpleNamespace as N
        from opendmt3.server.web import strings
        # The classes the cut corner and its seam are drawn on (one rule for every cut part: site.css).
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        rule = re.search(r"\n([^{}\n]*\.card,[^{}]*)\{\s*clip-path", css).group(1)
        cut = set(re.findall(r"\.([\w-]+)", rule))
        self.assertIn("plate", cut)
        # The editor with one picture of each kind, as a server with the card pictures shows it.
        card = N(pictures=True, icon=1, plate=32768, pattern=0, level=7, max_points=0)
        choices = {kind: [N(number=n, grade="")] for kind, n in (("icon", 1), ("plate", 32768), ("pattern", 0))}
        html = self.site.templates.get_template("_card_editor.html").render(
            card=card, name="NOVA", choices=choices, comment_max=12, comment="", w=strings.words("en"))
        boxes = re.findall(r'<div class="(choices[^"]*)"', html)
        self.assertEqual(len(boxes), 3, html)
        for box in boxes:
            # A box of pictures is a well, never a cut part (the plates' box was drawn as the podium's plate).
            self.assertFalse(cut & set(box.split()), box)
