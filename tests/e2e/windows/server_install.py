"""The server's one-line install for Windows (packaging/server/install.ps1) as a server owner runs it, on CI's Windows
runner and nowhere else: it changes the user's PATH and folders, which a test never does on a person's PC.

    python tests/e2e/windows/server_install.py PARTS_DIR OUT_DIR      (from the repository's top, on the runner)

PARTS_DIR holds the official 7-Zip for Windows in 7zip/ (packaging/windows/sevenzip.sh, CI's native job). In OUT_DIR,
as packaging/windows/server.sh makes the Windows server package: the version file and the icon (assets.py), the
program folder (server.spec, PyInstaller with this Python), zipped under the release's name with the release's sums
beside it, and the installer with the version put in. Then, in Windows PowerShell 5.1 as `irm ... | iex` runs it (the
script's text through Invoke-Expression), from that folder of files (OPENDMT3_SERVER_FILES) into OUT_DIR's installed
folder (OPENDMT3_SERVER_DIR):
  installed with no administrator's rights, opendmt3-server by name in the same window at once, the first install's
  server started and answering /health, the owner's first-run page asked of the browser (no account yet), the program
  answering with this tree's version, its folder on the user's PATH, a new PowerShell running it by name; the owner's
  account made, start finding the server running; the install again while it runs (stopped, put in place, running
  again, the data kept); a later release whose zip is not the one its sums name (refused, the server running on); the
  removal (the program and its PATH entry gone, the window's too, the server stopped, the data kept).
Each step says PASS or FAIL; the exit code is the number of steps that failed. Nothing here opens a window: the
server's program is a console one, run with its output read, and the browser is a recorder in BROWSER's place
(Python's webbrowser takes it first), which keeps the page it is asked for.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

# The repository's top: this file is in tests/e2e/windows/.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from opendmt3 import __version__  # noqa: E402

# Each step's time limit: PyInstaller takes a few minutes, an install or a start some seconds.
BUILD_SECONDS = 1200
RUN_SECONDS = 300


def step(name, ok, detail=""):
    """One step's line; returns 0 when it held, 1 when it did not."""
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (": " + detail) if detail else ""), flush=True)
    return 0 if ok else 1


def run(cmd, seconds, env=None):
    """A command from the repository's top: (exit code, its output and errors together)."""
    try:
        done = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=seconds, text=True, encoding="utf-8", errors="replace")
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else ""


def powershell(script, env, then=""):
    """Windows PowerShell 5.1 (every Windows 10 and 11 has it) running a script's text as iex runs a downloaded one;
    then, when given, more commands in the same window, as the person's next ones there."""
    command = "Get-Content -Raw -LiteralPath '%s' | Invoke-Expression" % script.replace("'", "''")
    if then:
        command += "; " + then
    return run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], RUN_SECONDS, env)


def recorder(out):
    """A browser in BROWSER's place: a batch file that keeps the address it is given in a file (returned with it), so
    no window opens. Python's webbrowser runs it with the address as its one argument and waits for it."""
    asked = os.path.join(out, "browser-asked.txt")
    path = os.path.join(out, "browser.cmd")
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write('@echo off\n>"%s" echo %%~1\n' % asked)
    return path, asked


def user_path():
    """The user's PATH as Windows keeps it (what a new terminal gets), read from the registry."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            return winreg.QueryValueEx(key, "Path")[0]
        except FileNotFoundError:
            return ""


def health(port=4730):
    """The site's /health answer, or None when nothing answers."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as answer:
            return answer.read().decode("utf-8")
    except OSError:
        return None


