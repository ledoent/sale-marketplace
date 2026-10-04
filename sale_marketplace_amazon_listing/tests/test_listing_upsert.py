# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestListingUpsert(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {"name": "Amazon US", "channel_type": "amazon"}
        )
        cls.product = cls.env["product.product"].create({"name": "Widget"})
        cls.other = cls.env["product.product"].create({"name": "Gadget"})

    def test_upsert_creates_then_updates(self):
        binding_model = self.env["sale.channel.product"]
        binding = binding_model._amazon_upsert(
            self.channel, self.product, "SKU-1", "ASIN-1"
        )
        self.assertEqual(binding.external_id, "SKU-1")
        self.assertEqual(binding.asin, "ASIN-1")
        self.assertEqual(binding.product_id, self.product)

        # Same SKU upserts the same record (new ASIN + product applied).
        again = binding_model._amazon_upsert(
            self.channel, self.other, "SKU-1", "ASIN-2"
        )
        self.assertEqual(again, binding)
        self.assertEqual(binding.asin, "ASIN-2")
        self.assertEqual(binding.product_id, self.other)
