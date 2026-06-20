# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import datetime
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Walmart status is per order line; an order whose every line is Cancelled has
# nothing to import.
_LINE_SKIP_STATUSES = {"Cancelled"}

# Walmart sends 3-letter ISO country codes; Odoo expects 2-letter ISO.
_COUNTRY_MAP = {
    "USA": "US",
    "CAN": "CA",
    "MEX": "MX",
    "GBR": "GB",
}

# Default Walmart cancellation reason for a seller-initiated cancel.
_WALMART_CANCEL_REASON = "CANCEL_BY_SELLER"


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    walmart_import_days_back = fields.Integer(
        "Walmart Initial Import Days Back",
        default=7,
        help="On first import, fetch orders created this many days ago.",
    )
    walmart_last_import_date = fields.Datetime(
        "Walmart Last Order Import",
        readonly=True,
        copy=False,
        help="Cursor for incremental order polling.",
    )
    walmart_auto_acknowledge = fields.Boolean(
        default=True,
        help="Acknowledge imported orders on Walmart so they are not "
        "auto-cancelled for non-acknowledgement.",
    )
    walmart_fiscal_position_id = fields.Many2one(
        "account.fiscal.position",
        string="Walmart Fiscal Position",
        help="Applied to imported Walmart orders so Odoo does not re-charge the "
        "sales tax Walmart already collects and remits as a marketplace "
        "facilitator. Map the relevant taxes to 0%% / no tax.",
    )
    walmart_auto_cancel = fields.Boolean(
        default=True,
        help="Push the cancellation to Walmart when a Walmart order is "
        "cancelled in Odoo.",
    )

    @api.model
    def _cron_walmart_import_orders(self):
        """Cron entry point: enqueue an import job per active Walmart channel."""
        channels = self.search(
            [("channel_type", "=", "walmart"), ("active", "=", True)]
        )
        for channel in channels:
            channel.with_delay(
                description=f"Import Walmart orders for {channel.display_name}"
            )._walmart_import_orders()

    def _walmart_import_orders(self):
        """Poll the Orders API and enqueue one import job per order.

        Updates ``walmart_last_import_date`` on success.
        """
        self.ensure_one()
        if self.walmart_last_import_date:
            since = self.walmart_last_import_date
        else:
            since = fields.Datetime.now() - datetime.timedelta(
                days=self.walmart_import_days_back or 7
            )

        token = self._walmart_get_token()
        # Capture the cursor BEFORE polling so orders created during the (possibly
        # paginated) poll are not skipped on the next run.
        poll_start = fields.Datetime.now()
        next_cursor = None
        imported = 0
        while True:
            if next_cursor:
                # nextCursor is a ready-made querystring (starts with "?").
                response = self._walmart_request(
                    "GET", "/v3/orders" + next_cursor, token=token
                )
            else:
                response = self._walmart_request(
                    "GET",
                    "/v3/orders",
                    params={
                        "createdStartDate": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "limit": 200,
                    },
                    token=token,
                )
            listing = (response or {}).get("list", {})
            elements = listing.get("elements", {}) or {}
            for order_data in elements.get("order", []) or []:
                po_id = order_data.get("purchaseOrderId")
                if not po_id:
                    continue
                self.with_delay(
                    description=f"Import Walmart order {po_id}"
                )._walmart_import_order(po_id)
                imported += 1

            next_cursor = (listing.get("meta", {}) or {}).get("nextCursor")
            if not next_cursor:
                break

        self.walmart_last_import_date = poll_start
        _logger.info(
            "Channel %s: enqueued %d order import jobs.", self.display_name, imported
        )
        self._walmart_log("order_import", f"Enqueued {imported} order import job(s).")

    def _walmart_import_order(self, purchase_order_id):
        """Fetch a Walmart order and import it as a native sale.order.

        Builds a ``sale.import.payload`` matching the ``sale_import_base`` schema
        and runs it through the standard importer, which creates the sale order,
        the ``sale.channel.partner`` binding and (optionally) confirms/invoices.
        """
        self.ensure_one()
        existing = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", purchase_order_id),
                ("sale_channel_id", "=", self.id),
            ],
            limit=1,
        )
        if existing:
            _logger.info(
                "Walmart order %s already imported (SO %s); skipping.",
                purchase_order_id,
                existing.name,
            )
            return existing

        # Let API errors propagate so the queue job retries instead of silently
        # dropping the order (the poll cursor has already advanced).
        response = self._walmart_request("GET", f"/v3/orders/{purchase_order_id}")
        order_data = (response or {}).get("order", {}) or {}
        data = self._walmart_order_to_payload(purchase_order_id, order_data)
        if not data["lines"]:
            _logger.info(
                "Walmart order %s has no importable lines; skipping.",
                purchase_order_id,
            )
            return self.env["sale.import.payload"]
        # _create_import_payload (sale_marketplace_import) enqueues its own
        # processing job, so we do not call process() here. The marketplace-
        # collected (facilitator) tax is carried on the payload so the importer
        # can stamp it on the order for reporting/reconciliation.
        collected_tax = self._walmart_order_collected_tax(order_data)
        return self._create_import_payload(data, walmart_collected_tax=collected_tax)

    def _walmart_order_collected_tax(self, order_data):
        """Total sales tax Walmart collected (as a facilitator) for an order."""
        return sum(
            self._walmart_sum_charges(line, "TAX")
            for line in self._walmart_order_lines(order_data)
        )

    def _walmart_order_to_payload(self, purchase_order_id, order_data):
        """Map Walmart order data to the sale_import_base SaleOrder schema dict."""
        self.ensure_one()
        shipping_info = order_data.get("shippingInfo", {}) or {}
        postal = shipping_info.get("postalAddress", {}) or {}
        country = (postal.get("country") or "").upper()
        country_code = _COUNTRY_MAP.get(country) or (country[:2] if country else "US")
        state_code = postal.get("state") or None
        # Forward only short state codes; full region names fail the state lookup.
        if state_code and len(state_code) > 3:
            state_code = None
        address = {
            "name": postal.get("name") or f"Walmart {purchase_order_id}",
            "street": postal.get("address1") or "",
            "street2": postal.get("address2") or None,
            "zip": postal.get("postalCode") or "",
            "city": postal.get("city") or "",
            "country_code": country_code,
            "state_code": state_code,
            "phone": shipping_info.get("phone") or None,
        }
        customer = dict(address, external_id=purchase_order_id)

        lines = []
        for line in self._walmart_order_lines(order_data):
            if self._walmart_line_is_skipped(line):
                continue
            item = line.get("item", {}) or {}
            sku = item.get("sku", "")
            qty = self._walmart_line_qty(line)
            total = self._walmart_line_product_charge(line)
            lines.append(
                {
                    "product_code": sku,
                    "qty": qty,
                    "price_unit": total / qty if qty else total,
                    "description": (
                        item.get("productName") or sku or "Walmart Product"
                    )[:255],
                }
            )

        return {
            "name": purchase_order_id,
            "address_customer": customer,
            "address_shipping": address,
            "address_invoicing": address,
            "lines": lines,
        }

    def _walmart_line_is_skipped(self, line):
        statuses = (line.get("orderLineStatuses", {}) or {}).get(
            "orderLineStatus", []
        ) or []
        line_states = {s.get("status") for s in statuses}
        # Skip only when every reported status is a skip status (e.g. fully
        # cancelled); a mixed line still ships its non-cancelled quantity.
        return bool(line_states) and line_states.issubset(_LINE_SKIP_STATUSES)

    def _walmart_line_qty(self, line):
        qty_node = line.get("orderLineQuantity", {}) or {}
        return self._walmart_float(qty_node.get("amount"), 1.0)

    def _walmart_line_product_charge(self, line):
        """Sum the PRODUCT charge amount(s) for a Walmart order line."""
        return self._walmart_sum_charges(line, "PRODUCT")

    # ------------------------------------------------------------------
    # Order acknowledgement
    #
    # Walmart auto-cancels orders that are not acknowledged within its SLA, so
    # acknowledgement is a required step in the order pipeline (no Amazon
    # equivalent). We acknowledge every order line and stamp the Odoo order.
    # ------------------------------------------------------------------
    def _walmart_acknowledge_order(self, purchase_order_id, order=None, token=None):
        """Acknowledge a Walmart order's lines and stamp the Odoo order."""
        self.ensure_one()
        token = token or self._walmart_get_token()
        order_data = self._walmart_fetch_order(purchase_order_id, token=token)
        ack_lines = [
            self._walmart_line_status(line, "Acknowledged")
            for line in self._walmart_order_lines(order_data)
        ]
        if not ack_lines:
            _logger.warning(
                "Walmart order %s has no lines to acknowledge; skipping.",
                purchase_order_id,
            )
            return False

        payload = {"orderAcknowledgement": {"orderLines": {"orderLine": ack_lines}}}
        self._walmart_request(
            "POST",
            f"/v3/orders/{purchase_order_id}/acknowledge",
            payload=payload,
            token=token,
        )
        order = order or self.env["sale.order"].search(
            [
                ("client_order_ref", "=", purchase_order_id),
                ("sale_channel_id", "=", self.id),
            ],
            limit=1,
        )
        if order:
            order.walmart_acknowledged = fields.Datetime.now()
        _logger.info("Acknowledged Walmart order %s.", purchase_order_id)
        return True

    @api.model
    def _cron_walmart_acknowledge_orders(self):
        """Acknowledge imported-but-unacknowledged orders per active channel."""
        channels = self.search(
            [
                ("channel_type", "=", "walmart"),
                ("active", "=", True),
                ("walmart_auto_acknowledge", "=", True),
            ]
        )
        for channel in channels:
            orders = self.env["sale.order"].search(
                [
                    ("sale_channel_id", "=", channel.id),
                    ("client_order_ref", "!=", False),
                    ("walmart_acknowledged", "=", False),
                ]
            )
            for order in orders:
                channel.with_delay(
                    description=f"Acknowledge Walmart order {order.client_order_ref}"
                )._walmart_acknowledge_order(order.client_order_ref, order=order)

    # ------------------------------------------------------------------
    # Order cancellation (W4)
    #
    # When a Walmart order is cancelled in Odoo, push the cancellation back to
    # Walmart so the marketplace order is cancelled too (every line, full qty).
    # ------------------------------------------------------------------
    def _walmart_cancel_order(self, purchase_order_id, order=None, token=None):
        """Cancel a Walmart order's lines and stamp the Odoo order."""
        self.ensure_one()
        if order and order.walmart_cancelled:
            return False
        token = token or self._walmart_get_token()
        order_data = self._walmart_fetch_order(purchase_order_id, token=token)
        cancel_lines = [
            self._walmart_line_status(
                line, "Cancelled", {"cancellationReason": _WALMART_CANCEL_REASON}
            )
            for line in self._walmart_order_lines(order_data)
        ]
        if not cancel_lines:
            _logger.warning(
                "Walmart order %s has no lines to cancel; skipping.",
                purchase_order_id,
            )
            return False

        payload = {"orderCancellation": {"orderLines": {"orderLine": cancel_lines}}}
        self._walmart_request(
            "POST",
            f"/v3/orders/{purchase_order_id}/cancel",
            payload=payload,
            token=token,
        )
        order = order or self.env["sale.order"].search(
            [
                ("client_order_ref", "=", purchase_order_id),
                ("sale_channel_id", "=", self.id),
            ],
            limit=1,
        )
        if order:
            order.walmart_cancelled = fields.Datetime.now()
        _logger.info("Cancelled Walmart order %s.", purchase_order_id)
        return True
