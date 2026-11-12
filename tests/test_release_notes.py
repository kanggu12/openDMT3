"""A release's notes and its one version (.github/release_notes.py): the tag, `__version__` and a CHANGELOG.md section
agree or nothing goes out, and the section is printed as the release's notes, its Security part included. The
workflows that run CI and a release's checks use every action from elsewhere by its commit."""

import contextlib
import glob
import importlib.util
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The script is no module of the package: it is loaded from its file, as the release runs it.
_SPEC = importlib.util.spec_from_file_location("release_notes", os.path.join(ROOT, ".github", "release_notes.py"))
notes = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notes)

# A changelog in the repository's own form: wrapped lines, an Unreleased part, a Security part, the next release.
CHANGELOG = """# Changelog

## [Unreleased]

### Added
- Something not released yet.

## [1.2.0] - 2026-11-12

### Added
- The first line of an item that CHANGELOG.md wraps at 120 characters, going on
  on the next line.

### Security
- An archive's entries are judged before anything is unpacked: no absolute path,
  no "..", no link.

```sh
./dmt3 test
```

## [1.1.0] - 2026-11-01

### Fixed
- An older fix.

[1.2.0]: https://example.com/compare/v1.1.0...v1.2.0
"""


def tree(folder, version="1.2.0", changelog=CHANGELOG):
    """A made-up repository: opendmt3/__init__.py with that version (None: no package) and that CHANGELOG.md."""
    root = Path(folder)
    if version is not None:
        (root / "opendmt3").mkdir()
        (root / "opendmt3" / "__init__.py").write_text('"""A package."""\n\n__version__ = "%s"\n' % version,
                                                      encoding="utf-8")
    if changelog is not None:
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


def run(*argv):
    """The script's exit code, its standard output and its standard error."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = notes.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ReleaseNotesTest(unittest.TestCase):

    def test_one_version_prints_its_section_with_the_security_part(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run("v1.2.0", "--root", str(tree(folder)))
        self.assertEqual((code, err), (0, ""))
        # The Security part is in the notes, as a heading of its own with its items.
        self.assertIn("### Security\n- An archive's entries are judged before anything is unpacked: no absolute path, "
                      "no \"..\", no link.", out)
        # A wrapped item is one line again; the code block keeps its own lines.
        self.assertIn("- The first line of an item that CHANGELOG.md wraps at 120 characters, going on on the next line.",
                      out)
        self.assertIn("```sh\n./dmt3 test\n```", out)
        # Only this release: neither what is not released yet, nor the release before, nor the link list.
        for other in ("Something not released yet", "An older fix", "example.com", "## [1.1.0]"):
            self.assertNotIn(other, out)

    def test_the_bare_number_is_the_same_as_the_tag(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(run("1.2.0", "--root", str(tree(folder)))[0], 0)

    def test_a_tag_the_code_does_not_carry_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run("v1.2.0", "--root", str(tree(folder, version="1.1.0")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("__version__ = 1.1.0: set it to 1.2.0", err)

    def test_no_notes_no_release(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run("v1.3.0", "--root", str(tree(folder, version="1.3.0")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("CHANGELOG.md has no notes for 1.3.0", err)

    def test_every_problem_is_said_at_once(self):
        with tempfile.TemporaryDirectory() as folder:
            # No package and no changelog: both are named in one run.
            code, _, err = run("v2.0.0", "--root", str(tree(folder, version=None, changelog=None)))
        self.assertEqual(code, 1)
        self.assertIn("__version__ = ?", err)
        self.assertIn("CHANGELOG.md has no notes for 2.0.0", err)

    def test_only_a_version_like_v1_2_3(self):
        with tempfile.TemporaryDirectory() as folder:
            # [Unreleased] is a section too, but never a release.
            code, _, err = run("Unreleased", "--root", str(tree(folder, version="Unreleased")))
        self.assertEqual(code, 1)
        self.assertIn("is not a version like v1.2.3", err)

    def test_this_trees_version_has_its_notes(self):
        # The version the code carries now always has its section: a release that raised it without notes, or notes
        # without the number, fails here before the release script does.
        version = notes.code_version(Path(ROOT))
        code, out, err = run("v" + version)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.strip())



class WorkflowsTest(unittest.TestCase):
    def test_every_action_from_elsewhere_is_pinned_by_its_commit(self):
        # A tag can be moved to other code after it was looked at; a commit cannot. The release it was is said beside.
        used, loose = 0, []
        for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    m = re.match(r"\s*(?:- )?uses:\s*(\S+)\s*(.*)$", line)
                    if not m or m.group(1).startswith("./"):
                        # Not a step that uses an action, or one of this repository's own workflows.
                        continue
                    used += 1
                    if not (re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1))
                            and re.fullmatch(r"# v\d+\.\d+\.\d+", m.group(2).strip())):
                        loose.append("%s:%d: %s" % (os.path.basename(path), number, line.strip()))
        self.assertEqual(loose, [], "\n".join(loose))
        # The workflows' actions were read (an instrument that read none would pass).
        self.assertGreater(used, 10)


if __name__ == "__main__":
    unittest.main()
