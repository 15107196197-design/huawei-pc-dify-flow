"""Offline checks for the deliberately narrow local-network exception."""
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "deploy/dify-local/generate-bridge-squid.py"
SPEC = importlib.util.spec_from_file_location("generate_bridge_squid", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BridgeSquidPolicyTests(unittest.TestCase):
    def test_reviewed_upstream_generates_only_narrow_exception(self):
        output = MODULE.generate(MODULE.UPSTREAM)
        self.assertIn("acl huawei_bridge_dst dst 192.168.5.2/32\n", output)
        self.assertIn("acl huawei_bridge_port port 8765\n", output)
        self.assertIn("acl huawei_bridge_method method POST\n", output)
        self.assertIn("acl huawei_bridge_path urlpath_regex ^/v1/(contexts/resolve|kb/evidence|quotes/solve)$\n", output)
        rule = "http_access allow client_localnet huawei_bridge_dst huawei_bridge_port huawei_bridge_method huawei_bridge_path\n"
        self.assertEqual(output.count(rule), 1)
        self.assertLess(output.index(rule), output.index("http_access deny to_private_networks\n"))
        self.assertNotIn("include /etc/squid/dify_allow_private.conf", output)

    def test_public_and_sandbox_policy_is_preserved(self):
        output = MODULE.generate(MODULE.UPSTREAM)
        for value in ["include /etc/squid/dify_common.conf\n",
                      "include /etc/squid/dify_sandbox_proxy.conf\n",
                      "http_access deny !Safe_ports\n",
                      "http_access deny CONNECT !SSL_ports\n",
                      "http_access deny to_private_networks\n",
                      "http_access allow allowed_domains\n",
                      "http_access deny all\n"]:
            self.assertIn(value, output)

    def test_drift_is_rejected(self):
        for source in ["", MODULE.UPSTREAM.replace("deny to_private_networks", "allow to_private_networks"),
                       MODULE.UPSTREAM + "http_access allow all\n"]:
            with self.assertRaises(ValueError):
                MODULE.generate(source)

    def test_already_generated_policy_is_idempotent(self):
        output = MODULE.generate(MODULE.UPSTREAM)
        self.assertEqual(MODULE.generate(output), output)

    def test_review_artifact_matches_generator(self):
        self.assertEqual(PATH.with_name("squid-bridge.conf.template").read_text(), MODULE.generate(MODULE.UPSTREAM))


if __name__ == "__main__":
    unittest.main()
