import unittest

from core.openclaw import OpenClawManager


class OpenClawProtocolTest(unittest.TestCase):
    def test_connect_params_include_protocol_version_range(self):
        client_meta = {
            "id": "gateway-client",
            "displayName": "Open-Xiaoai Bridge",
            "version": "1.0.0",
            "platform": "python",
            "mode": "backend",
            "instanceId": "xiaoai-test",
        }
        scopes = ["operator.read", "operator.write"]

        params = OpenClawManager._build_connect_params(
            client_meta=client_meta,
            scopes=scopes,
            token="token",
        )

        self.assertEqual(3, OpenClawManager._min_protocol)
        self.assertEqual(4, OpenClawManager._max_protocol)
        self.assertEqual(OpenClawManager._min_protocol, params["minProtocol"])
        self.assertEqual(OpenClawManager._max_protocol, params["maxProtocol"])
        self.assertEqual(client_meta, params["client"])
        self.assertEqual(scopes, params["scopes"])
        self.assertEqual({"token": "token"}, params["auth"])
        self.assertNotIn("device", params)

    def test_connect_params_use_empty_auth_token_when_token_is_none(self):
        params = OpenClawManager._build_connect_params(
            client_meta={"id": "gateway-client"},
            scopes=[],
            token=None,
            device_payload=None,
        )

        self.assertEqual({"token": ""}, params["auth"])
        self.assertNotIn("device", params)

    def test_protocol_range_accepts_v3_and_v4_server_protocols(self):
        params = OpenClawManager._build_connect_params(
            client_meta={"id": "gateway-client"},
            scopes=[],
            token="token",
        )

        for server_protocol in (3, 4):
            self.assertLessEqual(params["minProtocol"], server_protocol)
            self.assertGreaterEqual(params["maxProtocol"], server_protocol)

    def test_connect_params_include_device_payload(self):
        device_payload = {
            "id": "device",
            "publicKey": "public",
            "signature": "signature",
            "signedAt": 1,
            "nonce": "nonce",
        }

        params = OpenClawManager._build_connect_params(
            client_meta={"id": "gateway-client"},
            scopes=[],
            device_payload=device_payload,
            token="token",
        )

        self.assertEqual(device_payload, params["device"])


if __name__ == "__main__":
    unittest.main()
