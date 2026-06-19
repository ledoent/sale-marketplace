# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_fba.models.sale_channel"


def _summary(sku="SKU-1", fulfillable=8, total=10, inbound=2):
    return {
        "sellerSku": sku,
        "totalQuantity": total,
        "inventoryDetails": {
            "fulfillableQuantity": fulfillable,
            "inboundWorkingQuantity": inbound,
            "reservedQuantity": {"totalReservedQuantity": 1},
            "unfulfillableQuantity": {"totalUnfulfillableQuantity": 0},
        },
    }


def _payload(summaries, next_token=None):
    payload = {"inventorySummaries": summaries}
    if next_token:
        payload["pagination"] = {"nextToken": next_token}
    return payload


class TestFba(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, test_queue_job_no_delay=True))
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1", "is_storable": True}
        )
        cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 5
        )

    def _sync(self, payloads):
        api = MagicMock()
        api.get_inventory_summary_marketplace.side_effect = [
            MagicMock(payload=p) for p in payloads
        ]
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            return self.channel._amazon_sync_fba_inventory(), api

    def _record(self, sku="SKU-1"):
        return self.env["sale.channel.fba.inventory"].search(
            [("sale_channel_id", "=", self.channel.id), ("seller_sku", "=", sku)]
        )

    def test_sync_creates_record_and_drift(self):
        synced, _api = self._sync([_payload([_summary(fulfillable=8)])])
        self.assertEqual(synced, 1)
        rec = self._record()
        self.assertEqual(rec.fulfillable_qty, 8)
        self.assertEqual(rec.product_id, self.product)
        self.assertEqual(rec.odoo_qty, 5)
        self.assertEqual(rec.drift, 3)  # 8 fulfillable - 5 on-hand
        self.assertTrue(self.channel.last_fba_sync_date)

    def test_sync_idempotent(self):
        self._sync([_payload([_summary(fulfillable=8)])])
        self._sync([_payload([_summary(fulfillable=4)])])
        recs = self._record()
        self.assertEqual(len(recs), 1)  # updated, not duplicated
        self.assertEqual(recs.fulfillable_qty, 4)

    def test_sync_pagination(self):
        synced, api = self._sync(
            [
                _payload([_summary(sku="SKU-1")], next_token="t1"),
                _payload([_summary(sku="SKU-2")]),
            ]
        )
        self.assertEqual(synced, 2)
        self.assertEqual(api.get_inventory_summary_marketplace.call_count, 2)

    def test_sync_unknown_sku_has_no_product(self):
        self._sync([_payload([_summary(sku="UNKNOWN")])])
        rec = self._record("UNKNOWN")
        self.assertTrue(rec)
        self.assertFalse(rec.product_id)
        self.assertEqual(rec.odoo_qty, 0)

    def test_int_coercion_edges(self):
        self.assertEqual(self.channel._amazon_fba_int(None), 0)
        self.assertEqual(self.channel._amazon_fba_int("7"), 7)
        self.assertEqual(self.channel._amazon_fba_int("7.9"), 7)
        self.assertEqual(self.channel._amazon_fba_int("bad"), 0)
        self.assertEqual(self.channel._amazon_fba_int(3.6), 3)

    def test_cron_syncs(self):
        api = MagicMock()
        api.get_inventory_summary_marketplace.return_value = MagicMock(
            payload=_payload([_summary(fulfillable=8)])
        )
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.channel"]._cron_amazon_sync_fba_inventory()
        self.assertEqual(self._record().fulfillable_qty, 8)

    @mute_logger(_MODEL_PATH)
    def test_sync_error_isolation(self):
        api = MagicMock()
        api.get_inventory_summary_marketplace.side_effect = Exception("boom")
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            synced = self.channel._amazon_sync_fba_inventory()
        self.assertEqual(synced, 0)
        self.assertFalse(self._record())
