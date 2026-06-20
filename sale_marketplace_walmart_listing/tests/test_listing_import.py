# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


class TestListingImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )

    def _resp(self, items, next_cursor=None):
        return {"ItemResponse": items, "nextCursor": next_cursor}

    def test_import_creates_binding(self):
        items = [{"sku": "SKU-1", "wpid": "WPID-1", "productName": "Widget"}]
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", return_value=self._resp(items)),
        ):
            self.channel.action_walmart_import_listings()
        binding = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.channel.id), ("external_id", "=", "SKU-1")]
        )
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding.product_id, self.product)
        self.assertEqual(binding.wpid, "WPID-1")

    def test_import_updates_existing_binding(self):
        self.env["sale.channel.product"].create(
            {
                "sale_channel_id": self.channel.id,
                "product_id": self.product.id,
                "external_id": "SKU-1",
            }
        )
        items = [{"sku": "SKU-1", "wpid": "WPID-9"}]
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", return_value=self._resp(items)),
        ):
            self.channel.action_walmart_import_listings()
        bindings = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.channel.id), ("external_id", "=", "SKU-1")]
        )
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings.wpid, "WPID-9")

    def test_import_paginates(self):
        page1 = self._resp([{"sku": "SKU-1", "wpid": "W1"}], next_cursor="?offset=1")
        page2 = self._resp([{"sku": "SKU-2", "wpid": "W2", "productName": "Gadget"}])
        self.env["product.product"].create({"name": "Gadget", "default_code": "SKU-2"})
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", side_effect=[page1, page2]) as req,
        ):
            self.channel.action_walmart_import_listings()
        self.assertEqual(req.call_count, 2)
        self.assertEqual(
            req.call_args_list[1].kwargs["params"]["nextCursor"], "?offset=1"
        )
        bindings = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.channel.id)]
        )
        self.assertEqual(set(bindings.mapped("external_id")), {"SKU-1", "SKU-2"})

    @mute_logger("odoo.addons.sale_marketplace_walmart_listing.models.sale_channel")
    def test_import_skips_unknown_sku(self):
        items = [{"sku": "UNKNOWN", "wpid": "W-X"}]
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", return_value=self._resp(items)),
        ):
            self.channel.action_walmart_import_listings()
        self.assertFalse(
            self.env["sale.channel.product"].search(
                [("sale_channel_id", "=", self.channel.id)]
            )
        )
        # the unknown SKU is persisted as a warning in the Walmart log
        warning = self.env["sale.channel.walmart.log"].search(
            [
                ("sale_channel_id", "=", self.channel.id),
                ("level", "=", "warning"),
                ("reference", "=", "UNKNOWN"),
            ]
        )
        self.assertTrue(warning)
