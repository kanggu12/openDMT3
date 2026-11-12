"""The package's parts keep their direction: opendmt3.core imports nothing of the server or the client, and
opendmt3.server imports nothing of the client. Read from the source with ast, so an import inside a function, which
a test run might never reach, counts too."""

import ast
import os
import unittest

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# OPENDMT3_REPO points the scan at another copy of the tree (the check itself is tried on a copy with a planted fault).
REPO = os.environ.get("OPENDMT3_REPO") or ROOT
# Each part and the parts it must never import.
FORBIDDEN = {
    "opendmt3.core": ("opendmt3.server", "opendmt3.client"),
    "opendmt3.server": ("opendmt3.client",),
}
# The three parts every module but the package's own top files belongs to.
PARTS = ("opendmt3.core", "opendmt3.server", "opendmt3.client")


def modules(repo):
    """Every module of the package as (dotted name, path, is a package's __init__), from its files on disk."""
    found = []
    base = os.path.join(repo, "opendmt3")
    for folder, dirs, files in os.walk(base):
        # Compiled copies are not source; sorted so a failure lists the same order every run.
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            # The dotted name from the path below the repository: opendmt3/server/web/app.py -> opendmt3.server.web.app.
            parts = os.path.relpath(path, repo)[:-3].split(os.sep)
            is_package = parts[-1] == "__init__"
            if is_package:
                # A package's __init__ is the package itself.
                parts = parts[:-1]
            found.append((".".join(parts), path, is_package))
    return found


def imported(name, path, is_package):
    """Every module a file imports, as absolute dotted names, with the line of each import."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    # The package a relative import starts from: the module's own for an __init__, else its parent's.
    package = name if is_package else name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # from . import x / from ..y import z: climb one package per dot beyond the first.
                base = package.split(".")
                base = base[:len(base) - (node.level - 1)]
                start = ".".join(base + ([node.module] if node.module else []))
            else:
                start = node.module
            yield start, node.lineno
            # from opendmt3 import server: each name may be a module of its own, so it counts as start.name too.
            for alias in node.names:
                yield "%s.%s" % (start, alias.name), node.lineno


def within(module, part):
    """True when the dotted module is the part itself or below it."""
    return module == part or module.startswith(part + ".")


def violations(repo):
    """Every import that runs against the direction, as readable lines; and how many modules were read."""
    found = []
    mods = modules(repo)
    for name, path, is_package in mods:
        for part, banned in FORBIDDEN.items():
            if not within(name, part):
                continue
            # One line per import statement: `from opendmt3.client import theme` yields both the package and the name.
            reported = set()
            for target, line in imported(name, path, is_package):
                for other in banned:
                    if within(target, other) and line not in reported:
                        reported.add(line)
                        found.append("%s:%d %s imports %s" % (os.path.relpath(path, repo), line, part, target))
    return found, len(mods)


class ArchitectureTest(unittest.TestCase):
    def test_core_and_server_never_import_what_depends_on_them(self):
        found, read = violations(REPO)
        # The package has over eighty modules; a scan that read a handful would pass on nothing.
        self.assertGreater(read, 80)
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_every_module_is_in_one_of_the_three_parts(self):
        # Only the package's own top files (the version, python -m opendmt3) sit outside the parts.
        loose = [name for name, _, _ in modules(REPO)
                 if name not in ("opendmt3", "opendmt3.__main__") and not any(within(name, p) for p in PARTS)]
        self.assertEqual(loose, [])

    def test_a_relative_import_is_read_from_its_own_package(self):
        # The resolution the scan relies on, on a made-up module: `from .. import x` in opendmt3/core/cabinet/a.py
        # means opendmt3.core.x, and `from . import y` in a package's __init__ means that package's y.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("from .. import x\nfrom .y import z\n")
            got = {t for t, _ in imported("opendmt3.core.cabinet.a", path, False)}
            self.assertIn("opendmt3.core.x", got)
            self.assertIn("opendmt3.core.cabinet.y.z", got)
            got = {t for t, _ in imported("opendmt3.server", path, True)}
            self.assertIn("opendmt3.x", got)
            self.assertIn("opendmt3.server.y", got)


if __name__ == "__main__":
    unittest.main()
