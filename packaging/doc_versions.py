"""The version the guides' download lines name, against the one the code carries.

    python3 packaging/doc_versions.py [--write] [--root DIR]

The README and the guides name a release's files by their versioned names (opendmt3-launcher-1.2.3-windows-x64-
setup.exe, opendmt3-server-1.2.3-linux-macos.zip) and download them from that release's own address
(releases/download/v1.2.3/), so a line copied from them fetches the file it names; compose.yaml's default image and
the Helm chart's Chart.yaml are read the same way. Every such version must be `__version__` (opendmt3/__init__.py);
so must the bug form's example version. Lists each line that names another and exits 1; --write puts this version in
their place (a release raises the version, then runs this with --write). The standard library only, as
.github/release_notes.py.
"""

import argparse
import re
import sys
from pathlib import Path

# The repository: this file is in packaging/.
ROOT = Path(__file__).resolve().parent.parent
# A version as release files carry it: a pre-release only as rc.N, alpha.N or beta.N, so the part of a name after the
# version (-windows-x64) is never read as one.
V = r"\d+\.\d+\.\d+(?:-(?:rc|alpha|beta)\.\d+)?"
# Where a version is part of a download: a release file's name, a release's download address, the bug form's example.
# The launcher's files (its installer, the OpenAL sources: opendmt3-launcher-1.2.3-openal-sources.zip).
PATTERNS = [re.compile(r"(?<=opendmt3-launcher-)" + V + r"(?=-)"),
            # The server's: its packages, installers and Helm chart (opendmt3-server-1.2.3-helm-chart.tgz), also at a
            # line's end or before a space (the folder `cd opendmt3-server-1.2.3-linux-macos` goes into after
            # unzipping).
            re.compile(r"(?<=opendmt3-server-)" + V + r"(?![\w])"),
            re.compile(r"(?<=/releases/download/v)" + V + r"(?=/)"),
            # The SHA-256 sums' name (opendmt3-1.2.3-sha256sums.txt), and the server's image tag.
            re.compile(r"(?<=opendmt3-)" + V + r"(?=-sha256sums)"),
            re.compile(r"(?<=opendmt3-server:)" + V + r"\b"),
            # The Helm chart's own version and the server's in its Chart.yaml.
            re.compile(r"(?<=^version: )" + V + r"$", re.M), re.compile(r"(?<=^appVersion: \")" + V + r"(?=\")", re.M),
            re.compile(r"(?<=placeholder: )" + V + r"$", re.M)]
# The pages people copy download lines from (CHANGELOG.md keeps each release's own names, so it is not one).
PAGES = ["README.md", "CONTRIBUTING.md", "packaging/server/README.md", ".github/ISSUE_TEMPLATE/bug.yml",
         # The image compose.yaml runs by default, and the Helm chart's versions: a release moves them with the guides.
         "compose.yaml", "deploy/helm/opendmt3/Chart.yaml"]


def pages(root):
    """Every page checked, as paths from the tree's top: the fixed ones and every guide in docs/."""
    return PAGES + sorted("docs/" + p.name for p in (root / "docs").glob("*.md"))


def code_version(root):
    """`__version__` as opendmt3/__init__.py writes it (the line build.sh reads too)."""
    text = (root / "opendmt3" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]*)"', text, re.M).group(1)


def stale(root, version):
    """Each place that names another version, as (page, line number, the version there)."""
    found = []
    for page in pages(root):
        path = root / page
        if not path.is_file():
            # A page the tree does not have (a test's own tree): nothing to check there.
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in PATTERNS:
                found += [(page, number, m.group(0)) for m in pattern.finditer(line) if m.group(0) != version]
    return found


def write(root, version):
    """Puts the version in every place that names another; returns how many pages changed."""
    changed = 0
    for page in pages(root):
        path = root / page
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        new = text
        for pattern in PATTERNS:
            new = pattern.sub(version, new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="put the code's version in every place")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree to read (the tests give their own)")
    args = parser.parse_args(argv)
    version = code_version(args.root)
    if args.write:
        print("%d pages now name %s" % (write(args.root, version), version))
        return 0
    found = stale(args.root, version)
    for page, number, other in found:
        print("%s:%d names %s, the code is %s (packaging/doc_versions.py --write)" % (page, number, other, version),
              file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
