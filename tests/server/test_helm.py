"""The Helm chart (deploy/helm/opendmt3) as Helm reads it: it lints clean, it renders with its defaults and with every
optional part on, each part says what it should, its version is the server's, and every value the templates read is
in values.yaml. The kind test (deploy/kind/up.sh) installs it on a cluster; these need Helm alone, and are skipped
without it."""

import os
import re
import shutil
import subprocess
import unittest

from opendmt3 import __version__

# The repository's top folder (this file is in tests/server/).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHART = os.path.join(ROOT, "deploy", "helm", "opendmt3")
HELM = shutil.which("helm")
# Every optional part on: the first account from the chart's Secret, an Ingress with HTTPS, a NodePort, a proxy.
EVERYTHING = ["admin.enabled=true", "admin.password=abc12345", "ingress.enabled=true", "ingress.host=dmt.example.org",
              "ingress.tls[0].secretName=dmt3-tls", "ingress.tls[0].hosts[0]=dmt.example.org",
              "game.service.type=NodePort", "game.service.nodePort=30725", "proxy=10.244.0.0/16",
              "siteAddress=https://dmt.example.org/"]


def helm(*args):
    """Helm's output for these arguments; a failure is the test's failure, with what Helm said."""
    done = subprocess.run([HELM, *args], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError("helm %s: %s" % (" ".join(args), done.stderr or done.stdout))
    return done.stdout


def render(*values):
    """The chart rendered for a release named dmt3, with these --set values."""
    args = ["template", "dmt3", CHART]
    for value in values:
        args += ["--set", value]
    return helm(*args)


def kinds(text):
    """The kinds of the objects a rendering makes, in order."""
    return re.findall(r"^kind: (\w+)$", text, re.M)


class ChartFileTest(unittest.TestCase):
    """What needs no Helm: the chart's version and the values its templates read."""

    def read(self, *parts):
        with open(os.path.join(CHART, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_chart_and_the_server_have_one_version(self):
        chart = self.read("Chart.yaml")
        self.assertIn("\nversion: %s\n" % __version__, chart)
        self.assertIn('\nappVersion: "%s"\n' % __version__, chart)

    def test_every_value_the_templates_read_is_in_values_yaml(self):
        values = self.read("values.yaml")
        # The top keys values.yaml has (lines that start a key at no indent).
        tops = set(re.findall(r"^([A-Za-z]\w*):", values, re.M))
        read = set()
        for name in os.listdir(os.path.join(CHART, "templates")) + ["tests/" + n for n in
                                                                    os.listdir(os.path.join(CHART, "templates",
                                                                                            "tests"))]:
            if name.endswith((".yaml", ".tpl", ".txt")):
                read |= set(re.findall(r"\.Values\.([A-Za-z]\w*)", self.read("templates", name)))
        self.assertFalse(read - tops, "read by the templates, missing from values.yaml")


@unittest.skipUnless(HELM, "needs helm")
class ChartTest(unittest.TestCase):

    def test_it_lints_clean_with_its_defaults_and_with_every_part_on(self):
        helm("lint", "--strict", CHART)
        args = ["lint", "--strict", CHART]
        for value in EVERYTHING:
            args += ["--set", value]
        helm(*args)

    def test_the_defaults_make_one_server_its_volume_and_two_services(self):
        text = render()
        self.assertEqual(sorted(kinds(text)), ["Deployment", "PersistentVolumeClaim", "Pod", "Service", "Service"])
        # One server, the old pod gone before the new one starts: SQLite on one volume.
        self.assertIn("replicas: 1", text)
        self.assertIn("type: Recreate", text)
        # The image of the chart's own version, run as its own user.
        self.assertIn("image: ghcr.io/kanggu12/opendmt3-server:%s" % __version__, text)
        self.assertIn("runAsUser: 4725", text)
        self.assertIn("fsGroup: 4725", text)
        # The game's port outside the cluster with each cabinet's own address; the site inside it.
        self.assertIn("type: LoadBalancer", text)
        self.assertIn("externalTrafficPolicy: Local", text)
        self.assertIn("type: ClusterIP", text)
        # The probes ask /health; no first account, no Ingress, no Secret without being asked.
        self.assertIn("path: /health", text)
        self.assertNotIn("first-account", text)
        # The volume stays when the chart is uninstalled.
        self.assertIn("helm.sh/resource-policy: keep", text)

    def test_every_part_on_adds_the_account_the_ingress_and_the_arguments(self):
        text = render(*EVERYTHING)
        self.assertEqual(sorted(kinds(text)), ["Deployment", "Ingress", "PersistentVolumeClaim", "Pod", "Secret",
                                               "Service", "Service"])
        self.assertIn("name: first-account", text)
        # The password reaches the init container from the Secret, never in its command.
        self.assertIn("secretKeyRef:", text)
        self.assertNotIn("abc12345\n          ", text.split("kind: Deployment", 1)[1])
        self.assertIn("- --site-address\n            - \"https://dmt.example.org/\"", text)
        self.assertIn("- --proxy\n            - \"10.244.0.0/16\"", text)
        self.assertIn("nodePort: 30725", text)
        self.assertIn("secretName: dmt3-tls", text)
        self.assertIn('host: "dmt.example.org"', text)

    def test_an_account_without_a_password_is_refused_at_install(self):
        done = subprocess.run([HELM, "template", "dmt3", CHART, "--set", "admin.enabled=true"], capture_output=True,
                              text=True, timeout=60)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("admin.password or admin.existingSecret", done.stderr)

    def test_an_owners_secret_and_claim_replace_the_charts(self):
        text = render("admin.enabled=true", "admin.existingSecret=mine", "persistence.existingClaim=my-data")
        self.assertNotIn("kind: Secret", text)
        self.assertNotIn("kind: PersistentVolumeClaim", text)
        self.assertIn("name: mine", text)
        self.assertIn("claimName: my-data", text)


if __name__ == "__main__":
    unittest.main()
