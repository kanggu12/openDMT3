"""The documents stay true to the repository: every test case has an ID of its own and points at a check that
exists, every link leads to a file and a heading that are there, every picture a document embeds is in the
repository, and all of them are in English. The documents are the README, the guides in docs/, CONTRIBUTING.md,
CHANGELOG.md and what GitHub shows from .github/ (its pages and its issue forms)."""

import collections
import os
import re
import unittest

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _files(folder, ending):
    """The files of one folder with this ending, as paths from the repository's top, in order."""
    return sorted(os.path.join(folder, n).replace(os.sep, "/") for n in os.listdir(os.path.join(ROOT, folder))
                  if n.endswith(ending))


# The pages people read as Markdown: links, headings and pictures are checked in these.
PAGES = ["README.md", "CONTRIBUTING.md", "CHANGELOG.md"] + _files("docs", ".md") + _files(".github", ".md")
# The issue forms are YAML: their words are read too (the language), but they hold no Markdown links to follow.
FORMS = _files(os.path.join(".github", "ISSUE_TEMPLATE"), ".yml")
# A case's check, written `folder/file#text` in a table cell (the intro's `file#text` names the form, not a check).
CHECK = re.compile(r"`([\w.-]+/[\w./-]+)#([^`]+)`")
# A Markdown link's target; images and links alike.
LINK = re.compile(r"\]\(([^)\s]+)\)")
# What an HTML tag in a page points at: a link's href, a picture's src, a picture's other source (the dark one).
HTML_TARGET = re.compile(r"""<(a|img|source)\b[^>]*?\b(href|src|srcset)=["']([^"']+)["']""")
# A table row that opens with a case's ID: | SETUP-01 | ...
CASE_ROW = re.compile(r"^\| ([A-Z]+-\d+) \|")
# A cell's end: a bar that no backslash escapes (a bar inside a code span is written \|).
CELL_END = re.compile(r"(?<!\\)\|")


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def slug(heading):
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces as hyphens."""
    text = heading.strip().lower()
    # Letters, digits, spaces, hyphens and underscores stay; everything else (backquotes, commas, colons) goes.
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    """Every heading's anchor in a Markdown file (code blocks left out: a # there is a comment)."""
    found, fenced = set(), False
    for line in read(path).split("\n"):
        if line.startswith("```"):
            # A fence opens or closes a code block.
            fenced = not fenced
            continue
        match = re.match(r"#{1,6} (.+)", line)
        if match and not fenced:
            found.add(slug(match.group(1)))
    return found


def prose(text):
    """A page's text without its fenced code blocks: a link or a tag in an example is no link of the page's."""
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


def targets(page):
    """What a page points at inside the repository, as (kind, target): its Markdown links and pictures ("link"), its
    HTML links ("link") and its HTML pictures with their dark sources ("picture")."""
    text = prose(read(page))
    found = [("link", target) for target in LINK.findall(text)]
    for tag, _, target in HTML_TARGET.findall(text):
        found.append(("link" if tag == "a" else "picture", target))
    # A web address is not the repository's to check.
    return [(kind, target) for kind, target in found if not re.match(r"[a-z]+:", target)]


