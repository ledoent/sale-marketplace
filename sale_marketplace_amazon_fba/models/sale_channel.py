# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    last_fba_sync_date = fields.Datetime(readonly=True)

    @api.model
    def _amazon_fba_int(self, value):
        """Coerce an SP-API quantity to int, tolerating None / strings / floats."""
        if value is None:
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def _amazon_fba_odoo_qty(self, product):
        """Odoo on-hand for a product at this channel's warehouse stock location."""
        self.ensure_one()
        if not product or not self.warehouse_id:
            return 0
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", self.warehouse_id.lot_stock_id.id),
            ]
        )
        return int(sum(quants.mapped("quantity")))

    def _amazon_upsert_fba_summary(self, summary):
        """Create or update the FBA inventory record for one SP-API summary."""
        self.ensure_one()
        sku = summary.get("sellerSku")
        if not sku:
            return None
        details = summary.get("inventoryDetails", {}) or {}
        reserved = details.get("reservedQuantity", {}) or {}
        unsellable = details.get("unfulfillableQuantity", {}) or {}
        product = (
            self.env["sale.channel.product"]
            .search(
                [("sale_channel_id", "=", self.id), ("external_id", "=", sku)], limit=1
            )
            .product_id
        )
        vals = {
            "product_id": product.id or False,
            "fulfillable_qty": self._amazon_fba_int(details.get("fulfillableQuantity")),
            "inbound_qty": self._amazon_fba_int(details.get("inboundWorkingQuantity")),
            "reserved_qty": self._amazon_fba_int(reserved.get("totalReservedQuantity")),
            "unsellable_qty": self._amazon_fba_int(
                unsellable.get("totalUnfulfillableQuantity")
            ),
            "total_qty": self._amazon_fba_int(summary.get("totalQuantity")),
            "odoo_qty": self._amazon_fba_odoo_qty(product),
            "last_sync_date": fields.Datetime.now(),
        }
        record = self.env["sale.channel.fba.inventory"].search(
            [("sale_channel_id", "=", self.id), ("seller_sku", "=", sku)], limit=1
        )
        if record:
            record.write(vals)
        else:
            record = self.env["sale.channel.fba.inventory"].create(
                dict(vals, sale_channel_id=self.id, seller_sku=sku)
            )
        return record

    def _amazon_sync_fba_inventory(self):
        """Pull FBA inventory summaries (paginated) and upsert drift records."""
        self.ensure_one()
        from sp_api.api import Inventories

        api = self._amazon_get_api(Inventories)
        synced = 0
        next_token = None
        while True:
            kwargs = {
                "details": True,
                "granularityType": "Marketplace",
                "granularityId": self.amazon_marketplace_id,
                "marketplaceIds": [self.amazon_marketplace_id],
            }
            if next_token:
                kwargs["nextToken"] = next_token
            try:
                result = api.get_inventory_summary_marketplace(**kwargs)
            except Exception as exc:  # pragma: no cover - logged and stop
                _logger.warning("Amazon FBA inventory sync failed: %s", exc)
                break
            payload = result.payload or {}
            for summary in payload.get("inventorySummaries", []):
                if self._amazon_upsert_fba_summary(summary):
                    synced += 1
            next_token = (payload.get("pagination", {}) or {}).get("nextToken")
            if not next_token:
                break
        self.last_fba_sync_date = fields.Datetime.now()
        return synced

    def action_amazon_sync_fba_inventory(self):
        self.ensure_one()
        self.with_delay()._amazon_sync_fba_inventory()
        return True

    @api.model
    def _cron_amazon_sync_fba_inventory(self):
        channels = self.search([("channel_type", "=", "amazon")])
        for channel in channels:
            channel._amazon_sync_fba_inventory()
