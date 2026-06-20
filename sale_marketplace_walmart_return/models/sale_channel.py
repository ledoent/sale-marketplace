# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta
from uuid import uuid4

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    walmart_returns_enabled = fields.Boolean()
    # Labels humanize to "Walmart Auto ..." -> distinct from the Amazon return
    # module's "Auto ..." labels (avoids the ir_model same-label checklog warning).
    walmart_auto_return_picking = fields.Boolean()
    walmart_auto_credit_note = fields.Boolean()
    walmart_auto_refund = fields.Boolean()
    walmart_last_return_sync_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # Parse helpers
    # ------------------------------------------------------------------
    def _walmart_return_qty(self, node):
        # missing/invalid quantity -> 0 so we never silently restock a unit
        return self._walmart_float((node or {}).get("measurementValue"))

    def _walmart_return_line_vals(self, return_lines):
        self.ensure_one()
        line_vals = []
        for line in return_lines:
            item = line.get("item", {}) or {}
            sku = item.get("sku")
            product = (
                self.env["product.product"].search(
                    [("default_code", "=", sku)], limit=1
                )
                if sku
                else self.env["product.product"]
            )
            line_vals.append(
                {
                    "product_id": product.id or False,
                    "seller_sku": sku,
                    "quantity": self._walmart_return_qty(line.get("returnQuantity")),
                    "return_reason": line.get("returnReason"),
                }
            )
        return line_vals

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------
    def _walmart_upsert_return(self, return_order_id, purchase_order_id, line_vals):
        self.ensure_one()
        order = (
            self.env["sale.order"].search(
                [
                    ("client_order_ref", "=", purchase_order_id),
                    ("sale_channel_id", "=", self.id),
                ],
                limit=1,
            )
            if purchase_order_id
            else self.env["sale.order"]
        )
        ret = self.env["sale.channel.walmart.return"].search(
            [
                ("sale_channel_id", "=", self.id),
                ("return_order_id", "=", return_order_id),
            ],
            limit=1,
        )
        if ret:
            if order and not ret.order_id:
                ret.order_id = order.id
        else:
            ret = self.env["sale.channel.walmart.return"].create(
                {
                    "sale_channel_id": self.id,
                    "return_order_id": return_order_id,
                    "purchase_order_id": purchase_order_id,
                    "order_id": order.id or False,
                    "line_ids": [(0, 0, v) for v in line_vals],
                }
            )
        self._walmart_run_return_automation(ret)
        return ret

    # ------------------------------------------------------------------
    # Automation (state always reflects what was actually created)
    # ------------------------------------------------------------------
    @staticmethod
    def _walmart_return_state(ret):
        if ret.return_picking_id and ret.credit_note_id:
            return "done"
        if ret.credit_note_id:
            return "credited"
        if ret.return_picking_id:
            return "picking_created"
        return "new"

    def _walmart_run_return_automation(self, ret):
        self.ensure_one()
        if self.walmart_auto_return_picking and not ret.return_picking_id:
            try:
                picking = self._walmart_create_return_picking(ret)
            except Exception as exc:
                _logger.warning(
                    "Return restock failed for %s: %s", ret.return_order_id, exc
                )
                picking = False
            if picking:
                ret.return_picking_id = picking.id
        if self.walmart_auto_credit_note and not ret.credit_note_id:
            try:
                credit_note = self._walmart_create_credit_note(ret)
            except Exception as exc:
                _logger.warning(
                    "Return credit failed for %s: %s", ret.return_order_id, exc
                )
                credit_note = False
            if credit_note:
                ret.credit_note_id = credit_note.id
        if self.walmart_auto_refund and not ret.walmart_refund_issued:
            try:
                self._walmart_issue_refund(ret)
            except Exception as exc:
                _logger.warning(
                    "Return refund push failed for %s: %s", ret.return_order_id, exc
                )
        ret.state = self._walmart_return_state(ret)

    def _walmart_create_return_picking(self, ret):
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse:
            return False
        customer_loc = self.env.ref("stock.stock_location_customers")
        dest = warehouse.lot_stock_id
        moves = []
        for line in ret.line_ids:
            if not line.product_id or line.quantity <= 0:
                continue
            moves.append(
                (
                    0,
                    0,
                    {
                        "name": line.product_id.display_name,
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.quantity,
                        "product_uom": line.product_id.uom_id.id,
                        "location_id": customer_loc.id,
                        "location_dest_id": dest.id,
                    },
                )
            )
        if not moves:
            return False
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.in_type_id.id,
                "location_id": customer_loc.id,
                "location_dest_id": dest.id,
                "origin": ret.return_order_id,
                "move_ids": moves,
            }
        )
        picking.action_confirm()
        return picking

    def _walmart_create_credit_note(self, ret):
        self.ensure_one()
        order = ret.order_id
        if not order:
            return False
        invoices = order.invoice_ids.filtered(
            lambda m: m.move_type == "out_invoice" and m.state == "posted"
        )
        if not invoices:
            return False
        # match return lines against ALL posted invoices of the order (orders can
        # be invoiced across several invoices), and carry the original discount.
        invoice_lines = invoices.invoice_line_ids
        cn_lines = []
        for line in ret.line_ids:
            if not line.product_id or line.quantity <= 0:
                continue
            inv_line = invoice_lines.filtered(
                lambda il, line=line: il.product_id == line.product_id
            )[:1]
            if not inv_line:
                continue
            cn_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "quantity": line.quantity,
                        "price_unit": inv_line.price_unit,
                        "discount": inv_line.discount,
                        "tax_ids": [(6, 0, inv_line.tax_ids.ids)],
                    },
                )
            )
        if not cn_lines:
            return False
        # Inherit company/currency from the source invoice so multi-company /
        # non-company-currency credit notes land in the right books.
        source_invoice = invoices[0]
        credit_note = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "partner_id": source_invoice.partner_id.id,
                "company_id": source_invoice.company_id.id,
                "currency_id": source_invoice.currency_id.id,
                "invoice_origin": ret.return_order_id,
                "invoice_line_ids": cn_lines,
            }
        )
        credit_note.action_post()
        return credit_note

    # ------------------------------------------------------------------
    # Refund issuance (W3)
    #
    # Pushes the money back to the buyer on Walmart via the Refund API. We map
    # each return line to its Walmart order line (by SKU) and refund the PRODUCT
    # charge prorated to the returned quantity.
    # ------------------------------------------------------------------
    def _walmart_refund_amount(self, order_line, refund_qty):
        """Refund the PRODUCT charge prorated to the returned quantity."""
        total, currency = self._walmart_sum_charges(
            order_line, "PRODUCT", with_currency=True
        )
        qty_node = order_line.get("orderLineQuantity", {}) or {}
        order_qty = self._walmart_float(qty_node.get("amount"), 1.0)
        if refund_qty >= order_qty or order_qty <= 0:
            amount = total
        else:
            amount = total * refund_qty / order_qty
        return round(amount, 2), currency

    def _walmart_issue_refund(self, ret):
        """Issue a Walmart refund for the return's lines and stamp the return."""
        self.ensure_one()
        if ret.walmart_refund_issued:
            return False
        purchase_order_id = ret.purchase_order_id
        if not purchase_order_id:
            _logger.warning(
                "Walmart return %s has no purchase order; cannot refund.",
                ret.return_order_id,
            )
            return False
        token = self._walmart_get_token()
        order_data = self._walmart_fetch_order(purchase_order_id, token=token)
        by_sku = {
            (line.get("item", {}) or {}).get("sku"): line
            for line in self._walmart_order_lines(order_data)
            if (line.get("item", {}) or {}).get("sku")
        }
        refund_id = uuid4().hex
        refund_lines = []
        for line in ret.line_ids:
            if not line.product_id or line.quantity <= 0:
                continue
            order_line = by_sku.get(line.seller_sku)
            if not order_line:
                continue
            amount, currency = self._walmart_refund_amount(order_line, line.quantity)
            if amount <= 0:
                continue
            refund_lines.append(
                {
                    "lineNumber": order_line.get("lineNumber"),
                    "refunds": {
                        "refund": [
                            {
                                "refundId": refund_id,
                                "refundComments": line.return_reason or "Return refund",
                                "refundCharges": {
                                    "refundCharge": [
                                        {
                                            "refundReason": line.return_reason
                                            or "BuyerCancel",
                                            "charge": {
                                                "chargeType": "PRODUCT",
                                                "chargeName": "ItemPrice",
                                                "chargeAmount": {
                                                    "currency": currency,
                                                    "amount": amount,
                                                },
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            )
        if not refund_lines:
            _logger.warning(
                "Walmart return %s: no refundable lines; skipping refund.",
                ret.return_order_id,
            )
            return False
        payload = {
            "orderRefund": {
                "purchaseOrderId": purchase_order_id,
                "orderLines": {"orderLine": refund_lines},
            }
        }
        self._walmart_request(
            "POST",
            f"/v3/orders/{purchase_order_id}/refund",
            payload=payload,
            token=token,
        )
        ret.write(
            {
                "walmart_refund_id": refund_id,
                "walmart_refund_issued": fields.Datetime.now(),
            }
        )
        _logger.info(
            "Issued Walmart refund for return %s (order %s).",
            ret.return_order_id,
            purchase_order_id,
        )
        return True

    # ------------------------------------------------------------------
    # Pull flow
    # ------------------------------------------------------------------
    def _walmart_pull_returns(self):
        self.ensure_one()
        token = self._walmart_get_token()
        since = self.walmart_last_return_sync_date or (
            fields.Datetime.now() - timedelta(days=30)
        )
        poll_start = fields.Datetime.now()
        next_cursor = None
        processed = 0
        parsed_any = False
        while True:
            if next_cursor:
                response = self._walmart_request(
                    "GET", "/v3/returns" + next_cursor, token=token
                )
            else:
                response = self._walmart_request(
                    "GET",
                    "/v3/returns",
                    params={
                        "returnLastModifiedStartDate": since.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "limit": 100,
                    },
                    token=token,
                )
            response = response or {}
            for return_order in response.get("returnOrders", []) or []:
                return_order_id = return_order.get("returnOrderId")
                if not return_order_id:
                    continue
                line_vals = self._walmart_return_line_vals(
                    return_order.get("returnOrderLines", []) or []
                )
                self._walmart_upsert_return(
                    return_order_id,
                    return_order.get("customerOrderId"),
                    line_vals,
                )
                processed += 1
                parsed_any = True
            next_cursor = (response.get("meta", {}) or {}).get("nextCursor")
            if not next_cursor:
                break
        # advance the cursor only when at least one page parsed cleanly, so a
        # transient empty/failed pull never skips returns in the window.
        if parsed_any:
            self.walmart_last_return_sync_date = poll_start
        self._walmart_log("returns_sync", f"Processed {processed} return(s).")
        return processed

    def action_walmart_sync_returns(self):
        self.ensure_one()
        self.with_delay(
            description=f"Sync Walmart returns for {self.display_name}"
        )._walmart_pull_returns()
        return True

    @api.model
    def _cron_walmart_sync_returns(self):
        channels = self.search(
            [
                ("channel_type", "=", "walmart"),
                ("active", "=", True),
                ("walmart_returns_enabled", "=", True),
            ]
        )
        for channel in channels:
            channel.with_delay(
                description=f"Sync Walmart returns for {channel.display_name}"
            )._walmart_pull_returns()
