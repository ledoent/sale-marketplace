# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    inventory_sync_enabled = fields.Boolean("Inventory Sync", default=False)
    inventory_location_ids = fields.Many2many(
        "stock.location",
        "sale_channel_stock_location_rel",
        "channel_id",
        "location_id",
        string="Fulfillment Locations",
        domain=[("usage", "=", "internal")],
        help="Stock locations counted toward marketplace quantity. "
        "Leave empty to use the warehouse's default stock location.",
    )
    inventory_expose_ratio = fields.Float(
        "Expose Ratio",
        default=1.0,
        help="Fraction of available stock to push to the marketplace (0.0–1.0).",
    )
    inventory_min_reserve = fields.Integer(
        "Min Reserve",
        default=0,
        help="Units always held back for internal orders regardless of expose ratio.",
    )
    last_inventory_sync_date = fields.Datetime(
        "Last Inventory Sync", readonly=True, copy=False
    )

    @api.constrains("inventory_expose_ratio")
    def _check_expose_ratio(self):
        for rec in self:
            if not 0.0 <= rec.inventory_expose_ratio <= 1.0:
                raise ValidationError(_("Expose Ratio must be between 0.0 and 1.0."))

    @api.constrains("inventory_min_reserve")
    def _check_min_reserve(self):
        for rec in self:
            if rec.inventory_min_reserve < 0:
                raise ValidationError(_("Min Reserve cannot be negative."))

    def _walmart_compute_qty(self, product):
        """Return the quantity to push for a product.

        max(0, floor(free_qty * expose_ratio) - min_reserve), where free_qty is
        on-hand minus reserved across the configured locations.
        """
        self.ensure_one()
        if self.inventory_location_ids:
            location_ids = self.inventory_location_ids.ids
        elif self.warehouse_id:
            location_ids = [self.warehouse_id.lot_stock_id.id]
        else:
            return 0
        quants = self.env["stock.quant"].search(
            [("product_id", "=", product.id), ("location_id", "in", location_ids)]
        )
        # Clamp the aggregate, not each quant: a location with reserved > on-hand
        # must offset other locations, otherwise we over-expose stock.
        free_qty = max(0.0, sum(q.quantity - q.reserved_quantity for q in quants))
        return max(
            0,
            int(free_qty * self.inventory_expose_ratio) - self.inventory_min_reserve,
        )

    def _walmart_push_inventory(self):
        """Push stock qty for each active binding whose qty changed."""
        self.ensure_one()
        token = self._walmart_get_token()
        bindings = self.sale_channel_product_ids.filtered(
            lambda b: b.active and b.inventory_sync_enabled
        )
        pushed = 0
        for binding in bindings:
            new_qty = self._walmart_compute_qty(binding.product_id)
            if new_qty == binding.last_pushed_qty:
                continue
            try:
                self._walmart_request(
                    "PUT",
                    "/v3/inventory",
                    params={"sku": binding.external_id},
                    payload={
                        "sku": binding.external_id,
                        "quantity": {"unit": "EACH", "amount": new_qty},
                    },
                    token=token,
                )
                binding.write(
                    {
                        "last_pushed_qty": new_qty,
                        "last_inventory_push_date": fields.Datetime.now(),
                    }
                )
                pushed += 1
            except Exception as exc:
                _logger.warning(
                    "inventory push failed for SKU %s on channel %s: %s",
                    binding.external_id,
                    self.display_name,
                    exc,
                )
        self.last_inventory_sync_date = fields.Datetime.now()
        _logger.info(
            "pushed inventory for %d/%d bindings on channel %s",
            pushed,
            len(bindings),
            self.display_name,
        )
        self._walmart_log(
            "inventory_push", f"Pushed inventory for {pushed}/{len(bindings)} SKU(s)."
        )

    def action_walmart_push_inventory(self):
        self.ensure_one()
        self.with_delay(
            description=f"Push inventory for {self.display_name}"
        )._walmart_push_inventory()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Inventory Push Queued"),
                "message": _("Inventory synchronisation job has been queued."),
                "type": "info",
            },
        }

    @api.model
    def _cron_walmart_push_inventory(self):
        channels = self.search(
            [
                ("channel_type", "=", "walmart"),
                ("active", "=", True),
                ("inventory_sync_enabled", "=", True),
            ]
        )
        for channel in channels:
            channel.with_delay(
                description=f"Push inventory for {channel.display_name}"
            )._walmart_push_inventory()
