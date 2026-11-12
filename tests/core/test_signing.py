"""Tests for the signature on update packages (opendmt3/core/signing.py): Ed25519 against RFC 8032's own vectors,
what the signature of a package's bytes and the signature of its files each cover, which keys a launcher takes, and the
command line a build signs and checks with.

Every key here is made by the test (a fixed seed, or new-key into a temporary folder). The project's own key is never
read: the tests swap signing.KEYS for the test's public key where a check must pass.
"""

import contextlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
import warnings
import zipfile
from unittest import mock

from opendmt3.core import signing

# RFC 8032, section 7.1, TEST 1 to 3: (secret key, public key, message, signature), in hex as printed there.
RFC_8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]
# The order of Ed25519's base point: a signature's s plus it is another spelling of the same signature.
ORDER = 2 ** 252 + 27742317777372353535851937790883648493
# The test's own key, and a stranger's.
SEED, STRANGER = bytes(range(32)), bytes(range(1, 33))
NAME = "openDMT3-9.9.9-full.nupkg"
# A package's files, small: the manifest, the program, one more.
FILES = [("openDMT3.nuspec", b"<package/>"), ("lib/app/openDMT3.exe", b"MZ the program"), ("lib/app/x.txt", b"x")]


def flipped(hex_text, at=0):
    """A hex string with one bit of the byte at `at` flipped."""
    data = bytearray(bytes.fromhex(hex_text))
    data[at] ^= 1
    return data.hex()


class SigningCase(unittest.TestCase):
    """A temporary folder, and the test's public key as the one a launcher takes."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        keys = mock.patch.object(signing, "KEYS", (signing.public_key(SEED).hex(),))
        keys.start()
        self.addCleanup(keys.stop)

    def package(self, entries=FILES, name=NAME, method=zipfile.ZIP_DEFLATED):
        """A package of these entries, in their order; returns its path."""
        path = os.path.join(self.folder, name)
        with warnings.catch_warnings():
            # zipfile warns when a name is written twice: that is the case a test looks at.
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "w", method) as z:
                for entry, data in entries:
                    z.writestr(entry, data)
        return path

    def sig(self, path, seed=SEED, **changed):
        """The package's .sig as a launcher fetches it (bytes), with fields changed when a test says so."""
        return json.dumps(dict(signing.sign_package(seed, path), **changed)).encode("utf-8")


class Ed25519Test(unittest.TestCase):

    def test_ed25519_is_rfc_8032s(self):
        for number, (secret, public, message, signature) in enumerate(RFC_8032, 1):
            with self.subTest(vector=number):
                seed, pub, msg, sig = (bytes.fromhex(v) for v in (secret, public, message, signature))
                self.assertEqual(signing.public_key(seed), pub)
                self.assertEqual(signing.sign(seed, msg), sig)
                self.assertTrue(signing.verify(pub, msg, sig))

    def test_a_signature_of_something_else_never_verifies(self):
        for number, (_, public, message, signature) in enumerate(RFC_8032, 1):
            pub, msg, sig = (bytes.fromhex(v) for v in (public, message, signature))
            # s with the group order added: the same signature spelled another way, which a launcher takes for none.
            other_spelling = sig[:32] + (int.from_bytes(sig[32:], "little") + ORDER).to_bytes(32, "little")
            refused = {
                "another message": (pub, msg + b"x", sig),
                "a bit of R flipped": (pub, msg, bytes([sig[0] ^ 1]) + sig[1:]),
                "a bit of s flipped": (pub, msg, sig[:32] + bytes([sig[32] ^ 1]) + sig[33:]),
                "another key": (bytes.fromhex(RFC_8032[number % 3][1]), msg, sig),
                "s plus the order": (pub, msg, other_spelling),
                "a signature cut short": (pub, msg, sig[:63]),
                "a key cut short": (pub[:31], msg, sig),
                "no signature": (pub, msg, b""),
            }
            for what, (key, text, signed) in refused.items():
                with self.subTest(vector=number, what=what):
                    self.assertFalse(signing.verify(key, text, signed))


