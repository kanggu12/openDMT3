"""Tests for the pages composed rather than stacked (the owner's rules of 11-19), as the server's answers show them: the
notices under the page's head (its stage flush under the bar), each admin page's head of figures before its groups, the
Status page's groups in pairs and its two settings as rows of one group, the Backups page's main key in its title row,
no box that holds one key or one fact (every play reset, the invite, the connected cabinets, a player deleted), the
account's settings as rows, the keys of one role at one height (no taller kinds of the main key, none stretched by a
rule), and every text of the style sheets at a step of the type scale.

The layout itself (heights, middles, edges, widths, the stage's place at every width) is the site check's
(tests/e2e/web/measure.js: compose). They need the web libraries (Starlette, Jinja2, httpx for the test client); without
them they are skipped.
"""

import os
import re
import unittest

from tests.server.test_admin_site import AdminSiteBase
from tests.server.test_web import WEB

# The site's style sheets, where every size of the words is written.
STATIC = os.path.join(os.path.dirname(__file__), "..", "..", "opendmt3", "server", "web", "static")
TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "..", "opendmt3", "server", "web", "templates")
# The type scale (site.css's :root says it in words; the site check's STEPS hold the pages to it).
STEPS = {11, 12, 13, 14, 15, 17, 20, 24, 28, 32, 40, 48, 56, 64}


