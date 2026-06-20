# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import logging
from uuid import uuid4

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_PROD_URL = "https://marketplace.walmartapis.com"
_SANDBOX_URL = "https://sandbox.walmartapis.com"
_TIMEOUT = 60


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    channel_type = fields.Selection(
        selection_add=[("walmart", "Walmart")],
        ondelete={"walmart": "set null"},
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        help="Warehouse fulfilling and stocking this Walmart channel.",
    )
    walmart_client_id = fields.Char("Walmart Client ID")
    walmart_client_secret = fields.Char(groups="base.group_system")
    walmart_sandbox = fields.Boolean(
        "Walmart Sandbox Mode",
        help="Use the Walmart Marketplace sandbox endpoints.",
    )
    walmart_market = fields.Selection(
        [("us", "United States"), ("ca", "Canada"), ("mx", "Mexico")],
        default="us",
        required=True,
        help="Walmart marketplace region, sent as the WM_MARKET header so one "
        "connector can serve US, Canada and Mexico from the same API host.",
    )

    @api.model
    def _marketplace_channel_types(self):
        return super()._marketplace_channel_types() + ["walmart"]

    def _walmart_log(self, operation, message, level="info", reference=False):
        """Record a Walmart sync/mismatch log entry.

        Uses sudo so scheduled/queued jobs log regardless of the acting user.
        Feature modules call this at sync boundaries and on mismatches that would
        otherwise only reach the server log.
        """
        self.ensure_one()
        return (
            self.env["sale.channel.walmart.log"]
            .sudo()
            .create(
                {
                    "sale_channel_id": self.id,
                    "operation": operation,
                    "level": level,
                    "message": message,
                    "reference": reference or False,
                }
            )
        )

    # ------------------------------------------------------------------
    # Thin Walmart Marketplace REST client (OAuth2 client-credentials)
    # ------------------------------------------------------------------
    def _walmart_base_url(self):
        self.ensure_one()
        return _SANDBOX_URL if self.walmart_sandbox else _PROD_URL

    def _walmart_basic_auth(self):
        self.ensure_one()
        raw = f"{self.walmart_client_id}:{self.walmart_client_secret}".encode()
        return base64.b64encode(raw).decode()

    def _walmart_get_token(self):
        """Fetch an OAuth2 client-credentials access token."""
        self.ensure_one()
        try:
            response = requests.post(
                f"{self._walmart_base_url()}/v3/token",
                headers={
                    "Authorization": f"Basic {self._walmart_basic_auth()}",
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "WM_SVC.NAME": "Walmart Marketplace",
                    "WM_QOS.CORRELATION_ID": str(uuid4()),
                    "WM_MARKET": self.walmart_market or "us",
                },
                data={"grant_type": "client_credentials"},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(_("Walmart token request failed: %s") % exc) from exc
        return (response.json() or {}).get("access_token")

    def _walmart_request(self, method, path, params=None, payload=None, token=None):
        """Call a Walmart Marketplace endpoint and return the parsed JSON."""
        self.ensure_one()
        token = token or self._walmart_get_token()
        headers = {
            "Authorization": f"Basic {self._walmart_basic_auth()}",
            "WM_SEC.ACCESS_TOKEN": token or "",
            "WM_QOS.CORRELATION_ID": str(uuid4()),
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_MARKET": self.walmart_market or "us",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response = requests.request(
                method,
                f"{self._walmart_base_url()}{path}",
                headers=headers,
                params=params,
                json=payload,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(_("Walmart API request failed: %s") % exc) from exc
        return response.json() if response.content else {}

    # ------------------------------------------------------------------
    # Shared Walmart-API parse/build helpers
    #
    # Walmart's order endpoints share the same line/charge/status shapes, so the
    # parsing and the per-line status-payload builder live here (in the base) and
    # are reused by the order, stock, return and payment connectors rather than
    # re-implemented per module (avoids silent drift on the API contract).
    # ------------------------------------------------------------------
    @staticmethod
    def _walmart_float(value, default=0.0):
        """Coerce a Walmart numeric (str/number/None) to float, else ``default``."""
        try:
            return float(value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _walmart_order_lines(order_data):
        """Return the list of order lines from a Walmart order payload."""
        return (order_data.get("orderLines", {}) or {}).get("orderLine", []) or []

    def _walmart_fetch_order(self, purchase_order_id, token=None):
        """GET a single Walmart order and return its ``order`` dict."""
        self.ensure_one()
        token = token or self._walmart_get_token()
        response = (
            self._walmart_request("GET", f"/v3/orders/{purchase_order_id}", token=token)
            or {}
        )
        return response.get("order", {}) or {}

    def _walmart_sum_charges(self, line, charge_type, with_currency=False):
        """Sum a Walmart order line's charge amounts for ``charge_type``."""
        total = 0.0
        currency = "USD"
        for charge in (line.get("charges", {}) or {}).get("charge", []) or []:
            if charge.get("chargeType") != charge_type:
                continue
            node = charge.get("chargeAmount", {}) or {}
            currency = node.get("currency") or currency
            total += self._walmart_float(node.get("amount"))
        return (total, currency) if with_currency else total

    def _walmart_line_status(self, line, status, extra=None):
        """Build one orderLine status entry (acknowledge/cancel/ship share this).

        ``extra`` merges extra keys into the orderLineStatus (e.g.
        ``cancellationReason`` or ``trackingInfo``).
        """
        qty_node = line.get("orderLineQuantity", {}) or {}
        order_line_status = {
            "status": status,
            "statusQuantity": {
                "unitOfMeasurement": qty_node.get("unitOfMeasurement", "EACH"),
                "amount": qty_node.get("amount", "1"),
            },
        }
        if extra:
            order_line_status.update(extra)
        return {
            "lineNumber": line.get("lineNumber"),
            "orderLineStatuses": {"orderLineStatus": [order_line_status]},
        }

    def action_walmart_test_connection(self):
        self.ensure_one()
        token = self._walmart_get_token()
        ok = bool(token)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Walmart"),
                "message": _("Connection successful.")
                if ok
                else _("No access token returned."),
                "type": "success" if ok else "warning",
                "sticky": False,
            },
        }
