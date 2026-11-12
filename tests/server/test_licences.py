"""The site's Licenses page and its API twin list what the server and the launcher it hands out are made with, as
OpenDMTQ's page lists its own: openDMT3's own licence with its text, the parts with what each is for and its licence,
and the fonts with theirs. The list is kept true: every package the server's image and the launcher's build pin is
named, and so is every package those bring along, with the licence its metadata gives (checked where this Python has
them installed); the versions it names are the ones the build pins."""

import importlib.metadata
import os
import re
import unittest

from tests.server.test_web import WEB, WebBase

if WEB:
    # The site's words and its list of parts, which need the site's libraries (without them both classes are skipped).
    from opendmt3.server.web import common, strings

# The repository's top folder (this file is in tests/server/).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Where the parts run: the server's image (python:3.12 on Linux) and the launcher (python-build-standalone's 3.12 on
# Windows). The markers of what a package brings along are read for these, not for the Python running the tests: a
# package one of them brings is named.
TARGETS = ({"python_version": (3, 12), "sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
           {"python_version": (3, 12), "sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"})
# A licence as package metadata says it, and the words of it the parts' table uses.
SAID = {"BSD-3-Clause": "BSD 3-Clause", "BSD License": "BSD", "MIT": "MIT", "MIT License": "MIT",
        "Apache-2.0": "Apache License 2.0", "PSF-2.0": "PSF", "MIT-CMU": "MIT-CMU"}


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def pinned():
    """Every package name == version the server's image and the launcher's build machine install with pip."""
    names = set()
    for dockerfile in ("packaging/docker/Dockerfile", "packaging/windows/Dockerfile"):
        # A command's lines joined where they end in a backslash, so a pip install is one line however it wraps.
        text = read(dockerfile).replace("\\\n", " ")
        for line in re.findall(r"pip install[^\n]*", text):
            names.update(name.lower() for name in re.findall(r"([A-Za-z0-9_.-]+)==[0-9]", line))
    return names


# One comparison in a marker: the name, its operator, the quoted value.
COMPARISON = r"(python_version|sys_platform|platform_system|os_name)\s*(<=|>=|==|!=|<|>)\s*['\"]([^'\"]*)['\"]"


def applies(marker):
    """Whether a requirement's marker holds where the parts run (any of TARGETS): an extra never does; comparisons of
    the Python version and of the platform are worked out; any other marker fails the test, so that a new kind is
    looked at, not guessed."""
    if "extra" in marker:
        return False
    held = []
    for target in TARGETS:

        def compare(match, target=target):
            name, op, value = match.group(1), match.group(2), match.group(3)
            have = target[name]
            # A version compares number by number; a platform's name as text.
            want = tuple(int(n) for n in value.split(".")) if name == "python_version" else value
            return str({"<": have < want, "<=": have <= want, ">": have > want, ">=": have >= want,
                        "==": have == want, "!=": have != want}[op])
        worked = re.sub(COMPARISON, compare, marker)
        if not re.fullmatch(r"(\s|True|False|and|or|not|\(|\))*", worked):
            raise AssertionError("a marker this test cannot read: %s" % marker)
        held.append(eval(worked, {"__builtins__": {}}))  # noqa: S307  (only True, False, and, or, not and brackets)
    return any(held)


def brought_along(names):
    """The installed packages these bring along, for the shipped Python (those not installed here are left out)."""
    found, todo = {}, list(names)
    while todo:
        name = todo.pop()
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        key = dist.metadata["Name"].lower()
        if key in found:
            continue
        found[key] = dist
        for requirement in dist.requires or []:
            spec, _, marker = requirement.partition(";")
            if marker and not applies(marker):
                continue
            todo.append(re.split(r"[\s<>=!~\[(]", spec.strip(), 1)[0])
    return found


def row_of(name):
    """The parts' row that names a package (any letter case), or None."""
    for part, use, licence in common.LICENCE_PARTS:
        if name.lower() in [p.strip().lower() for p in part.split(",")]:
            return part, use, licence
    return None


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class PartsListTest(unittest.TestCase):

    def test_every_package_the_builds_pin_is_named(self):
        names = pinned()
        # Both images pin the site's libraries; the launcher's also PyInstaller and Velopack.
        self.assertGreaterEqual(names, {"starlette", "jinja2", "uvicorn", "python-multipart", "pillow", "pyinstaller",
                                        "velopack"})
        for name in sorted(names):
            with self.subTest(package=name):
                self.assertIsNotNone(row_of(name), "name it in common.LICENCE_PARTS")

    def test_what_they_bring_along_is_named_with_its_licence(self):
        # PyInstaller builds the launcher and leaves only its bootloader in it (named in the table): what it needs to
        # build is not handed out.
        found = brought_along(pinned() - {"pyinstaller"})
        # In a Python with the site's libraries there are a dozen; with none of them, nothing to check here.
        if "starlette" not in found:
            self.skipTest("the site's libraries are not installed in this Python")
        self.assertGreaterEqual(len(found), 10)
        for key, dist in sorted(found.items()):
            with self.subTest(package=key):
                row = row_of(dist.metadata["Name"])
                self.assertIsNotNone(row, "%s is brought along: name it in common.LICENCE_PARTS" % key)
                metadata = dist.metadata
                said = (metadata.get("License-Expression") or metadata.get("License") or "").strip()
                if not said or len(said) > 60:
                    # A licence classifier when the fields hold nothing short.
                    said = [c.split("::")[-1].strip() for c in metadata.get_all("Classifier") or []
                            if c.startswith("License ::")][0]
                self.assertIn(said, SAID, "a licence the table has no words for")
                self.assertIn(SAID[said], strings.TEXT[row[2]][0])

    def test_the_versions_named_are_the_ones_built(self):
        # 7-Zip's release, as packaging/windows/sevenzip.sh and the server's image take it.
        release = re.search(r"^SEVENZIP_VERSION=(\S+)$", read("packaging/windows/sevenzip.sh"), re.M).group(1)
        self.assertIsNotNone(row_of("7-Zip " + release))
        self.assertIn("7z%s-linux-x64" % release.replace(".", ""), read("packaging/docker/Dockerfile"))
        # CI's tests of archives take the same release by the same address and hash.
        linux = re.search(r"^SEVENZIP_LINUX_URL=(\S+)\nSEVENZIP_LINUX_SHA256=(\S+)$",
                          read("packaging/windows/sevenzip.sh"), re.M)
        ci = read(".github/workflows/ci.yml")
        self.assertIn(linux.group(1), ci)
        self.assertIn(linux.group(2), ci)
        # OpenAL Soft's release, as native/openal/build.sh builds it for the Sound page's mixer.
        openal = re.search(r"^OPENAL_VERSION=(\S+)$", read("native/openal/build.sh"), re.M).group(1)
        self.assertIsNotNone(row_of("OpenAL Soft " + openal))
        # Python's: the server image's base and the launcher's Windows Python.
        self.assertIsNotNone(row_of("Python 3.12"))
        self.assertIn("FROM python:3.12-", read("packaging/docker/Dockerfile"))
        self.assertIn("/cpython-3.12.", read("packaging/windows/build.sh"))

    def test_every_word_of_the_table_is_said_in_both_languages(self):
        for part, use, licence in common.LICENCE_PARTS:
            for key in (use, licence):
                with self.subTest(key=key):
                    english, korean = strings.TEXT[key]
                    self.assertTrue(english and korean)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class LicensesPageTest(WebBase):

    def copyright(self):
        """The copyright line of openDMT3's own licence: its text and no other on the page."""
        return next(line for line in read("LICENSE").splitlines() if line.startswith("Copyright"))

    def test_the_page_says_openDMT3s_licence_the_parts_and_the_fonts(self):
        page = self.client.get("/licenses")
        self.assertEqual(page.status_code, 200)
        text = page.text
        # openDMT3's own licence, what it does not cover, and its text in full (the repository's LICENSE).
        self.assertIn("openDMT3&#39;s own code and guides are under the MIT License.", text)
        self.assertIn("It does not cover the game or its files", text)
        self.assertIn(self.copyright(), text)
        # Each part with its words in this language, in the table's order.
        cells = re.findall(r'<td class="part">([^<]*)</td>', text)
        self.assertEqual(cells, [part for part, _, _ in common.LICENCE_PARTS])
        self.assertIn("The launcher carries every full text in its program&#39;s licenses folder", text)
        # The fonts' licences in full, as before.
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)
        self.client.cookies.set("opendmt3_lang", "ko")
        korean = self.client.get("/licenses").text
        self.assertIn("openDMT3 자체의 코드와 안내서는 MIT 라이선스를 따릅니다.", korean)
        self.assertIn(strings.TEXT["licenses.use.passes"][1], korean)

    def test_without_its_licence_beside_it_the_page_names_it_without_the_text(self):
        from unittest import mock
        with mock.patch.object(common, "OWN_LICENCE", os.path.join(self.tmp, "no-LICENSE")):
            text = self.client.get("/licenses").text
            twin = self.client.get("/api/v1/licenses").json()
        self.assertIn("under the MIT License.", text)
        self.assertNotIn(self.copyright(), text)
        self.assertEqual(twin["own"], {"name": "MIT License", "text": None})

    def test_the_api_twin_gives_the_same(self):
        twin = self.client.get("/api/v1/licenses").json()
        self.assertEqual(twin["own"], {"name": "MIT License", "text": read("LICENSE")})
        self.assertEqual([p["part"] for p in twin["parts"]], [part for part, _, _ in common.LICENCE_PARTS])
        self.assertEqual(twin["parts"][0]["used_for"], strings.TEXT["licenses.use.site"][0])
        korean = self.client.get("/api/v1/licenses?lang=ko").json()
        self.assertEqual(korean["parts"][0]["license"], strings.TEXT["licenses.lic.site"][1])
        # The fonts' licences as before.
        self.assertEqual([item["name"] for item in twin["licenses"]], ["SIL Open Font License 1.1"] * 2)
        # The answer's keys in the spelling the address has (/api/v1/licenses): no other spelling beside them.
        self.assertEqual(sorted(twin), ["licenses", "own", "parts"])
        self.assertEqual(sorted(twin["parts"][0]), ["license", "part", "used_for"])


if __name__ == "__main__":
    unittest.main()
