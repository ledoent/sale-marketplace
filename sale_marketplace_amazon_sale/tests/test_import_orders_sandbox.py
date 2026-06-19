# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Live Amazon SP-API **sandbox** smoke test (no mocks).

This talks to the real SP-API *sandbox* endpoint, so it needs real LWA
credentials. It is therefore **double-gated** and never runs in normal CI:

1. ``@tagged("-standard", ...)`` removes it from the default test selection,
   so ``oca_run_tests`` (and runboat) skip it.
2. ``skipUnless`` skips it whenever the sandbox credentials are absent from the
   environment.

Run it explicitly, with credentials in the environment:

    odoo -u sale_marketplace_amazon_sale \\
         --test-enable --test-tags amazon_sandbox --stop-after-init

Environment variables (never commit these — keep them local, or in a private
fork's ``workflow_dispatch`` secrets; see
``.github/workflows/amazon-sandbox-smoke.yml``):

    AMAZON_SP_API_CLIENT_ID        LWA app client id
    AMAZON_SP_API_CLIENT_SECRET    LWA app client secret
    AMAZON_SP_API_REFRESH_TOKEN    LWA refresh token  (also the gate)
    AMAZON_SP_API_MARKETPLACE_ID   marketplace id     (default: ATVPDKIKX0DER)
    AMAZON_SP_API_SANDBOX_ORDER_ID static-sandbox order id (default: TEST_CASE_200)

NB: the unit-level coverage of the order-import mapping lives in
``test_import_orders.py`` (fully mocked). This test only proves the live
sandbox round-trip works end to end.
"""

import os
import unittest

from odoo.tests.common import TransactionCase, tagged

SANDBOX_ORDER_ID = os.environ.get("AMAZON_SP_API_SANDBOX_ORDER_ID", "TEST_CASE_200")


@tagged("-standard", "amazon_sandbox")
@unittest.skipUnless(
    os.environ.get("AMAZON_SP_API_REFRESH_TOKEN"),
    "Amazon SP-API sandbox credentials not in environment",
)
class TestImportOrdersSandbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon Sandbox",
                "channel_type": "amazon",
                "amazon_client_id": os.environ["AMAZON_SP_API_CLIENT_ID"],
                "amazon_client_secret": os.environ["AMAZON_SP_API_CLIENT_SECRET"],
                "amazon_refresh_token": os.environ["AMAZON_SP_API_REFRESH_TOKEN"],
                "amazon_marketplace_id": os.environ.get(
                    "AMAZON_SP_API_MARKETPLACE_ID", "ATVPDKIKX0DER"
                ),
                "amazon_sandbox": True,
                "warehouse_id": cls.warehouse.id,
            }
        )

    def test_sandbox_import_order(self):
        """Import one static-sandbox order end to end (real SP-API sandbox)."""
        self.channel.with_context(test_queue_job_no_delay=True)._amazon_import_order(
            SANDBOX_ORDER_ID
        )
        payload = self.env["sale.import.payload"].search(
            [("sale_channel_id", "=", self.channel.id)], order="id desc", limit=1
        )
        self.assertTrue(payload, "no import payload created from the sandbox order")
        self.assertNotEqual(
            payload.state, "fail", f"sandbox import failed: {payload.state_info}"
        )
