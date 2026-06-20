# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Live Walmart Marketplace **sandbox** smoke test (no mocks).

This talks to the real Walmart *sandbox* endpoint (sandbox.walmartapis.com), so
it needs real sandbox API credentials. It is **double-gated** and never runs in
normal CI:

1. ``@tagged("-standard", ...)`` removes it from the default test selection, so
   ``oca_run_tests`` (and runboat) skip it.
2. ``skipUnless`` skips it whenever the sandbox credentials are absent from the
   environment.

Run it explicitly, with credentials in the environment:

    odoo -u sale_marketplace_walmart \\
         --test-enable --test-tags walmart_sandbox --stop-after-init

Environment variables (never commit these — keep them local, or in a private
fork's ``workflow_dispatch`` secrets; see
``.github/workflows/walmart-sandbox-smoke.yml``):

    WALMART_CLIENT_ID       sandbox API client id (also the gate)
    WALMART_CLIENT_SECRET   sandbox API client secret

NB: the Walmart sandbox returns mostly static/canned responses and does not
persist state, so this only proves the OAuth2 round-trip + request signing work
end to end. The business-logic coverage lives in the fully-mocked unit tests.
"""

import os
import unittest

from odoo.tests.common import TransactionCase, tagged


@tagged("-standard", "walmart_sandbox")
@unittest.skipUnless(
    os.environ.get("WALMART_CLIENT_ID"),
    "Walmart sandbox credentials not in environment",
)
class TestWalmartSandbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart Sandbox",
                "channel_type": "walmart",
                "walmart_client_id": os.environ["WALMART_CLIENT_ID"],
                "walmart_client_secret": os.environ["WALMART_CLIENT_SECRET"],
                "walmart_sandbox": True,
            }
        )

    def test_sandbox_token_round_trip(self):
        """Fetch an OAuth2 token from the real Walmart sandbox."""
        token = self.channel._walmart_get_token()
        self.assertTrue(token, "no access token returned from the Walmart sandbox")
