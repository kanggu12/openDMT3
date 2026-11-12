"""The licence texts the installed launcher carries (packaging/windows/notices.py): gathered from what the build holds,
every part with its row in NOTICES.txt and its full text in licenses/, and a build that holds a part without its
text, or a library no part claims, stopped. On made-up builds: made-up packages, a made-up Python and the folders a
build makes; the kept texts are the repository's own."""

import importlib.metadata
import importlib.util
import os
import re
import shutil
import tempfile
import unittest

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The script is no module of the package: it is loaded from its file, as the build runs it.
_SPEC = importlib.util.spec_from_file_location("notices", os.path.join(ROOT, "packaging", "windows", "notices.py"))
notices = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notices)

# A licence's short notice, as some packages ship it instead of the whole Apache License.
SHORT_APACHE = "Licensed under the Apache License, Version 2.0 (the \"License\");\n"


def write(path, text):
    """A text file, with its folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def package(site, name, version, module, metadata, files):
    """A made-up installed package: its .dist-info with METADATA (extra lines given) and the files given (path inside
    the .dist-info -> text), and a RECORD that lists them with its module."""
    info = os.path.join(site, "%s-%s.dist-info" % (name.replace("-", "_"), version))
    write(os.path.join(info, "METADATA"), "Metadata-Version: 2.4\nName: %s\nVersion: %s\n%s" % (name, version, metadata))
    for rel, text in files.items():
        write(os.path.join(info, rel), text)
    write(os.path.join(site, module, "__init__.py"), "")
    record = ["%s/__init__.py,," % module, "%s/METADATA,," % os.path.basename(info)]
    record += ["%s/%s,," % (os.path.basename(info), rel) for rel in files]
    write(os.path.join(info, "RECORD"), "\n".join(record) + "\n")


class LauncherLicencesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        site = os.path.join(self.tmp, "site")
        # A package under BSD-3-Clause with its text where PEP 639 keeps it.
        package(site, "made-web", "1.0", "made_web", "License-Expression: BSD-3-Clause\nLicense-File: LICENSE.txt\n",
                {"licenses/LICENSE.txt": "Made-up BSD text\n"})
        # One under Apache-2.0 whose own file is the short notice only, beside METADATA as older tools put it.
        package(site, "made-apache", "2.0", "made_apache", "License-Expression: Apache-2.0\nLicense-File: LICENSE\n",
                {"LICENSE": SHORT_APACHE})
        # One with its licence in a classifier and an SBOM beside it.
        package(site, "made-sbom", "3.0", "made_sbom", "Classifier: License :: OSI Approved :: MIT License\n"
                "License-File: COPYING\n", {"licenses/COPYING": "Made-up MIT text\n",
                                            "sboms/made.cyclonedx.json": "{}\n"})
        # A build tool the program does not carry: never listed.
        package(site, "made-tool", "4.0", "made_tool", "License-Expression: MIT\nLicense-File: LICENSE\n",
                {"licenses/LICENSE": "The tool's text\n"})
        self.installed = {notices._key(d.metadata["Name"]): d for d in importlib.metadata.distributions(path=[site])}
        self.owners = {"made_web": ["made-web"], "made_apache": ["made-apache"], "made_sbom": ["made-sbom"],
                       "made_tool": ["made-tool"]}
        # A made-up Windows Python: its licence, its program library and the OpenSSL its ssl module uses.
        self.python = os.path.join(self.tmp, "python")
        write(os.path.join(self.python, "LICENSE.txt"), "Made-up PSF text\n")
        write(os.path.join(self.python, "python312.dll"), "")
        write(os.path.join(self.python, "DLLs", "_ssl.pyd"), "")
        write(os.path.join(self.python, "DLLs", "libssl-3-x64.dll"), "")
        # The repository it is built from.
        self.repo = os.path.join(self.tmp, "repo")
        write(os.path.join(self.repo, "LICENSE"), "MIT License\n\nCopyright (c) J.-G. Kang\n")
        write(os.path.join(self.repo, "opendmt3", "__init__.py"), '__version__ = "9.8.7"\n')
        # PyInstaller's folder, as a build leaves it: the programs, then everything else in _internal.
        self.dist = os.path.join(self.tmp, "dist", "openDMT3")
        inside = os.path.join(self.dist, "_internal")
        for name in ("python312.dll", "VCRUNTIME140.dll", "_ssl.pyd", "libssl-3-x64.dll"):
            write(os.path.join(inside, name), "")
        # A package with files beside the programs (made_apache's is inside the program, as its module list says).
        write(os.path.join(inside, "made_web", "_speedups.pyd"), "")
        write(os.path.join(inside, "opendmt3", "core", "cabinet", "bin", "CRT_R1.dll"), "")
        write(os.path.join(inside, "opendmt3", "core", "cabinet", "bin", "card-reader-NOTICES.txt"), "The library's notices\n")
        write(os.path.join(inside, "opendmt3", "client", "bin", "7-Zip", "License.txt"), "7-Zip's licence\n")
        write(os.path.join(inside, "opendmt3", "client", "bin", "7-Zip", "readme.txt"), "7-Zip 25.01\n----\n")
        for name in ("Saira-OFL.txt", "Pretendard-OFL.txt"):
            write(os.path.join(inside, "opendmt3", "client", "assets", "fonts", name), "OFL of %s\n" % name)
        # The site's copy of Pretendard's licence, the same text as the launcher's.
        write(os.path.join(inside, "opendmt3", "server", "web", "static", "fonts", "OFL-Pretendard.txt"),
              "OFL of Pretendard-OFL.txt\n")
        self.modules = {"made_apache", "made_sbom", "opendmt3", "json"}

    def gather(self):
        return notices.gather(self.dist, self.repo, self.modules, installed=self.installed, owners=self.owners,
                              python_root=self.python)

    def notices_text(self):
        with open(os.path.join(self.dist, "licenses", "NOTICES.txt"), encoding="utf-8") as f:
            return f.read().replace("\r\n", "\n")

    def test_every_part_the_build_holds_has_its_row_and_its_text(self):
        notes = self.gather()
        self.assertEqual(notes.problems, [])
        text = self.notices_text()
        # openDMT3's own first, with its version, then Python with its C runtime, then the library in its ssl module.
        self.assertTrue(text.split("\n\n")[1].startswith("openDMT3 9.8.7"))
        self.assertIn("Python %d.%d.%d, with the Microsoft C runtime it ships (VCRUNTIME140.dll)" % os.sys.version_info[:3],
                      text)
        self.assertIn("OpenSSL ", text)
        # Each package the program carries, with its version, its licence as its metadata says it and its text.
        self.assertIn("made-web 1.0\n  License: BSD-3-Clause\n  Text:    made-web-LICENSE.txt", text)
        # A licence classifier when there is no expression; the SBOM beside the licence.
        self.assertIn("made-sbom 3.0\n  License: MIT License\n  Text:    made-sbom-COPYING.txt, "
                      "made-sbom-made.cyclonedx.json", text)
        # The short Apache notice gets the whole licence beside it, from the kept text.
        self.assertIn("made-apache 2.0\n  License: Apache-2.0\n  Text:    made-apache-LICENSE.txt, Apache-2.0.txt", text)
        with open(os.path.join(self.dist, "licenses", "Apache-2.0.txt"), encoding="utf-8") as f:
            self.assertIn("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", f.read())
        # A build tool is not in the program: it is not in its notices.
        self.assertNotIn("made-tool", text)
        # openDMT3's parts by others, with the texts the build put beside them: 7-Zip, the card reader library's
        # notices, the fonts (the site's copy of Pretendard's licence the same file as the launcher's).
        self.assertIn("7-Zip 25.01 for Windows", text)
        self.assertIn("Text:    card-reader-NOTICES.txt", text)
        self.assertIn("Text:    Pretendard-OFL.txt, Saira-OFL.txt\n", text)
        # Every file in the folder is named by a row, and every row's file is there (write() checks both).
        named = set(re.findall(r"^  Text:    (.*)$", text, re.M))
        files = {f for line in named for f in line.split(", ")}
        self.assertEqual(files, set(os.listdir(os.path.join(self.dist, "licenses"))) - {"NOTICES.txt"})

    def test_a_package_without_its_licence_stops_the_build(self):
        os.remove(os.path.join(self.tmp, "site", "made_web-1.0.dist-info", "licenses", "LICENSE.txt"))
        self.installed = {notices._key(d.metadata["Name"]): d
                          for d in importlib.metadata.distributions(path=[os.path.join(self.tmp, "site")])}
        problems = self.gather().problems
        self.assertTrue(any("made-web 1.0 names no licence file" in p for p in problems), problems)

    def test_a_library_no_part_claims_stops_the_build(self):
        write(os.path.join(self.dist, "_internal", "mystery.dll"), "")
        problems = self.gather().problems
        self.assertIn("mystery.dll is in the program, and no part of NOTICES.txt claims it", problems)

    def test_the_card_reader_library_without_its_notices_stops_the_build(self):
        os.remove(os.path.join(self.dist, "_internal", "opendmt3", "core", "cabinet", "bin", "card-reader-NOTICES.txt"))
        problems = self.gather().problems
        self.assertTrue(any("card-reader-NOTICES.txt" in p for p in problems), problems)

    def test_the_notices_name_every_file_and_every_name_is_a_file(self):
        folder = os.path.join(self.tmp, "licenses")
        os.makedirs(folder)
        notes = notices.Notices(folder)
        # A text no row names, and a row naming a text that is not there.
        notes.text("loose-LICENSE.txt", "a text")
        notes.row("a part", "MIT", ["gone-LICENSE.txt"])
        notes.write()
        self.assertEqual(notes.problems, ["loose-LICENSE.txt is in licenses but no part names it",
                                          "a part names gone-LICENSE.txt, which is not in licenses"])

    def test_a_folder_from_an_earlier_build_is_made_afresh(self):
        write(os.path.join(self.dist, "licenses", "old-LICENSE.txt"), "from an earlier build")
        self.assertEqual(self.gather().problems, [])
        self.assertNotIn("old-LICENSE.txt", os.listdir(os.path.join(self.dist, "licenses")))

    def test_a_licence_as_the_metadata_says_it(self):
        message = importlib.metadata.Distribution.at(os.path.join(self.tmp, "site", "made_web-1.0.dist-info")).metadata
        self.assertEqual(notices.licence_of(message), "BSD-3-Clause")
        # A License field holding a whole text is no name; the classifiers say it then.
        email = __import__("email.message").message.Message()
        email["License"] = "Line one\nline two"
        email["Classifier"] = "License :: OSI Approved :: BSD License"
        self.assertEqual(notices.licence_of(email), "BSD License")

    def test_every_kept_text_is_there_and_said_where_it_came_from(self):
        with open(os.path.join(notices.KEPT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        kept = [entry[-1] for entry in notices.LIBRARIES] + list(notices.KEPT_FOR.values()) + [notices.APACHE[1]]
        for name in kept:
            with self.subTest(text=name):
                self.assertTrue(os.path.getsize(os.path.join(notices.KEPT, name)) > 100)
                self.assertIn("`%s`" % name, readme)


if __name__ == "__main__":
    unittest.main()