class DocumentsTest(unittest.TestCase):
    def test_every_case_points_at_a_check_that_exists(self):
        checks = CHECK.findall(read("docs/test-cases.md"))
        # The table has dozens of cases; a pattern that stopped matching would pass with none.
        self.assertGreater(len(checks), 60)
        for path, text in checks:
            with self.subTest(check="%s#%s" % (path, text)):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), "no such file")
                # assertTrue, not assertIn: a failure names the text, not the whole file.
                self.assertTrue(text in read(path), "the file no longer has this text")

    def test_every_case_has_an_id_of_its_own_and_every_cell(self):
        rows, header = [], None
        for line in read("docs/test-cases.md").split("\n"):
            if line.startswith("| ID |"):
                # The table this row opens: its cases have as many cells as it has.
                header = len(CELL_END.findall(line))
            match = CASE_ROW.match(line)
            if match:
                rows.append((match.group(1), len(CELL_END.findall(line)), header, line))
        # Hundreds of cases; a pattern that stopped matching would pass with none.
        self.assertGreater(len(rows), 300)
        twice = sorted(i for i, n in collections.Counter(case for case, _, _, _ in rows).items() if n > 1)
        # One number names one case: a second use of it hides one of the two from whoever looks a case up.
        self.assertEqual(twice, [], "used twice: %s" % ", ".join(twice))
        for case, cells, wanted, line in rows:
            with self.subTest(case=case):
                # A row short of a cell (its check, or where it runs) is a case nothing checks.
                self.assertEqual(cells, wanted, "the row has %d cells, its table %d" % (cells - 1, (wanted or 0) - 1))
                if wanted and wanted > 5:
                    # A table with a "Checked by" column: its cell names a check as `file#text`.
                    self.assertTrue(CHECK.search(line), "no `file#text` check in the row")

    def test_every_link_leads_somewhere(self):
        seen = 0
        for page in PAGES:
            folder = os.path.dirname(page)
            for kind, target in targets(page):
                if kind != "link":
                    continue
                path, _, anchor = target.partition("#")
                # A bare #anchor is a heading in the same page.
                resolved = os.path.normpath(os.path.join(folder, path)).replace(os.sep, "/") if path else page
                if resolved.startswith(".."):
                    # Above the repository: a page of the repository's site (its releases), not a file.
                    continue
                seen += 1
                with self.subTest(page=page, link=target):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, resolved)), "no such file")
                    if anchor and resolved.endswith(".md"):
                        self.assertIn(anchor, anchors(resolved), "no such heading")
        # Each page links to others; none at all would mean the pattern broke.
        self.assertGreater(seen, 60)

    def test_every_picture_a_page_embeds_is_in_the_repository(self):
        seen = 0
        for page in PAGES:
            folder = os.path.dirname(page)
            for kind, target in targets(page):
                # A Markdown picture is a link by its form: told by what it points at.
                if kind != "picture" and not re.search(r"\.(svg|png|jpe?g|gif|webp)$", target, re.I):
                    continue
                seen += 1
                with self.subTest(page=page, picture=target):
                    resolved = os.path.normpath(os.path.join(folder, target))
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, resolved)), "no such picture")
                    # A picture of nothing (a build that failed half way) is no picture.
                    self.assertGreater(os.path.getsize(os.path.join(ROOT, resolved)), 500, "an empty picture")
        # The README alone embeds several (its logo, its screens, its figure, each light and dark).
        self.assertGreater(seen, 6)

    def test_the_pictures_drawn_as_svg_hold_all_they_show(self):
        pictures = _files(os.path.join("docs", "images"), ".svg")
        self.assertGreater(len(pictures), 3)
        for picture in pictures:
            with self.subTest(picture=picture):
                text = read(picture)
                # GitHub shows a picture alone, with no way to another file: a font, an image or a style sheet it
                # points at would not be there.
                self.assertIsNone(re.search(r"""(href|src)=["'](?!#)""", text), "it points at another file")
                self.assertNotIn("@import", text)
                self.assertNotIn("url(http", text)

    def test_the_documents_are_in_english(self):
        for page in PAGES + FORMS:
            with self.subTest(page=page):
                # Hangul syllables or jamo: the documents are English only (the launcher and the site speak Korean).
                self.assertIsNone(re.search(r"[ᄀ-ᇿ㄰-㆏가-힣]", read(page)))

    def test_the_instruments_find_what_they_are_for(self):
        # A heading's anchor as GitHub makes it, a link in a code block left out, an HTML picture found.
        self.assertEqual(slug("What `ingame.sh` checks"), "what-ingamesh-checks")
        self.assertEqual(prose("a\n```sh\n[x](missing.md)\n```\nb\n"), "a\n\nb\n")
        self.assertEqual(HTML_TARGET.findall('<source media="(prefers-color-scheme: dark)" srcset="a-dark.svg">'
                                             '<img alt="x" src="a.svg" width="100%"><a href="#top">'),
                         [("source", "srcset", "a-dark.svg"), ("img", "src", "a.svg"), ("a", "href", "#top")])
        # A bar a backslash escapes ends no cell.
        self.assertEqual(len(CELL_END.findall(r"| A-1 | `a \| b` | c |")), 4)


if __name__ == "__main__":
    unittest.main()