class PackageSignatureTest(SigningCase):

    def test_both_signatures_of_a_package_check_out(self):
        path = self.package()
        sig = self.sig(path)
        self.assertTrue(signing.checks_out(sig, path, NAME))
        self.assertTrue(signing.content_checks_out(sig, path, NAME))
        # What a .sig says: the two hashes, the key, the two signatures.
        said = json.loads(sig)
        self.assertEqual(sorted(said), ["content", "content_signature", "file", "format", "key", "sha256", "signature"])
        self.assertEqual(said["sha256"], signing.sha256_of(path))
        self.assertEqual(said["content"], signing.content_sha256(path))

    def test_a_signature_that_is_not_the_keys_own_is_refused_with_everything_else_right(self):
        path = self.package()
        good = signing.sign_package(SEED, path)
        # The project's key named, the hashes right, and a signature that key never made: one bit off, a stranger's
        # under the project's key, the other signature of the same .sig.
        strangers = signing.sign_package(STRANGER, path)
        for what, field, value in (
                ("a bit of the signature flipped", "signature", flipped(good["signature"])),
                ("its last byte flipped", "signature", flipped(good["signature"], 63)),
                ("a stranger's signature under the project's key", "signature", strangers["signature"]),
                ("the files' signature in its place", "signature", good["content_signature"])):
            with self.subTest(what=what):
                self.assertFalse(signing.checks_out(self.sig(path, **{field: value}), path, NAME))
        for what, field, value in (
                ("a bit of the signature flipped", "content_signature", flipped(good["content_signature"])),
                ("its last byte flipped", "content_signature", flipped(good["content_signature"], 63)),
                ("a stranger's signature under the project's key", "content_signature",
                 strangers["content_signature"]),
                ("the bytes' signature in its place", "content_signature", good["signature"])):
            with self.subTest(what=what):
                self.assertFalse(signing.content_checks_out(self.sig(path, **{field: value}), path, NAME))

    def test_only_a_key_the_launcher_takes_signs_for_it(self):
        path = self.package()
        # A stranger's whole .sig, right in itself: its key is not one built in.
        strangers = self.sig(path, seed=STRANGER)
        self.assertFalse(signing.checks_out(strangers, path, NAME))
        self.assertFalse(signing.content_checks_out(strangers, path, NAME))
        # The same .sig checked against the stranger's key passes: it was the key, nothing else.
        key = (signing.public_key(STRANGER).hex(),)
        self.assertTrue(signing.checks_out(strangers, path, NAME, key))
        self.assertTrue(signing.content_checks_out(strangers, path, NAME, key))
        # A key that is no key at all.
        for junk in ("", "zz", "00" * 31):
            self.assertFalse(signing.checks_out(self.sig(path, key=junk), path, NAME))
            self.assertFalse(signing.content_checks_out(self.sig(path, key=junk), path, NAME))

    def test_a_signature_is_for_one_file_name(self):
        path = self.package()
        sig = self.sig(path)
        other = "openDMT3-1.0.0-full.nupkg"
        # Asked about under another name (an older package offered as a newer one), and a .sig that names another.
        self.assertFalse(signing.checks_out(sig, path, other))
        self.assertFalse(signing.content_checks_out(sig, path, other))
        self.assertFalse(signing.checks_out(self.sig(path, file=other), path, NAME))
        self.assertFalse(signing.content_checks_out(self.sig(path, file=other), path, NAME))
        # And one that names the name asked for, signed for the other: the name is in what was signed.
        self.assertFalse(signing.checks_out(self.sig(path, file=other), path, other))
        self.assertFalse(signing.content_checks_out(self.sig(path, file=other), path, other))

    def test_the_bytes_signature_is_for_those_bytes(self):
        path = self.package()
        sig = self.sig(path)
        # The same files zipped again are other bytes.
        again = self.package(list(reversed(FILES)))
        self.assertNotEqual(json.loads(sig)["sha256"], signing.sha256_of(again))
        self.assertFalse(signing.checks_out(sig, again, NAME))
        # A hash in the .sig that is the file's, with the signature of the other hash.
        self.assertFalse(signing.checks_out(self.sig(again, signature=json.loads(sig)["signature"]), again, NAME))

    def test_the_files_signature_covers_every_files_name_and_contents(self):
        path = self.package()
        sig, reference = self.sig(path), signing.content_sha256(path)
        same = {
            "the same files in another order": list(reversed(FILES)),
            "a folder's own entry beside them": FILES + [("lib/app/", b"")],
            "a name spelled with backslashes": [(name.replace("/", "\\"), data) for name, data in FILES],
        }
        other = {
            "a file's contents changed": FILES[:2] + [("lib/app/x.txt", b"y")],
            "a file added": FILES + [("lib/app/new.dll", b"new")],
            "an empty file added": FILES + [("lib/app/empty", b"")],
            "a file left out": FILES[:2],
            "a file under another name, the same contents": FILES[:2] + [("lib/app/y.txt", b"x")],
            "a file in another folder, the same contents": FILES[:2] + [("lib/other/x.txt", b"x")],
            "two files' names swapped": [FILES[0], ("lib/app/x.txt", b"MZ the program"),
                                         ("lib/app/openDMT3.exe", b"x")],
            "a name in another case": FILES[:2] + [("lib/app/X.txt", b"x")],
            "a name listed twice, the same contents": FILES + [("lib/app/x.txt", b"x")],
            "a name listed twice, other contents after": FILES + [("lib/app/x.txt", b"y")],
            "a name listed twice, other contents before": FILES[:2] + [("lib/app/x.txt", b"y"),
                                                                       ("lib/app/x.txt", b"x")],
        }
        for what, entries in same.items():
            with self.subTest(what=what):
                again = self.package(entries)
                self.assertEqual(signing.content_sha256(again), reference)
                self.assertTrue(signing.content_checks_out(sig, again, NAME))
        for what, entries in other.items():
            with self.subTest(what=what):
                again = self.package(entries)
                self.assertNotEqual(signing.content_sha256(again), reference)
                self.assertFalse(signing.content_checks_out(sig, again, NAME))
        # Stored instead of deflated: the same files.
        self.assertEqual(signing.content_sha256(self.package(method=zipfile.ZIP_STORED)), reference)

    def test_what_is_no_zip_has_no_files_to_sign(self):
        path = self.package()
        sig = self.sig(path)
        with open(path, "rb") as f:
            whole = f.read()
        for what, data in (("not a zip", b"PK not a zip"), ("a zip cut in half", whole[:len(whole) // 2]),
                           ("nothing", b"")):
            with self.subTest(what=what):
                with open(path, "wb") as f:
                    f.write(data)
                self.assertIsNone(signing.content_sha256(path))
                self.assertFalse(signing.content_checks_out(sig, path, NAME))
        # A package that is no zip is signed by its bytes alone (no files' signature in its .sig).
        with open(path, "wb") as f:
            f.write(b"PK not a zip")
        alone = signing.sign_package(SEED, path)
        self.assertEqual(sorted(alone), ["file", "format", "key", "sha256", "signature"])
        self.assertTrue(signing.checks_out(json.dumps(alone).encode(), path, NAME))
        self.assertFalse(signing.content_checks_out(json.dumps(alone).encode(), path, NAME))

    def test_what_is_no_signature_file_is_refused(self):
        path = self.package()
        good = signing.sign_package(SEED, path)
        cases = {
            "not JSON": b"not json",
            "not text": b"\xff\xfe\x00",
            "a list": json.dumps([good]).encode(),
            "another format": json.dumps(dict(good, format=2)).encode(),
            "no key": json.dumps({k: v for k, v in good.items() if k != "key"}).encode(),
            "a number for the key": json.dumps(dict(good, key=7)).encode(),
            "longer than any .sig": json.dumps(dict(good, padding="x" * signing.SIG_LIMIT)).encode(),
            "nothing": b"",
        }
        for what, sig in cases.items():
            with self.subTest(what=what):
                self.assertFalse(signing.checks_out(sig, path, NAME))
                self.assertFalse(signing.content_checks_out(sig, path, NAME))
        # Each signature needs its own fields: without the one, the other still checks out.
        bytes_only = json.dumps({k: v for k, v in good.items() if not k.startswith("content")}).encode()
        self.assertTrue(signing.checks_out(bytes_only, path, NAME))
        self.assertFalse(signing.content_checks_out(bytes_only, path, NAME))
        files_only = json.dumps({k: v for k, v in good.items() if k not in ("sha256", "signature")}).encode()
        self.assertFalse(signing.checks_out(files_only, path, NAME))
        self.assertTrue(signing.content_checks_out(files_only, path, NAME))


class KeysTest(SigningCase):

    def test_a_test_builds_key_is_taken_beside_the_projects(self):
        # A copy of the repository has no such file: only a build given a test's key writes one.
        self.assertFalse(os.path.exists(signing.TEST_KEYS_FILE))
        self.assertEqual(signing.added_keys(), ())
        self.assertEqual(signing.trusted(), signing.KEYS)
        path = self.package()
        strangers = self.sig(path, seed=STRANGER)
        written = os.path.join(self.folder, "update-test-keys.txt")
        key = signing.public_key(STRANGER).hex()
        for text, keys in (("", ()),                                           # a release's file
                           (key + "\n", (key,)),                               # a test build's
                           (key.upper(), (key,)),                              # no newline, capitals
                           ("not a key\n%s\n%s\n\n" % (key[:63], key), (key,)),   # lines that are no key are left out
                           ("\xff", ())):                                      # no text at all
            with self.subTest(text=text):
                with open(written, "w", encoding="latin-1") as f:
                    f.write(text)
                self.assertEqual(signing.added_keys(written), keys)
        with open(written, "w", encoding="ascii") as f:
            f.write(key + "\n")
        self.assertFalse(signing.checks_out(strangers, path, NAME))
        with mock.patch.object(signing, "TEST_KEYS_FILE", written):
            # The launcher built with that file takes the test's key, and the project's as before.
            self.assertEqual(signing.trusted(), signing.KEYS + (key,))
            self.assertTrue(signing.checks_out(strangers, path, NAME))
            self.assertTrue(signing.content_checks_out(strangers, path, NAME))
            self.assertTrue(signing.checks_out(self.sig(path), path, NAME))

    def test_the_command_line_makes_a_key_signs_and_checks(self):
        key_file = os.path.join(self.folder, "throwaway.key")
        path = self.package()

        def run(*argv):
            """main()'s exit code and what it printed."""
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = signing.main(list(argv))
            return code, out.getvalue()

        code, said = run("new-key", key_file)
        public = said.strip()
        self.assertEqual((code, len(public)), (0, 64))
        if os.name == "posix":
            # Readable by its owner only, from the moment it exists.
            self.assertEqual(stat.S_IMODE(os.stat(key_file).st_mode), 0o600)
        with open(key_file, encoding="ascii") as f:
            self.assertEqual(signing.public_key(bytes.fromhex(f.read().strip())).hex(), public)
        # A key is never written over.
        with self.assertRaises(SystemExit):
            signing.main(["new-key", key_file])
        self.assertEqual(run("sign", key_file, path), (0, "signed %s\n" % NAME))
        # The key is not one built in: not signed for a launcher, unless the build was given it (a test build).
        self.assertEqual(run("check", path), (1, "%s: NOT SIGNED by a key built in\n" % NAME))
        self.assertEqual(run("check", "--key", public, path), (0, "%s: signed\n" % NAME))
        self.assertEqual(run("check", "--key", public.upper(), path), (0, "%s: signed\n" % NAME))
        with mock.patch.object(signing, "KEYS", (public,)):
            self.assertEqual(run("check", path), (0, "%s: signed\n" % NAME))
            # A file changed after it was signed, a package with no .sig, and both signatures looked at.
            shutil.copy(path, path + ".copy")
            self.assertEqual(run("check", path + ".copy")[0], 1)
            with open(path + ".sig", encoding="utf-8") as f:
                said = json.load(f)
            with open(path + ".sig", "w", encoding="utf-8") as f:
                json.dump(dict(said, content_signature=flipped(said["content_signature"])), f)
            self.assertEqual(run("check", path)[0], 1)
        # A key that is none, a key and no package, a key file that is no key: said, never a pass.
        for argv in (["check", "--key", "abc", path], ["check", "--key", public], ["sign", path, path]):
            with self.subTest(argv=argv[:3]), self.assertRaises((SystemExit, ValueError)):
                signing.main(argv)
        # Anything else: the three commands.
        code, said = run("help")
        self.assertEqual((code, len(said.strip().splitlines())), (2, 3))
        self.assertIn("check [--key PUBLIC] PACKAGE...", said)


if __name__ == "__main__":
    unittest.main()
