# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.clean_channel = cls.env["sale.channel"].create(
            {"name": "Walmart Clean", "channel_type": "walmart"}
        )
        product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )
        product2 = cls.env["product.product"].create(
            {"name": "Widget 2", "default_code": "SKU-2"}
        )
        Binding = cls.env["sale.channel.product"]
        cls.binding = Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": product.id,
                "external_id": "SKU-1",
                "inventory_sync_enabled": True,
            }
        )
        Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": product2.id,
                "external_id": "SKU-2",
                "inventory_sync_enabled": False,
            }
        )
        cls.env["sale.channel.product.walmart.price.history"].create(
            {
                "sale_channel_product_id": cls.binding.id,
                "new_price": 20.0,
                "trigger": "manual",
            }
        )
        group = cls.env["sale.channel.walmart.settlement.group"].create(
            {"sale_channel_id": cls.channel.id, "walmart_settlement_id": "S1"}
        )
        cls.env["sale.channel.walmart.settlement.reconciliation"].create(
            {
                "settlement_group_id": group.id,
                "purchase_order_id": "PO-1",
                "state": "matched",
            }
        )
        cls.env["sale.channel.walmart.settlement.reconciliation"].create(
            {
                "settlement_group_id": group.id,
                "purchase_order_id": "PO-2",
                "state": "variance",
                "variance": 5.0,
            }
        )
        cls.env["sale.channel.walmart.return"].create(
            {
                "sale_channel_id": cls.channel.id,
                "return_order_id": "R1",
                "state": "new",
            }
        )
        cls.env["sale.channel.walmart.return"].create(
            {
                "sale_channel_id": cls.channel.id,
                "return_order_id": "R2",
                "state": "credited",
            }
        )

    def _dash(self, channel=None):
        return self.env["sale.channel.walmart.dashboard"].create(
            {"sale_channel_id": channel.id if channel else False}
        )

    def test_aggregate(self):
        dash = self._dash()
        self.assertEqual(dash.listings_total, 2)
        self.assertEqual(dash.listings_inventory_synced, 1)
        self.assertEqual(dash.price_changes_7d, 1)
        self.assertEqual(dash.settlement_groups, 1)
        self.assertEqual(dash.recon_matched, 1)
        self.assertEqual(dash.recon_variance, 1)
        self.assertAlmostEqual(dash.recon_variance_amount, 5.0)
        self.assertEqual(dash.recon_no_invoice, 0)
        self.assertEqual(dash.returns_open, 1)
        self.assertEqual(dash.returns_credited, 1)

    def test_health_attention_on_variance(self):
        self.assertEqual(self._dash().health_status, "attention")

    def test_health_ok_for_clean_channel(self):
        self.assertEqual(self._dash(self.clean_channel).health_status, "ok")

    def test_backend_filter_scopes(self):
        dash = self._dash(self.clean_channel)
        self.assertEqual(dash.listings_total, 0)
        self.assertEqual(dash.settlement_groups, 0)

    def test_latest_empty_when_no_sync_dates(self):
        self.assertFalse(self._dash(self.clean_channel).last_order_sync)

    def test_drill_recon_variance_action(self):
        action = self._dash().action_open_recon_variance()
        self.assertEqual(
            action["res_model"], "sale.channel.walmart.settlement.reconciliation"
        )
        self.assertIn(("state", "=", "variance"), action["domain"])

    def test_drill_open_returns_action(self):
        action = self._dash().action_open_returns_open()
        self.assertEqual(action["res_model"], "sale.channel.walmart.return")
