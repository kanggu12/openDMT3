"""A release's notes and its one version, before anything is built or published.

    python3 .github/release_notes.py v1.2.3 [--root DIR]

Checks that the tag, `__version__` in opendmt3/__init__.py and a section of CHANGELOG.md all name the same version,
then prints that section, each paragraph and list item on one line, which packaging/release.sh publishes as the
release's notes (its `### Security` part included). Exits 1, saying what differs or what is missing: a release
does not go out under a number the code does not carry, or without notes. The standard library only: it runs on any
Python 3, the release machine's own or a runner's, before anything is installed.
"""
import argparse
import re
import sys
from pathlib import Path

# The repository: this file is in .github/.
ROOT = Path(__file__).resolve().parent.parent
# MAJOR.MINOR.PATCH, with an optional pre-release part, as semver.org writes it.
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?")
# The one place the version is written (CONTRIBUTING.md): build.sh reads it with the same pattern.
VERSION_LINE = re.compile(r'^__version__ = "([^"]*)"\s*$', re.M)


def code_version(root):
    """`__version__` as opendmt3/__init__.py writes it, or "" when the file or the line is not there."""
    try:
        text = (root / "opendmt3" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        # No package in that tree: the check below says so with the number it wanted.
        return ""
    found = VERSION_LINE.search(text)
    # The line build.sh and the release script read the version from too.
    return found.group(1) if found else ""


def section(text, version):
    """The body under `## [version]`, up to the next `## [` heading or the link list at the end; None if absent."""
    found = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)", text, re.S | re.M)
    # Blank lines around the body are no part of the notes.
    return found.group(1).strip() if found else None


# A line that starts a block of its own: a heading, a list item, a quote or a table row.
BLOCK_START = re.compile(r"\s*(#|[-*>|] |\d+\. )")


def unwrap(body):
    """The section with each paragraph and list item on one line. CHANGELOG.md wraps its lines at 120 characters, and a
    GitHub release shows every line break as it is, in the middle of a sentence; code blocks keep theirs."""
    lines = []
    # Inside a fenced code block nothing is joined.
    fenced = False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            # A fence opens or closes a code block, and stays a line of its own.
            fenced = not fenced
            lines.append(line)
            continue
        previous = lines[-1] if lines else ""
        # Joined to the line before: text that goes on from a paragraph or a list item, outside a code block (a
        # heading, a table row and a fence end their line).
        if (not fenced and line.strip() and not BLOCK_START.match(line) and previous.strip()
                and not previous.lstrip().startswith(("#", "|", "```"))):
            lines[-1] = previous.rstrip() + " " + line.strip()
        else:
            lines.append(line)
    return "\n".join(lines)


def problems_with(tag, root):
    """What stops a release under this tag, as sentences (none: it may go), and the notes when there are any."""
    # The tag's name or the bare number: the number is what every file carries.
    version = tag[1:] if tag.startswith("v") else tag
    problems = []
    if not SEMVER.fullmatch(version):
        problems.append(f"{tag} is not a version like v1.2.3")
    code = code_version(root)
    # The launcher, the installer, the server and the update packages all carry this number (build.sh reads it).
    if code != version:
        problems.append(f"opendmt3/__init__.py says __version__ = {code or '?'}: set it to {version}")
    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        # No changelog is the same as no section: there are no notes.
        changelog = ""
    body = section(changelog, version)
    if not body:
        problems.append(f"CHANGELOG.md has no notes for {version}: add a '## [{version}] - YYYY-MM-DD' section")
    return problems, body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the release's tag, v1.2.3, or the bare number")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (the tests give their own)")
    args = parser.parse_args(argv)
    problems, body = problems_with(args.tag, args.root)
    if problems:
        # Every problem at once, so one run says everything to fix.
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    # The notes themselves, on standard output alone, ready for --notes-file.
    print(unwrap(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
