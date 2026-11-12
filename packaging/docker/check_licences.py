"""The licence texts the server's image keeps beside its parts, checked in the image itself (CI's server job):

    docker run --rm -v "$PWD/packaging/docker:/check:ro" --entrypoint python IMAGE -I /check/check_licences.py

Python's own LICENSE.txt; each installed Python package's licence files, as its metadata names them; each system
package's copyright file (Debian keeps one for every package in /usr/share/doc); 7-Zip's License.txt beside its
program; and openDMT3's own LICENSE beside the package. Prints one line a part with where its text is, and exits 1
naming each part whose text is not in the image. The standard library only: it runs on the image's own Python.
"""

import importlib.metadata
import importlib.util
import os
import platform
import subprocess
import sys
import sysconfig

# 7-Zip in the image (packaging/docker/Dockerfile), and where its licence stays with it.
SEVENZIP = "/usr/local/bin/7zz"
SEVENZIP_LICENCE = "/usr/local/share/doc/7-zip/License.txt"


def licence_paths(dist):
    """Where a package's licence files are, as its metadata names them (PEP 639's .dist-info/licenses/ first, then
    beside METADATA as older tools put them); the ones not there are left out."""
    paths = []
    records = {str(f).replace("\\", "/"): f for f in dist.files or []}
    for name in dist.metadata.get_all("License-File") or []:
        for record, entry in records.items():
            # The RECORD line of that file inside the package's .dist-info folder.
            if ".dist-info/" in record and record.split(".dist-info/", 1)[1] in ("licenses/" + name, name):
                path = str(entry.locate())
                if os.path.isfile(path):
                    paths.append(path)
                break
    return paths


def system_packages():
    """Every package dpkg installed, by name (an image that is no Debian has none to check)."""
    try:
        done = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\n"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(set(done.stdout.split()))


def check():
    """(part, where its text is) for every part, and the parts whose text is missing."""
    found, missing = [], []

    def part(name, path):
        (found if path and os.path.isfile(path) else missing).append((name, path or "no licence file named"))

    # Python itself: its LICENSE.txt is in the standard library's folder.
    part("Python %s" % platform.python_version(), os.path.join(sysconfig.get_paths()["stdlib"], "LICENSE.txt"))
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        paths = licence_paths(dist)
        name = "%s %s" % (dist.metadata["Name"], dist.version)
        if paths:
            for path in paths:
                part(name, path)
        else:
            part(name, None)
    for package in system_packages():
        part("system package " + package, "/usr/share/doc/%s/copyright" % package)
    if os.path.exists(SEVENZIP):
        part("7-Zip (%s)" % SEVENZIP, SEVENZIP_LICENCE)
    # openDMT3's package where the server runs it from: the image's working folder (/app, where the Dockerfile puts
    # LICENSE beside it), as python -I leaves it off the import path; else wherever this Python imports it from.
    spec = importlib.util.find_spec("opendmt3")
    here = os.path.join(os.getcwd(), "opendmt3")
    folder = os.path.dirname(here) if os.path.isdir(here) else (
        os.path.dirname(os.path.dirname(spec.origin)) if spec and spec.origin else None)
    part("openDMT3", os.path.join(folder, "LICENSE") if folder else None)
    return found, missing


def main():
    found, missing = check()
    for name, path in found:
        print("ok      %s: %s" % (name, path))
    for name, path in missing:
        print("MISSING %s: %s" % (name, path))
    print("%d texts found, %d missing" % (len(found), len(missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