def package(out, parts):
    """The Windows server package of this tree, as server.sh makes it (its program folder zipped under one folder of
    the release's name), in a folder of release files with their sums and the installer: (the files' folder, the
    number of steps that failed)."""
    failed = 0
    assets = os.path.join(out, "assets")
    code, said = run([sys.executable, os.path.join("packaging", "windows", "assets.py"), assets, __version__],
                     RUN_SECONDS)
    failed += step("the icon and the version file", code == 0 and os.path.isfile(
        os.path.join(assets, "server-version.txt")), said.strip()[-400:])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENDMT3_BUILD_DIR=assets,
               OPENDMT3_7ZIP_DIR=os.path.join(parts, "7zip"))
    dist = os.path.join(out, "dist")
    code, said = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--distpath", dist,
                      "--workpath", os.path.join(out, "work"), os.path.join("packaging", "windows", "server.spec")],
                     BUILD_SECONDS, env)
    program = os.path.join(dist, "opendmt3-server")
    failed += step("PyInstaller made opendmt3-server.exe", code == 0 and os.path.isfile(
        os.path.join(program, "opendmt3-server.exe")), said.strip()[-1200:])
    files = os.path.join(out, "files")
    os.makedirs(files)
    name = "opendmt3-server-%s-windows-x64" % __version__
    archive = os.path.join(files, name + ".zip")
    # One folder of the package's name, as the release's zip holds it.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for top, dirs, names in os.walk(program):
            dirs.sort()
            for each in sorted(names):
                path = os.path.join(top, each)
                zf.write(path, os.path.join(name, os.path.relpath(path, program)))
    sums(files, __version__, [name + ".zip"])
    installer(files, __version__)
    return files, failed


