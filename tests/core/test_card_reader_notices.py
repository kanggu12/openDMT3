"""The notices of the code built into openDMT3's card reader library go wherever the library goes: native/cardreader
makes them beside it, a build keeps them beside it, and the launcher puts them in place with it."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from opendmt3.core.cabinet import native, steps

# The repository's top folder (this file is in tests/core/).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CardReaderNoticesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        # A stand-in for the built library (a copy of the repository has none), and its notices beside it.
        self.dll = os.path.join(self.tmp, "CRT_R1.dll")
        with open(self.dll, "wb") as f:
            f.write(b"MZ openDMT3 library stand-in")
        self.notices = os.path.join(self.tmp, native.NOTICES)

    def test_the_notices_go_wherever_the_library_goes(self):
        with open(self.notices, "w", encoding="utf-8") as f:
            f.write("the library's notices")
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll}):
            self.assertEqual(native.notices(), self.notices)
            sources = steps.CardReader()._sources()
        # Every file the step writes comes from this map: the notices are one of them, from beside the library.
        self.assertEqual(sources[steps.CardReader.NOTICES], self.notices)
        self.assertEqual(sources[steps.CardReader.REL], self.dll)
        # Recorded and put back with the library's other files.
        self.assertIn(steps.CardReader.NOTICES, steps.CardReader.FILES)

    def test_the_notices_under_an_earlier_launchers_name_go_when_the_files_are_written_again(self):
        with open(self.notices, "w", encoding="utf-8") as f:
            f.write("the library's notices")
        # openDMT3's folder as an earlier launcher left it: the notices named after the library's file.
        own = steps.Own(os.path.join(self.tmp, "own"))
        os.makedirs(own.folder)
        former = own.path("openDMT3-CRT_R1-NOTICES.txt")
        with open(former, "w", encoding="utf-8") as f:
            f.write("the notices of an earlier library")
        self.assertEqual(steps.CardReader.FORMER, (os.path.basename(former),))
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll}):
            # The new name is not there yet, so the step is not done, and doing it leaves one copy: today's.
            self.assertFalse(steps.CardReader().status(None, own, None).done)
            steps.CardReader().apply(None, own, None)
        self.assertFalse(os.path.exists(former))
        with open(own.path("openDMT3-card-reader-NOTICES.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "the library's notices")
        self.assertEqual(sorted(os.listdir(own.folder)), sorted(steps.CardReader.FILES))

    def test_the_openal_mixer_goes_with_the_library_when_the_build_has_it(self):
        # DSOAL and OpenAL Soft with their notices in a build's folder: all three go beside the library at PLAY.
        folder = os.path.join(self.tmp, "openal")
        os.makedirs(folder)
        for name in native.OPENAL_FILES:
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(name)
        own = steps.Own(os.path.join(self.tmp, "own"))
        os.makedirs(own.folder)
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll, "OPENDMT3_OPENAL_DIR": folder}):
            self.assertEqual(sorted(native.openal()), sorted(native.OPENAL_FILES))
            steps.CardReader().apply(None, own, None)
            self.assertTrue(steps.CardReader().status(None, own, steps.Options()).done)
        for name in native.OPENAL_FILES:
            with open(own.path(name), encoding="utf-8") as f:
                self.assertEqual(f.read(), name)
        # Without its notices the libraries do not go at all (never one without its licences).
        os.remove(os.path.join(folder, "openal-NOTICES.txt"))
        with mock.patch.dict(os.environ, {"OPENDMT3_OPENAL_DIR": folder}):
            self.assertEqual(native.openal(), {})

    def test_the_touch_screen_library_goes_with_the_library_when_the_build_has_it(self):
        # Beside the card reader library, as build.sh makes it: in the step's files, written beside the client copy.
        touch = os.path.join(self.tmp, native.TOUCH)
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll}):
            self.assertIsNone(native.touch_library())
            self.assertNotIn(native.TOUCH, steps.CardReader()._sources())
            with open(touch, "wb") as f:
                f.write(b"MZ openDMT3 touch screen stand-in")
            self.assertEqual(native.touch_library(), touch)
            self.assertEqual(steps.CardReader()._sources()[native.TOUCH], touch)

    def test_a_library_without_notices_goes_alone(self):
        # A library a test made has none: the step still works, without them.
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll}):
            self.assertIsNone(native.notices())
            self.assertNotIn(steps.CardReader.NOTICES, steps.CardReader()._sources())

    def test_the_build_makes_them_and_keeps_them_beside_the_library(self):
        # native/cardreader/build.sh writes them beside CRT_R1.dll (notices.sh, every third-party text in full), and
        # the touch screen's library beside both ...
        with open(os.path.join(ROOT, "native", "cardreader", "build.sh"), encoding="utf-8") as f:
            build = f.read()
        self.assertIn("notices.sh /out/card-reader-NOTICES.txt", build)
        self.assertIn("-o /out/%s" % native.TOUCH, build)
        with open(os.path.join(ROOT, "native", "cardreader", "notices.sh"), encoding="utf-8") as f:
            script = f.read()
        for text in ("third_party/fsr/LICENSE.txt", "third_party/nis/LICENSE.txt", "third_party/smaa/LICENSE.txt",
                     "third_party/fxaa/NOTICE.txt", "/usr/share/doc/mingw-w64-i686-dev/copyright"):
            self.assertIn(text, script)
        # ... and the launcher's build keeps them beside it in bin/, where native.notices() finds them.
        with open(os.path.join(ROOT, "packaging", "windows", "openDMT3.spec"), encoding="utf-8") as f:
            spec = f.read()
        self.assertIn('for name in ("CRT_R1.dll", "%s", "card-reader-NOTICES.txt")' % native.TOUCH, spec)
        # The OpenAL Soft mixer's three files too, the names native.openal() looks for.
        self.assertIn("for name in (%s)]," % ", ".join('"%s"' % name for name in native.OPENAL_FILES), spec)
        self.assertEqual(native.NOTICES, "card-reader-NOTICES.txt")


if __name__ == "__main__":
    unittest.main()
