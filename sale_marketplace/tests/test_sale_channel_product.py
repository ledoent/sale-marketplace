# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestSaleChannelProduct(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create({"name": "Marketplace"})
        cls.product = cls.env["product.product"].create({"name": "Test Product"})
        cls.other_product = cls.env["product.product"].create({"name": "Other Product"})
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
            }
        )

    @mute_logger("odoo.sql_db")
    def test_constraint_product_channel_unique(self):
        with self.assertRaises(IntegrityError):
            self.binding.copy({"external_id": "SKU-2"})

    @mute_logger("odoo.sql_db")
    def test_constraint_external_id_channel_unique(self):
        with self.assertRaises(IntegrityError):
            self.binding.copy({"product_id": self.other_product.id})

    def test_channel_product_count(self):
        self.assertEqual(self.channel.sale_channel_product_count, 1)

    def test_not_marketplace_by_default(self):
        # No marketplace channel_type registered by this base module.
        self.assertFalse(self.channel.is_marketplace)