def element_end(page, start):
    """Where the div that starts at `start` ends (its closing tag's end), counting the divs inside it."""
    depth = 0
    for m in re.finditer(r"<(/?)div\b[^>]*>", page[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start + m.end()
    return len(page)


def card_of(page, marker):
    """The markup of the nearest card (a group) that holds `marker`."""
    at = page.index(marker)
    # (Up to the end of the tag the marker is in, when it is an attribute of the card's own tag.)
    for m in reversed(list(re.finditer(r'<div\b[^>]*\bclass="card\b[^"]*"[^>]*>', page[:page.index(">", at) + 1]))):
        end = element_end(page, m.start())
        if end > at:
            return page[m.start():end]
    raise AssertionError("no card holds %s" % marker)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class HeadThenNoticesTest(AdminSiteBase):
    """The page's head first, flush under the bar; the notices under it, inside the page."""

    def test_the_notices_stand_under_the_stage_inside_the_page(self):
        from opendmt3.server.services import notice
        self.admin()
        notice.write(self.tmp, "Back at nine", "BOSS")
        self.sign_in(self.client, "BOSS")
        for path in ("/", "/rankings", "/songs", "/download", "/account"):
            page = self.client.get(path).text
            head = page.index('class="hero' if 'class="hero' in page else 'class="page-head"')
            notices = page.index('<div class="notices">')
            # Inside the page, after its head (nothing between the bar and the stage for a shard to end in).
            self.assertLess(page.index('<main id="main"'), head, path)
            self.assertLess(head, notices, path)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AdminHeadsTest(AdminSiteBase):
    """Each admin page reads its head's figures first, then its groups; Status pairs its groups."""

    def test_each_page_opens_on_its_head(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        for path in ("/admin/status", "/admin/players", "/admin/cabinets", "/admin/song_list", "/admin/backups",
                     "/admin/server", "/admin/log/plays"):
            page = self.console.get(path).text
            main = page[page.index('<div class="console-main">'):]
            first = re.search(r'<div class="card[^"]*"', main).group(0)
            # The first group is the head's plate (Status may show what to look at above it).
            if path == "/admin/status" and "card head" not in first:
                first = re.findall(r'<div class="card[^"]*"', main)[1]
            # (The head's plate is a status panel: its figures on a sunken screen.)
            self.assertRegex(first, r'^<div class="card head\b[^"]*\bk-status\b', path)
            self.assertIn('<div class="headline', main, path)

    def test_status_pairs_its_groups_and_holds_its_two_settings_as_rows_of_one(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/status").text
        self.assertEqual(page.count('<div class="pair">'), 2)
        announce = card_of(page, 'id="notice"')
        self.assertIn('id="maintenance"', announce)
        self.assertEqual(len(re.findall(r'<div class="row(?: ctl)?"[ >]', announce)), 2)
        # Maintenance's words and its key on one line: its name on the key's middle, as a control's row is (laid on
        # the words' baseline it stood a pixel and a half off the key once the words were stepped by the face).
        self.assertIn('<div class="row ctl" id="maintenance">', announce)
        # The disk is the machine's: one group of them both.
        self.assertIn("What takes the disk", card_of(page, '<div class="machine-split">'))

    def test_back_up_now_is_the_title_rows_main_key(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/backups").text
        head = page[page.index('<section class="console-head">'):page.index('<div class="console-main">')]
        self.assertIn('<form method="post" action="/admin/backups" class="head-key">', head)
        self.assertIn('<input type="hidden" name="action" value="make"><button class="btn primary">Back up now</button>', head)
        self.assertEqual(page.count('class="btn primary"'), 1)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class NoBoxOfOneThingTest(AdminSiteBase):
    """A key or a fact alone is a row of the group it belongs to, never a box of its own."""

    def test_every_play_reset_is_the_accounts_last_line_and_the_invite_is_beside_the_form(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players").text
        self.assertIn('value="reset_all"', card_of(page, "Download CSV"))
        self.assertIn('class="invite-code"', card_of(page, 'id="make"'))

    def test_what_ends_sign_ins_or_removes_is_one_danger_tray(self):
        self.admin()
        self.make("NOVA")
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players/NOVA").text
        tray = card_of(page, 'id="danger"')
        self.assertIn('class="card wide k-danger"', tray)
        for action in ("password", "reset_plays", "delete"):
            self.assertIn('name="action" value="%s"' % action, tray)
        # The ban is a tray of its own; the account's group keeps the name, the rights and the picture.
        self.assertIn('class="card k-danger"', card_of(page, 'id="ban"'))
        self.assertNotIn('value="delete"', card_of(page, 'id="account"'))

    def test_the_danger_trays_rows_say_what_each_acts_on_and_end_on_its_key(self):
        self.admin()
        self.make("NOVA")
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players/NOVA").text
        tray = card_of(page, 'id="danger"')
        # A row each, as the account's settings are: what it acts on, the words of what happens, then its key, an
        # ordinary one as a row's control is (three small keys one under another once stood at the tray's left).
        self.assertEqual(re.findall(r'<p class="row-label">([^<]+)</p>', tray), ["Password", "Plays", "Account"])
        self.assertEqual(tray.count('<p class="line-words">'), 3)
        self.assertEqual(tray.count('class="form line"'), 3)
        self.assertNotIn("btn small", tray)
        # One's own page has no Delete (that is My account's): the tray keeps its other two rows.
        own = card_of(self.console.get("/admin/players/BOSS").text, 'id="danger"')
        self.assertEqual(re.findall(r'<p class="row-label">([^<]+)</p>', own), ["Password", "Plays"])
        # The account's other keys (admin rights, the picture) on one line under the name's field.
        self.assertIn('<div class="key-row">', card_of(page, 'id="account"'))

    def test_the_connected_cabinets_are_a_live_line_in_the_home_pages_head(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/").text
        hero = page[page.index('<section class="hero">'):page.index("</section>", page.index('<section class="hero">'))]
        self.assertIn('<p class="hero-live">', hero)
        self.assertIn("Connected cabinets <b>0</b>", hero)
        self.assertNotIn(">Connected cabinets</h3>", page)

    def test_the_message_to_send_is_the_first_part_of_the_group_that_made_it(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        page = self.console.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "HANA"}).text
        made = card_of(page, 'id="message"')
        self.assertIn('id="make"', made)
        self.assertLess(made.index('id="message"'), made.index('id="make"'))

    def test_a_page_not_there_has_no_box_for_its_line_and_its_key(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/nowhere").text
        lost = page[page.index('<section class="narrow lost">'):page.index("</section>", page.index('<section class="narrow lost">'))]
        self.assertIn('<a class="btn primary" href="/">Home</a>', lost)
        self.assertNotIn('class="card', lost)

    def test_an_empty_board_says_so_on_the_rankings_own_line(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/rankings").text
        self.assertIn('<p class="page-note muted small">No cleared stage yet.</p>', page)
        self.assertNotIn('<div class="card"><p class="muted">No cleared stage', page)

    def test_the_lists_with_nothing_yet_say_so_in_the_head(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/cabinets").text
        self.assertIn("No cabinet has connected yet.", card_of(page, '<div class="headline">'))
        self.assertNotIn('<div class="card" id="cabinets">', page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AccountRowsTest(AdminSiteBase):
    """My account: each section one group of rows, its name the group's heading."""

    def test_the_sections_are_groups_of_rows(self):
        self.make("NOVA")
        self.sign_in(self.client, "NOVA")
        page = self.client.get("/account").text
        for section in ("profile", "account", "security"):
            self.assertRegex(page, r'<div class="card[^"]*">\s*<h2 id="%s-title">' % section)
        account = card_of(page, 'id="account-title"')
        self.assertIn('<label class="row-label" for="dj-name">DJ name</label>', account)
        # The account deleted: a danger tray of its own under the account's group.
        self.assertNotIn('value="delete_me"', account)
        self.assertIn('<div class="card k-danger" id="delete-account">', page)
        security = card_of(page, 'id="security-title"')
        self.assertIn('value="password"', security)
        self.assertIn('value="signout_others"', security)


class KeysAndTypeTest(unittest.TestCase):
    """One height a role of key, none stretched by a rule; every size of words on the scale."""

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def test_no_taller_kind_of_the_main_key_and_none_stretched(self):
        css = self.read(STATIC, "site.css") + self.read(STATIC, "players.css")
        self.assertNotRegex(css, r"\.btn\.(big|lg)\b")
        for name in os.listdir(TEMPLATES):
            self.assertNotRegex(self.read(TEMPLATES, name), r'class="btn[^"]*\b(big|lg)\b', name)
        # No rule makes a key as wide as what holds it (a key is as wide as its words).
        for rule in re.findall(r"([^{}]*\.btn[^{}]*)\{([^}]*)\}", css):
            selector, body = rule
            if re.search(r"\.btn\b", selector.split(",")[-1]) or any(re.search(r"\.btn\b(?![-\w])", part) for part in selector.split(",")):
                self.assertNotRegex(body, r"(^|;)\s*width:\s*100%", selector.strip())
                self.assertNotRegex(body, r"(^|;)\s*flex:\s*1\b", selector.strip())

    def test_every_size_of_words_is_a_step_of_the_scale(self):
        # Every size the style sheets give words, but the drawings' (the DJ card as the game draws it, the mark, a
        # page's big code) and the fields' own (a field's words follow the platform: 16 px on a touch screen).
        drawn = re.compile(r"\.(djcard|dj-comment|dj-level|cp-|card-preview|logo|lost-code|mc-number)|\b(input|select|textarea)\b|:is\(input")
        for sheet in ("site.css", "players.css"):
            css = self.read(STATIC, sheet)
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if drawn.search(selector):
                    continue
                for size in re.findall(r"(?:font-size:\s*|font:[^;]*?\s)(\d+(?:\.\d+)?)px", body):
                    self.assertIn(float(size), STEPS, "%s: %s px in %s" % (sheet, size, selector.strip()[-60:]))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class CardKindsTest(AdminSiteBase):
    """Each card takes its kind by one modifier (_work/theme/CARDS.md): its face and shape follow what it holds."""

    def kinds(self, page):
        """Each card's kind on a page, in its order (a card with none is a settings plate)."""
        found = []
        for m in re.finditer(r'<div\b[^>]*\bclass="(card\b[^"]*)"', page):
            kind = re.search(r"\bk-(\w+)", m.group(1))
            found.append(kind.group(1) if kind else "settings")
        return found

    def test_the_status_page(self):
        self.admin()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/status").text
        # The head and the machine on a status panel's sunken screen; the plays and the song list as lists; this
        # server's facts quiet; the notice and maintenance a settings plate.
        self.assertEqual(self.kinds(page), ["status", "list", "info", "status", "list", "list", "settings"])
        self.assertIn('<div class="k-screen">', card_of(page, '<div class="headline">'))
        self.assertIn('<div class="k-screen">', card_of(page, '<div class="machine-split">'))

    def test_the_home_page_and_a_djs(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/").text
        # One's own DJ: the plate holding the member's card.
        self.assertIn('class="card dj k-member', page)
        page = self.client.get("/dj/1").text
        self.assertEqual(self.kinds(page)[:2], ["result", "result"])

    def test_the_kinds_are_one_class_each_in_the_style_sheet(self):
        with open(os.path.join(STATIC, "site.css"), encoding="utf-8") as f:
            css = f.read()
        for kind in ("status", "member", "result", "list", "info", "danger"):
            self.assertIn(".card.k-%s" % kind, css)
        # A result is cut at two opposite corners, and its ring follows both cuts.
        self.assertIn("var(--cut) 100%, 0 calc(100% - var(--cut))", css)


def media_blocks(css, query):
    """The rules inside every @media block for `query`, together (each block read to its own closing brace)."""
    found = []
    for m in re.finditer(r"@media %s \{" % re.escape(query), css):
        depth = 1
        for brace in re.finditer(r"[{}]", css[m.end():]):
            depth += 1 if brace.group() == "{" else -1
            if depth == 0:
                found.append(css[m.end():m.end() + brace.start()])
                break
    return "\n".join(found)


class WordsWholeTest(unittest.TestCase):
    """No word broken inside itself by a squeezed column, no stacked cell's value back under its label, and a phone's
    English notice with the row's width for its words (where each lands on a page is the site check's: wraps,
    unlabelled)."""

    def setUp(self):
        with open(os.path.join(STATIC, "site.css"), encoding="utf-8") as f:
            self.css = f.read()
        self.phone = media_blocks(self.css, "(max-width: 760px)")

    def test_a_korean_tables_columns_are_as_wide_as_their_words(self):
        # The Korean page breaks anywhere (body.lang-ko), which let a column be squeezed under its word ("syste", "m"):
        # a table's cells break a word only when it is wider than the whole line, and under a cell's own rule.
        self.assertIn(":where(body.lang-ko) .table :is(th, td) { overflow-wrap: break-word; }", self.css)
        self.assertIn(".table .token-name { overflow-wrap: anywhere; }", self.css)

    def test_a_stacked_cells_label_is_a_column_of_its_own(self):
        # On a phone the value starts past its label (the cell's padding) and the label is pulled back into that
        # padding by as much (its width and the gap after it): a value's second line starts where its first did.
        cell = re.search(r"td\[data-label\] \{ padding-left: (\d+)px; \}", self.phone)
        label = re.search(r"td\[data-label\]::before \{[^}]*\bwidth: (\d+)px;[^}]*margin: 0 (\d+)px 0 -(\d+)px;", self.phone)
        self.assertIsNotNone(cell)
        self.assertIsNotNone(label)
        width, gap, back = (int(v) for v in label.groups())
        self.assertEqual(int(cell.group(1)), width + gap)
        self.assertEqual(back, width + gap)

    def test_every_glyph_is_stepped_by_its_faces_own_advance(self):
        # The default rendering steps each glyph by a whole pixel on Linux ("487 25"): the page's words take the
        # face's own advances, the fields too (the browser's sheet sets them back to auto).
        self.assertRegex(self.css, r"(?s)\nbody \{[^}]*text-rendering: geometricPrecision;")
        self.assertIn(":is(input, select, textarea) { text-rendering: inherit; }", self.css)
        # A key's words and the menu's keep the default their place was set by (the site check measures a key's ink);
        # a tab's take the face's, their line a pixel lower in the box to stay where they stood.
        self.assertIn(":is(.btn, button, .menu a) { text-rendering: auto; }", self.css)
        self.assertIn(".tabs a { padding: 10px 22px 8px;", self.css)
        self.assertIn(".tabs.quiet a { padding: 7px 14px 5px; }", self.css)
        self.assertIn(".tabs a { padding: 10px 14px 8px; }", self.phone)

    def test_an_english_notices_words_have_the_rows_width_on_a_phone(self):
        # The lamp and the label on a line of their own over the words; the words fill their line beside More.
        self.assertIn("body:not(.lang-ko) .notices .site-notice { flex-wrap: wrap;", self.phone)
        self.assertIn("body:not(.lang-ko) .notices .site-notice .label { flex-basis: 100%; }", self.phone)
        self.assertIn("body:not(.lang-ko) .notices .site-notice .text { flex: 1 1 0; }", self.phone)
        # A Korean word of the admin's notice whole on a page in any language.
        self.assertRegex(self.css, r"\.site-notice \.text \{[^}]*word-break: keep-all;")