def sums(files, version, names, wrong=()):
    """The release's SHA-256 sums over the files named (those in `wrong` given a sum that is not theirs)."""
    import hashlib
    lines = []
    for name in names:
        with open(os.path.join(files, name), "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        lines.append("%s  %s" % ("0" * 64 if name in wrong else digest, name))
    with open(os.path.join(files, "opendmt3-%s-sha256sums.txt" % version), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def installer(files, version):
    """The release's windows-installer.ps1 for `version`, as release_files.py writes it; returns its path."""
    with open(os.path.join(ROOT, "packaging", "server", "install.ps1"), encoding="utf-8") as f:
        text = f.read().replace("@VERSION@", version)
    path = os.path.join(files, "opendmt3-server-%s-windows-installer.ps1" % version)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def under_wine():
    """True under Wine (its ntdll has a function of Wine's own), where the job runs on a Linux PC (_work's ci_local)."""
    try:
        import ctypes
        return hasattr(ctypes.WinDLL("ntdll"), "wine_get_version")
    except (OSError, AttributeError):
        return False


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[3].strip())
        return 2
    if os.name == "nt" and under_wine():
        # Wine has no Windows PowerShell to run the installer in: the runner's Windows does it.
        print("SKIP the server's one-line install for Windows: Windows PowerShell 5.1 runs it on CI's Windows runner")
        return 0
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        # It puts a folder on this user's PATH and a program in their folders: CI's runner is made for it, a person's
        # PC is not.
        print("runs on CI's Windows runner only: it changes this user's PATH and folders")
        return 2
    parts, out = (os.path.abspath(a) for a in argv)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    files, failed = package(out, parts)
    installed = os.path.join(out, "installed")
    exe = os.path.join(installed, "opendmt3-server.exe")
    browser, asked = recorder(out)
    env = dict(os.environ, OPENDMT3_SERVER_FILES=files, OPENDMT3_SERVER_DIR=installed, BROWSER=browser)
    env.pop("OPENDMT3_SERVER_UNINSTALL", None)
    script = os.path.join(files, "opendmt3-server-%s-windows-installer.ps1" % __version__)

    # The person's next command in the same window: the program by name, its folder on this window's PATH at once.
    code, said = powershell(script, env, then="Write-Output 'by name here:'; opendmt3-server --version")
    failed += step("the one line installs the server, with no administrator's rights",
                   code == 0 and os.path.isfile(exe), said.strip()[-1200:])
    failed += step("opendmt3-server by name in the same window, at once",
                   "by name here:\nopenDMT3 server " + __version__ in said, said.strip()[-400:])
    answer = health()
    failed += step("a first install starts the server, answering /health", answer is not None and
                   '"version":"%s"' % __version__ in answer, (answer or said).strip()[-400:])
    try:
        with open(asked, encoding="ascii", errors="replace") as f:
            page = f.read().strip()
    except OSError:
        page = ""
    failed += step("with no account yet, the browser asked for the owner's first-run page on this PC",
                   page == "http://127.0.0.1:4731/", page or "nothing asked of the browser")
    code, said = run([exe, "--version"], RUN_SECONDS)
    failed += step("opendmt3-server --version", code == 0 and said.strip() == "openDMT3 server " + __version__,
                   said.strip())
    entries = [os.path.normcase(os.path.expandvars(e)).rstrip("\\") for e in user_path().split(";") if e]
    failed += step("its folder on the user's PATH", os.path.normcase(installed) in entries)
    # A new PowerShell, its PATH as Windows gives a new terminal (the user's and the machine's), runs it by name.
    by_name = ("$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + "
               "[Environment]::GetEnvironmentVariable('Path', 'Machine'); opendmt3-server --version")
    code, said = run(["powershell.exe", "-NoProfile", "-Command", by_name], RUN_SECONDS)
    failed += step("a new PowerShell runs opendmt3-server by name", code == 0 and "openDMT3 server " + __version__ in
                   said, said.strip())
    code, said = run([exe, "setup", "--admin", "BOSS", "--password", "pass1234"], RUN_SECONDS)
    failed += step("setup makes the owner's account", code == 0 and "made BOSS" in said, said.strip()[-400:])
    code, said = run([exe, "start"], RUN_SECONDS)
    answer = health()
    failed += step("start finds it running, answering /health", code == 0 and "already runs" in said and
                   answer is not None and '"version":"%s"' % __version__ in answer, (answer or said).strip()[-400:])

    code, said = powershell(script, env)
    status, told = run([exe, "status"], RUN_SECONDS)
    data = os.path.join(installed, "data", "openDMT3.sqlite")
    failed += step("the install again while it runs: stopped, put in place, running again, the data kept",
                   code == 0 and status == 0 and os.path.isfile(data), (said + told).strip()[-1200:])

    # A later release whose zip is not the one its sums name: refused before anything is stopped.
    later = __version__ + "9"
    name = "opendmt3-server-%s-windows-x64.zip" % later
    shutil.copyfile(os.path.join(files, "opendmt3-server-%s-windows-x64.zip" % __version__), os.path.join(files, name))
    sums(files, later, [name], wrong=[name])
    code, said = powershell(installer(files, later), env)
    status, _ = run([exe, "status"], RUN_SECONDS)
    _, version = run([exe, "--version"], RUN_SECONDS)
    failed += step("a later release whose zip is not the release's: refused, the server running on",
                   code != 0 and status == 0 and "is not the release's" in said
                   and version.strip() == "openDMT3 server " + __version__, said.strip()[-400:])

    remove = dict(env, OPENDMT3_SERVER_UNINSTALL="1")
    # The window's own PATH after the removal, as the person's next command there would see it.
    here = ("Write-Output ('this window: ' + [string]@($env:Path -split ';' | Where-Object { $_.TrimEnd('\\') -eq '%s' "
            "}).Count)" % installed.replace("'", "''"))
    code, said = powershell(script, remove, then=here)
    # The server has let go of its port by the time the removal ends; a moment for the socket to close.
    time.sleep(2)
    entries = [os.path.normcase(os.path.expandvars(e)).rstrip("\\") for e in user_path().split(";") if e]
    failed += step("removed: the program and its PATH entry gone, the window's too, the server stopped, the data kept",
                   code == 0 and not os.path.exists(exe) and os.path.isfile(data) and health() is None
                   and os.path.normcase(installed) not in entries and "this window: 0" in said, said.strip()[-1200:])
    print("%d steps failed" % failed if failed else "every step passed", flush=True)
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
