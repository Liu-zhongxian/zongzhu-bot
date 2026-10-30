"""Live connectivity checks for OpenClaw gateway.

Usage:
    OPENCLAW_LIVE_TEST=1 python3 -m unittest tests/test_openclaw_live_connectivity.py -v

Optional overrides:
    OPENCLAW_URL=ws://127.0.0.1:18789
    OPENCLAW_TOKEN=...
    OPENCLAW_SESSION_KEY=main:open-xiaoai-bridge
    OPENCLAW_DEVICE_IDENTITY_PATH=/tmp/open-xiaoai-device.json
"""

import os
import unittest
import uuid

from core.openclaw import OpenClawManager


def _enabled() -> bool:
    return os.getenv("OPENCLAW_LIVE_TEST", "").strip().lower() in {"1", "true", "yes"}


@unittest.skipUnless(_enabled(), "set OPENCLAW_LIVE_TEST=1 to run live OpenClaw connectivity tests")
class OpenClawLiveConnectivityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        OpenClawManager.initialize_from_config(enabled=True)

        # Allow local shell overrides without editing config.py.
        url = os.getenv("OPENCLAW_URL", "").strip()
        token = os.getenv("OPENCLAW_TOKEN", "").strip()
        session_key = os.getenv("OPENCLAW_SESSION_KEY", "").strip()
        identity_path = os.getenv("OPENCLAW_DEVICE_IDENTITY_PATH", "").strip()
        if url:
            OpenClawManager._url = url
        if token:
            OpenClawManager._token = token
        if session_key:
            OpenClawManager._session_key = session_key
        if identity_path:
            OpenClawManager._identity_path = os.path.expanduser(identity_path)

    async def asyncTearDown(self):
        try:
            await OpenClawManager.close()
        except Exception:
            pass

    async def test_connect_and_health(self):
        self.assertTrue(
            bool(OpenClawManager._token),
            "OpenClaw token is empty; set config.py openclaw.token or OPENCLAW_TOKEN",
        )
        ok = await OpenClawManager.connect()
        self.assertTrue(ok, f"connect failed, url={OpenClawManager._url}")

        health = await OpenClawManager._request("health", {}, timeout=10)
        self.assertTrue(health.get("ok"), f"health failed: {health}")

    async def test_write_scope_not_missing(self):
        ok = await OpenClawManager.connect()
        self.assertTrue(ok, f"connect failed, url={OpenClawManager._url}")

        # We intentionally send an invalid agent payload so the handler returns quickly.
        # The key check is that we do NOT get "missing scope: operator.write".
        res = await OpenClawManager._request(
            "agent",
            {
                "sessionKey": OpenClawManager._session_key or "main",
                "deliver": False,
                "idempotencyKey": f"live-scope-{uuid.uuid4().hex[:8]}",
                # message intentionally omitted
            },
            timeout=10,
        )
        if res.get("ok"):
            return
        message = str((res.get("error") or {}).get("message") or "")
        self.assertNotIn(
            "missing scope: operator.write",
            message,
            f"write scope missing in live call: {res}",
        )

    async def test_agent_message_is_accepted(self):
        ok = await OpenClawManager.connect()
        self.assertTrue(ok, f"connect failed, url={OpenClawManager._url}")

        message = os.getenv("OPENCLAW_LIVE_MESSAGE", "OpenClaw live connectivity test")
        idem = f"live-agent-{uuid.uuid4().hex[:8]}"
        res = await OpenClawManager._request(
            "agent",
            {
                "message": message,
                "sessionKey": OpenClawManager._session_key or "main",
                "deliver": False,
                "idempotencyKey": idem,
            },
            timeout=20,
        )
        self.assertTrue(res.get("ok"), f"agent request failed: {res}")
        payload = res.get("payload") or {}
        self.assertTrue(
            payload.get("runId") or payload.get("status"),
            f"agent request was accepted but payload looked empty: {res}",
        )


if __name__ == "__main__":
    unittest.main()
