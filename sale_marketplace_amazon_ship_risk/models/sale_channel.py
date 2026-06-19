# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    ship_risk_threshold_hours = fields.Float(
        "Ship Risk Threshold (hours)",
        default=24.0,
        help="Hours-to-cutoff at or below which an order is flagged at risk.",
    )
    ship_risk_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Ship Risk Calendar",
        help="If set, hours-to-cutoff is counted in this calendar's working "
        "hours instead of wall-clock.",
    )

    @api.model
    def _amazon_parse_dt(self, value):
        """Parse an SP-API ISO-8601 datetime to a naive UTC datetime."""
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        if parsed.tzinfo:
            parsed = parsed.astimezone(pytz.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)

    def _amazon_capture_ship_dates(self, order):
        """Fetch ship dates + fulfillment channel for an order and update risk.

        The risk is recomputed unconditionally afterwards, so a transient write
        or API hiccup never leaves the order's risk state stale.
        """
        self.ensure_one()
        from sp_api.api import Orders

        api = self._amazon_get_api(Orders)
        try:
            result = api.get_order(order.client_order_ref)
            payload = result.payload or {}
        except Exception as exc:  # pragma: no cover - logged; risk still recomputed
            _logger.warning(
                "Amazon GetOrder failed for %s: %s", order.client_order_ref, exc
            )
            payload = {}
        vals = {}
        latest = self._amazon_parse_dt(payload.get("LatestShipDate"))
        earliest = self._amazon_parse_dt(payload.get("EarliestShipDate"))
        channel = payload.get("FulfillmentChannel")
        if latest:
            vals["amazon_latest_ship_date"] = latest
        if earliest:
            vals["amazon_earliest_ship_date"] = earliest
        if channel:
            vals["amazon_fulfillment_channel"] = channel
        if vals:
            order.write(vals)
        order._amazon_update_ship_risk()
