# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    amazon_returns_enabled = fields.Boolean()
    amazon_auto_return_picking = fields.Boolean("Auto Restock Picking")
    amazon_auto_credit_note = fields.Boolean("Auto Credit Note")
    last_return_sync_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # XML helpers (namespace-resilient)
    # ------------------------------------------------------------------
    @staticmethod
    def _amazon_return_local(tag):
        return tag.split("}")[-1].lower()

    def _amazon_return_ftext(self, elem, name):
        name = name.lower()
        for node in elem.iter():
            if (
                self._amazon_return_local(node.tag) == name
                and (node.text or "").strip()
            ):
                return node.text.strip()
        return ""

    @staticmethod
    def _amazon_return_int(value):
        # missing/invalid quantity -> 0 so we never silently restock a unit
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Parse + upsert
    # ------------------------------------------------------------------
    def _amazon_parse_returns_xml(self, report, xml_text):
        self.ensure_one()
        try:
            root = ET.fromstring(xml_text or "")
        except ET.ParseError as exc:
            # surface the parse error on the report instead of swallowing it
            report.write({"state": "error", "error_message": str(exc)})
            _logger.warning("Amazon returns XML parse error: %s", exc)
            return
        nodes = [n for n in root.iter() if self._amazon_return_local(n.tag) == "return"]
        if not nodes:
            nodes = [root]
        for node in nodes:
            rma = self._amazon_return_ftext(node, "RMAId") or self._amazon_return_ftext(
                node, "rma"
            )
            if not rma:
                continue
            amazon_order_id = self._amazon_return_ftext(node, "AmazonOrderId")
            line_vals = []
            items = [
                c for c in node.iter() if self._amazon_return_local(c.tag) == "item"
            ]
            for item in items:
                sku = self._amazon_return_ftext(
                    item, "SKU"
                ) or self._amazon_return_ftext(item, "SellerSKU")
                quantity = self._amazon_return_int(
                    self._amazon_return_ftext(item, "Quantity")
                )
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
                        "quantity": quantity,
                        "return_reason": self._amazon_return_ftext(item, "Reason"),
                    }
                )
            self._amazon_upsert_return(rma, amazon_order_id, line_vals)
        report.state = "parsed"

    def _amazon_upsert_return(self, rma, amazon_order_id, line_vals):
        self.ensure_one()
        order = (
            self.env["sale.order"].search(
                [
                    ("client_order_ref", "=", amazon_order_id),
                    ("sale_channel_id", "=", self.id),
                ],
                limit=1,
            )
            if amazon_order_id
            else self.env["sale.order"]
        )
        ret = self.env["sale.channel.return"].search(
            [("sale_channel_id", "=", self.id), ("rma_id", "=", rma)], limit=1
        )
        if ret:
            if order and not ret.order_id:
                ret.order_id = order.id
        else:
            ret = self.env["sale.channel.return"].create(
                {
                    "sale_channel_id": self.id,
                    "rma_id": rma,
                    "amazon_order_id": amazon_order_id,
                    "order_id": order.id or False,
                    "line_ids": [(0, 0, v) for v in line_vals],
                }
            )
        self._amazon_run_return_automation(ret)
        return ret

    # ------------------------------------------------------------------
    # Automation (state always reflects what was actually created)
    # ------------------------------------------------------------------
    @staticmethod
    def _amazon_return_state(ret):
        if ret.return_picking_id and ret.credit_note_id:
            return "done"
        if ret.credit_note_id:
            return "credited"
        if ret.return_picking_id:
            return "picking_created"
        return "new"

    def _amazon_run_return_automation(self, ret):
        self.ensure_one()
        if self.amazon_auto_return_picking and not ret.return_picking_id:
            try:
                picking = self._amazon_create_return_picking(ret)
            except (
                Exception
            ) as exc:  # pragma: no cover - logged; state stays consistent
                _logger.warning("Return restock failed for %s: %s", ret.rma_id, exc)
                picking = False
            if picking:
                ret.return_picking_id = picking.id
        if self.amazon_auto_credit_note and not ret.credit_note_id:
            try:
                credit_note = self._amazon_create_credit_note(ret)
            except (
                Exception
            ) as exc:  # pragma: no cover - logged; state stays consistent
                _logger.warning("Return credit failed for %s: %s", ret.rma_id, exc)
                credit_note = False
            if credit_note:
                ret.credit_note_id = credit_note.id
        ret.state = self._amazon_return_state(ret)

    def _amazon_create_return_picking(self, ret):
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
                "origin": ret.rma_id,
                "move_ids": moves,
            }
        )
        picking.action_confirm()
        return picking

    def _amazon_create_credit_note(self, ret):
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
        credit_note = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "partner_id": invoices[0].partner_id.id,
                "invoice_origin": ret.rma_id,
                "invoice_line_ids": cn_lines,
            }
        )
        credit_note.action_post()
        return credit_note

    # ------------------------------------------------------------------
    # Reports flow
    # ------------------------------------------------------------------
    def _amazon_returns_document_text(self, doc):
        payload = getattr(doc, "payload", doc)
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return payload.get("document") or payload.get("Contents") or ""
        return ""

    def _amazon_request_returns_report(self):
        self.ensure_one()
        from sp_api.api import Reports

        api = self._amazon_get_api(Reports)
        start = self.last_return_sync_date or (
            fields.Datetime.now() - timedelta(days=30)
        )
        try:
            result = api.create_report(
                reportType="GET_XML_RETURNS_DATA_BY_RETURN_DATE",
                dataStartTime=start.isoformat(),
                marketplaceIds=[self.amazon_marketplace_id],
            )
        except Exception as exc:  # pragma: no cover - logged and skipped
            _logger.warning("Amazon create returns report failed: %s", exc)
            return self.env["sale.channel.return.report"]
        return self.env["sale.channel.return.report"].create(
            {
                "sale_channel_id": self.id,
                "amazon_report_id": (result.payload or {}).get("reportId"),
                "state": "requested",
            }
        )

    def _amazon_fetch_returns_reports(self):
        self.ensure_one()
        from sp_api.api import Reports

        api = self._amazon_get_api(Reports)
        pending = self.env["sale.channel.return.report"].search(
            [("sale_channel_id", "=", self.id), ("state", "=", "requested")]
        )
        for report in pending:
            try:
                status = api.get_report(report.amazon_report_id).payload or {}
            except Exception as exc:  # pragma: no cover - logged and skipped
                _logger.warning("Amazon get_report failed: %s", exc)
                continue
            processing = status.get("processingStatus")
            if processing in ("CANCELLED", "FATAL"):
                report.write({"state": "error", "error_message": processing})
                continue
            if processing != "DONE":
                continue
            report.write(
                {"state": "done", "document_id": status.get("reportDocumentId")}
            )
            try:
                doc = api.get_report_document(report.document_id, decrypt=True)
                text = self._amazon_returns_document_text(doc)
            except Exception as exc:  # pragma: no cover - logged and skipped
                report.write({"state": "error", "error_message": str(exc)})
                continue
            self._amazon_parse_returns_xml(report, text)
            # only advance the cursor when the report actually parsed; a parse
            # error must not skip the window (it would lose those returns).
            if report.state == "parsed":
                self.last_return_sync_date = fields.Datetime.now()

    def _amazon_pull_returns(self):
        self.ensure_one()
        self._amazon_request_returns_report()
        self._amazon_fetch_returns_reports()

    def action_amazon_sync_returns(self):
        self.ensure_one()
        self.with_delay()._amazon_pull_returns()
        return True

    @api.model
    def _cron_amazon_sync_returns(self):
        channels = self.search(
            [("channel_type", "=", "amazon"), ("amazon_returns_enabled", "=", True)]
        )
        for channel in channels:
            channel._amazon_pull_returns()
