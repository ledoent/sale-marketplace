# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import pytz

from odoo import api, fields, models

_OPEN_STATES = ("sale", "done")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    amazon_latest_ship_date = fields.Datetime(readonly=True)
    amazon_earliest_ship_date = fields.Datetime(readonly=True)
    amazon_fulfillment_channel = fields.Char(readonly=True)
    amazon_ship_deadline_hours = fields.Float(readonly=True)
    amazon_ship_risk = fields.Selection(
        [
            ("none", "None"),
            ("on_track", "On Track"),
            ("at_risk", "At Risk"),
            ("blocked", "Blocked"),
            ("overdue", "Overdue"),
        ],
        default="none",
        readonly=True,
        index=True,
    )

    def _amazon_delivery_ready(self):
        """True when no pending outgoing picking is blocked (all assigned)."""
        self.ensure_one()
        pending = self.picking_ids.filtered(
            lambda p: p.picking_type_id.code == "outgoing"
            and p.state not in ("done", "cancel")
        )
        return all(p.state == "assigned" for p in pending)

    def _amazon_hours_to_cutoff(self):
        """Hours until the latest ship date (business hours if a calendar set)."""
        self.ensure_one()
        cutoff = self.amazon_latest_ship_date
        if not cutoff:
            return 0.0
        now = fields.Datetime.now()
        if cutoff <= now:
            return 0.0
        calendar = self.sale_channel_id.ship_risk_calendar_id
        if calendar:
            # resource.calendar needs tz-aware datetimes; Odoo stores naive UTC.
            now_utc = pytz.utc.localize(now)
            cutoff_utc = pytz.utc.localize(cutoff)
            return calendar.get_work_hours_count(now_utc, cutoff_utc)
        return (cutoff - now).total_seconds() / 3600.0

    def _amazon_update_ship_risk(self):
        """Recompute the ship-risk state for each order from stored data."""
        for order in self:
            if (
                order.amazon_fulfillment_channel != "MFN"
                or not order.amazon_latest_ship_date
            ):
                order.amazon_ship_risk = "none"
                continue
            if not order._amazon_delivery_ready():
                order.amazon_ship_risk = "blocked"
                continue
            hours = order._amazon_hours_to_cutoff()
            order.amazon_ship_deadline_hours = hours
            threshold = order.sale_channel_id.ship_risk_threshold_hours
            if hours <= 0:
                order.amazon_ship_risk = "overdue"
            elif hours <= threshold:
                order.amazon_ship_risk = "at_risk"
            else:
                order.amazon_ship_risk = "on_track"

    @api.model
    def _cron_amazon_update_ship_risk(self):
        orders = self.search(
            [
                ("sale_channel_id.channel_type", "=", "amazon"),
                ("state", "in", _OPEN_STATES),
            ]
        )
        for order in orders:
            channel = order.sale_channel_id
            if channel and not order.amazon_latest_ship_date:
                channel.with_delay()._amazon_capture_ship_dates(order)
            else:
                order._amazon_update_ship_risk()
