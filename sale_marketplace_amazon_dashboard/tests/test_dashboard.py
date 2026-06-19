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
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.clean_channel = cls.env["sale.channel"].create(
            {"name": "Amazon Clean", "channel_type": "amazon"}
        )
        product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )
        Binding = cls.env["sale.channel.product"]
        cls.winner = Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": product.id,
                "external_id": "SKU-1",
                "buy_box_price": 20.0,
                "buy_box_winner": True,
            }
        )
        Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": product.copy().id,
                "external_id": "SKU-2",
                "buy_box_price": 15.0,
                "buy_box_winner": False,
            }
        )
        cls.env["sale.channel.product.price.history"].create(
            {
                "sale_channel_product_id": cls.winner.id,
                "new_price": 20.0,
                "trigger": "manual",
            }
        )
        cls.env["sale.channel.product.offer.snapshot"].create(
            {"sale_channel_product_id": cls.winner.id, "price": 20.0}
        )
        cls.env["sale.channel.fba.inventory"].create(
            {
                "sale_channel_id": cls.channel.id,
                "seller_sku": "SKU-1",
                "product_id": product.id,
                "fulfillable_qty": 8,
                "odoo_qty": 5,
            }
        )
        group = cls.env["sale.channel.settlement.group"].create(
            {"sale_channel_id": cls.channel.id, "amazon_group_id": "G1"}
        )
        cls.env["sale.channel.settlement.reconciliation"].create(
            {
                "settlement_group_id": group.id,
                "amazon_order_id": "O1",
                "state": "matched",
            }
        )
        cls.env["sale.channel.settlement.reconciliation"].create(
            {
                "settlement_group_id": group.id,
                "amazon_order_id": "O2",
                "state": "variance",
                "variance": 5.0,
            }
        )
        cls.env["sale.channel.return"].create(
            {"sale_channel_id": cls.channel.id, "rma_id": "R1", "state": "new"}
        )
        cls.env["sale.channel.return"].create(
            {"sale_channel_id": cls.channel.id, "rma_id": "R2", "state": "credited"}
        )

    def _dash(self, channel=None):
        return self.env["sale.channel.dashboard"].create(
            {"sale_channel_id": channel.id if channel else False}
        )

    def test_aggregate(self):
        dash = self._dash()
        self.assertEqual(dash.listings_total, 2)
        self.assertEqual(dash.listings_buybox_us, 1)
        self.assertAlmostEqual(dash.buybox_win_rate, 0.5)
        self.assertEqual(dash.price_changes_7d, 1)
        self.assertEqual(dash.offers_7d, 1)
        self.assertEqual(dash.fba_skus, 1)
        self.assertEqual(dash.fba_drift_skus, 1)
        self.assertEqual(dash.fba_total_drift, 3)
        self.assertEqual(dash.settlement_groups, 1)
        self.assertEqual(dash.recon_matched, 1)
        self.assertEqual(dash.recon_variance, 1)
        self.assertAlmostEqual(dash.recon_variance_amount, 5.0)
        self.assertEqual(dash.returns_open, 1)
        self.assertEqual(dash.returns_credited, 1)

    def test_health_attention_on_variance_and_drift(self):
        self.assertEqual(self._dash().health_status, "attention")

    def test_health_ok_for_clean_channel(self):
        # the clean channel has no listings/drift/variance/returns
        self.assertEqual(self._dash(self.clean_channel).health_status, "ok")

    def test_backend_filter_scopes(self):
        dash = self._dash(self.clean_channel)
        self.assertEqual(dash.listings_total, 0)
        self.assertEqual(dash.fba_skus, 0)

    def test_latest_empty_when_no_sync_dates(self):
        # the clean channel never synced -> last_* are falsy, no error
        self.assertFalse(self._dash(self.clean_channel).last_order_sync)

    def test_drill_recon_variance_action(self):
        action = self._dash().action_open_recon_variance()
        self.assertEqual(action["res_model"], "sale.channel.settlement.reconciliation")
        self.assertIn(("state", "=", "variance"), action["domain"])
