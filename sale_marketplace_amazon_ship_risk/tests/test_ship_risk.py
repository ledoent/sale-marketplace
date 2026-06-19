# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_ship_risk.models.sale_channel"


class TestShipRisk(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER1",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "warehouse_id": cls.warehouse.id,
                "ship_risk_threshold_hours": 24.0,
            }
        )
        cls.customer = cls.env["res.partner"].create({"name": "Buyer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 100
        )
        cls.order = cls._make_order(assign=True)
        cls.order.amazon_fulfillment_channel = "MFN"

    @classmethod
    def _make_order(cls, assign=True):
        order = cls.env["sale.order"].create(
            {
                "partner_id": cls.customer.id,
                "sale_channel_id": cls.channel.id,
                "client_order_ref": "ORDER-1",
                "order_line": [
                    (0, 0, {"product_id": cls.product.id, "product_uom_qty": 1})
                ],
            }
        )
        order.action_confirm()
        if assign:
            order.picking_ids.action_assign()
        return order

    def _set_cutoff(self, hours):
        self.order.amazon_latest_ship_date = fields.Datetime.now() + timedelta(
            hours=hours
        )

    # ---- risk states ----
    def test_overdue(self):
        self._set_cutoff(-1)
        self.order._amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "overdue")

    def test_at_risk(self):
        self._set_cutoff(2)
        self.order._amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "at_risk")
        self.assertGreater(self.order.amazon_ship_deadline_hours, 0)

    def test_on_track(self):
        self._set_cutoff(100)
        self.order._amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "on_track")

    def test_afn_ignored(self):
        self.order.amazon_fulfillment_channel = "AFN"
        self._set_cutoff(2)
        self.order._amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "none")

    def test_no_ship_date_is_none(self):
        self.order.amazon_latest_ship_date = False
        self.order._amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "none")

    def test_blocked_when_delivery_not_ready(self):
        no_stock = self.env["product.product"].create(
            {"name": "NoStock", "is_storable": True}
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "sale_channel_id": self.channel.id,
                "client_order_ref": "ORDER-2",
                "order_line": [
                    (0, 0, {"product_id": no_stock.id, "product_uom_qty": 1})
                ],
            }
        )
        order.action_confirm()  # no stock -> picking not assigned
        order.amazon_fulfillment_channel = "MFN"
        order.amazon_latest_ship_date = fields.Datetime.now() + timedelta(hours=48)
        order._amazon_update_ship_risk()
        self.assertEqual(order.amazon_ship_risk, "blocked")

    # ---- calendar (timezone-aware) path ----
    def test_hours_to_cutoff_with_calendar(self):
        calendar = self.env["resource.calendar"].search([], limit=1)
        self.channel.ship_risk_calendar_id = calendar.id
        self._set_cutoff(48)
        # must not raise with naive UTC datetimes localized to tz-aware
        hours = self.order._amazon_hours_to_cutoff()
        self.assertGreaterEqual(hours, 0.0)

    # ---- capture ----
    def test_capture_ship_dates(self):
        latest = (fields.Datetime.now() + timedelta(hours=48)).isoformat() + "Z"
        api = MagicMock()
        api.get_order.return_value.payload = {
            "LatestShipDate": latest,
            "FulfillmentChannel": "MFN",
        }
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_capture_ship_dates(self.order)
        self.assertTrue(self.order.amazon_latest_ship_date)
        self.assertEqual(self.order.amazon_fulfillment_channel, "MFN")
        self.assertEqual(self.order.amazon_ship_risk, "on_track")

    def test_parse_dt(self):
        self.assertFalse(self.channel._amazon_parse_dt(None))
        self.assertFalse(self.channel._amazon_parse_dt("garbage"))
        parsed = self.channel._amazon_parse_dt("2026-06-01T23:59:59Z")
        self.assertEqual(parsed.year, 2026)
        self.assertIsNone(parsed.tzinfo)

    def test_cron_updates_open_orders(self):
        latest = (fields.Datetime.now() + timedelta(hours=48)).isoformat() + "Z"
        api = MagicMock()
        api.get_order.return_value.payload = {
            "LatestShipDate": latest,
            "FulfillmentChannel": "MFN",
        }
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.order"]._cron_amazon_update_ship_risk()
        self.assertEqual(self.order.amazon_ship_risk, "on_track")

    @mute_logger(_MODEL_PATH)
    def test_capture_error_recomputes_risk(self):
        api = MagicMock()
        api.get_order.side_effect = Exception("boom")
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_capture_ship_dates(self.order)
        # no dates captured -> risk recomputed to none, no exception raised
        self.assertEqual(self.order.amazon_ship_risk, "none")
