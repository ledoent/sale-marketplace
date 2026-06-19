# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests.common import TransactionCase


class TestCreateImportPayload(TransactionCase):
    """The marketplace import seam wraps sale.import.payload creation.

    We do not run the enqueued processing job here (no
    ``test_queue_job_no_delay``); processing the payload end-to-end is covered
    by the connector suites (e.g. ``sale_marketplace_amazon_sale``). This test
    only proves the boundary helper writes a payload bound to the channel.
    """

    def test_create_import_payload(self):
        channel = self.env["sale.channel"].create({"name": "Test Marketplace"})
        data = {"name": "EXT-ORDER-1", "lines": []}

        payload = channel._create_import_payload(data)

        self.assertEqual(payload._name, "sale.import.payload")
        self.assertEqual(payload.sale_channel_id, channel)
        self.assertEqual(payload.company_id, channel.company_id)
        self.assertEqual(json.loads(payload.data_str), data)
