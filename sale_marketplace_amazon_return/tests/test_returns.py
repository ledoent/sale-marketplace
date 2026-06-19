# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_return.models.sale_channel"

RETURNS_XML = """<Returns>
  <Return>
    <RMAId>RMA-1</RMAId>
    <AmazonOrderId>ORDER-1</AmazonOrderId>
    <Item><SKU>SKU-1</SKU><Quantity>1</Quantity><Reason>Defective</Reason></Item>
  </Return>
</Returns>"""

RETURNS_XML_NO_QTY = """<Returns>
  <Return>
    <RMAId>RMA-2</RMAId>
    <AmazonOrderId>ORDER-1</AmazonOrderId>
    <Item><SKU>SKU-1</SKU><Reason>Defective</Reason></Item>
  </Return>
</Returns>"""


@tagged("post_install", "-at_install")
class TestReturns(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER1",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "warehouse_id": cls.warehouse.id,
                "amazon_returns_enabled": True,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "default_code": "SKU-1",
                "is_storable": True,
                "invoice_policy": "order",
                "taxes_id": [(6, 0, [])],
                "property_account_income_id": cls.company_data[
                    "default_account_revenue"
                ].id,
            }
        )

    def _report(self):
        return self.env["sale.channel.return.report"].create(
            {
                "sale_channel_id": self.channel.id,
                "amazon_report_id": "R1",
                "state": "requested",
            }
        )

    def _ret(self, rma="RMA-1"):
        return self.env["sale.channel.return"].search(
            [("sale_channel_id", "=", self.channel.id), ("rma_id", "=", rma)]
        )

    def _invoiced_order(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "sale_channel_id": self.channel.id,
                "client_order_ref": "ORDER-1",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": 50.0,
                        },
                    )
                ],
            }
        )
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        return order

    # ---- parsing ----
    def test_parse_creates_return_and_lines(self):
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        ret = self._ret()
        self.assertEqual(len(ret), 1)
        self.assertEqual(ret.amazon_order_id, "ORDER-1")
        self.assertEqual(ret.line_ids.product_id, self.product)
        self.assertEqual(ret.line_ids.quantity, 1)

    def test_parse_missing_quantity_defaults_to_zero(self):
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML_NO_QTY)
        self.assertEqual(self._ret("RMA-2").line_ids.quantity, 0)  # no over-restock

    def test_parse_idempotent(self):
        report = self._report()
        self.channel._amazon_parse_returns_xml(report, RETURNS_XML)
        self.channel._amazon_parse_returns_xml(report, RETURNS_XML)
        self.assertEqual(len(self._ret()), 1)

    @mute_logger(_MODEL_PATH)
    def test_xml_parse_error_surfaced(self):
        report = self._report()
        self.channel._amazon_parse_returns_xml(report, "<Returns><broken")
        self.assertEqual(report.state, "error")
        self.assertTrue(report.error_message)

    # ---- automation ----
    def test_auto_restock_picking(self):
        self.channel.amazon_auto_return_picking = True
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        ret = self._ret()
        self.assertTrue(ret.return_picking_id)
        self.assertEqual(ret.state, "picking_created")

    def test_auto_credit_note(self):
        self._invoiced_order()
        self.channel.amazon_auto_credit_note = True
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        ret = self._ret()
        self.assertTrue(ret.credit_note_id)
        self.assertEqual(ret.credit_note_id.move_type, "out_refund")
        self.assertEqual(ret.state, "credited")

    def test_no_credit_without_invoice(self):
        self.channel.amazon_auto_credit_note = True
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        ret = self._ret()
        self.assertFalse(ret.credit_note_id)
        self.assertEqual(ret.state, "new")

    def test_reingest_self_heals_credit(self):
        # first ingest: no invoice yet -> state new
        self.channel.amazon_auto_credit_note = True
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        self.assertEqual(self._ret().state, "new")
        # invoice the order, re-ingest -> credit note now created
        self._invoiced_order()
        self.channel._amazon_parse_returns_xml(self._report(), RETURNS_XML)
        self.assertTrue(self._ret().credit_note_id)

    # ---- reports flow ----
    def test_pull_returns_full_flow(self):
        api = MagicMock()
        api.create_report.return_value.payload = {"reportId": "R1"}
        api.get_report.return_value.payload = {
            "processingStatus": "DONE",
            "reportDocumentId": "D1",
        }
        api.get_report_document.return_value.payload = RETURNS_XML
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_pull_returns()
        self.assertTrue(self._ret())

    def test_report_fatal_sets_error(self):
        report = self._report()
        api = MagicMock()
        api.get_report.return_value.payload = {"processingStatus": "FATAL"}
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_fetch_returns_reports()
        self.assertEqual(report.state, "error")
