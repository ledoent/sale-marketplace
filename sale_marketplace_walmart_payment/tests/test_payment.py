# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.queue_job.tests.common import trap_jobs

_BASE = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"
_PAY = "odoo.addons.sale_marketplace_walmart_payment.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_walmart_payment.models.sale_channel"


def _txn(desc, amount, settlement="S1", po="PO-1", ttype="Sale"):
    return {
        "settlementId": settlement,
        "purchaseOrderId": po,
        "transactionType": ttype,
        "transactionDescription": desc,
        "amount": amount,
        "currency": "USD",
        "postedTimestamp": "2026-06-01T00:00:00Z",
    }


def _transactions(principal=100.0):
    return [
        _txn("Product", principal),
        _txn("Tax", 8.0),
        _txn("Commission", -15.0),
    ]


@tagged("post_install", "-at_install")
class TestPayment(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        revenue = cls.company_data["default_account_revenue"]
        expense = cls.company_data["default_account_expense"]
        cls.revenue = revenue
        cls.expense = expense
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
                "walmart_settlement_journal_id": cls.company_data[
                    "default_journal_bank"
                ].id,
                "walmart_income_account_id": revenue.id,
                "walmart_fee_account_id": expense.id,
                "walmart_tax_account_id": revenue.id,
                "walmart_shipping_account_id": revenue.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "invoice_policy": "order",
                "taxes_id": [(6, 0, [])],
                "property_account_income_id": revenue.id,
            }
        )

    def _run(self, transactions=None):
        txns = transactions if transactions is not None else _transactions()
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", return_value={"transactions": txns}),
        ):
            return self.channel._walmart_pull_settlements()

    def _group(self, settlement="S1"):
        return self.env["sale.channel.walmart.settlement.group"].search(
            [
                ("sale_channel_id", "=", self.channel.id),
                ("walmart_settlement_id", "=", settlement),
            ]
        )

    def _make_invoiced_order(self, price=100.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "sale_channel_id": self.channel.id,
                "client_order_ref": "PO-1",
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": price,
                        },
                    )
                ],
            }
        )
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        return order, invoice

    # ---- classification helpers ----
    def test_event_type_classification(self):
        et = self.channel._walmart_event_type
        self.assertEqual(et("Sale", "Product"), "sale")
        self.assertEqual(et("Sale", "Commission"), "commission")
        self.assertEqual(et("Sale", "Shipping"), "shipping")
        self.assertEqual(et("Sale", "Sales Tax"), "tax")
        self.assertEqual(et("Refund", "Refund Principal"), "refund")
        self.assertEqual(et("Adjustment", "Misc"), "other")

    def test_money_coercion(self):
        self.assertEqual(self.channel._walmart_money("12.50"), 12.5)
        self.assertEqual(self.channel._walmart_money(None), 0.0)
        self.assertEqual(self.channel._walmart_money("bad"), 0.0)

    # ---- pull + parse ----
    def test_event_parsing(self):
        self._run()
        by_type = {e.event_type: e.amount for e in self._group().financial_event_ids}
        self.assertEqual(by_type.get("sale"), 100.0)
        self.assertEqual(by_type.get("tax"), 8.0)
        self.assertEqual(by_type.get("commission"), -15.0)

    # ---- GL entry ----
    def test_settlement_entry_balances_and_posts(self):
        self._run()
        move = self._group().account_move_id
        self.assertTrue(move)
        self.assertEqual(move.state, "posted")
        debit = sum(move.line_ids.mapped("debit"))
        credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(debit, credit)
        self.assertAlmostEqual(debit, 108.0)  # 100 income + 8 tax credited

    def test_fee_posts_to_fee_account_not_income(self):
        self._run()
        move = self._group().account_move_id
        fee_lines = move.line_ids.filtered(lambda line: line.account_id == self.expense)
        income_lines = move.line_ids.filtered(
            lambda line: line.account_id == self.revenue
        )
        self.assertAlmostEqual(sum(fee_lines.mapped("debit")), 15.0)
        self.assertAlmostEqual(sum(income_lines.mapped("credit")), 108.0)

    def test_fee_never_routed_to_income_when_no_fee_account(self):
        # With no fee account configured, the commission must NOT fall back to
        # income; it is dropped (absorbed by the bank offset), entry still balances.
        self.channel.walmart_fee_account_id = False
        self._run()
        move = self._group().account_move_id
        self.assertEqual(move.state, "posted")
        income_lines = move.line_ids.filtered(
            lambda line: line.account_id == self.revenue
        )
        # income credit stays sale(100)+tax(8); the -15 commission is not here
        self.assertAlmostEqual(sum(income_lines.mapped("credit")), 108.0)
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )

    def test_negative_refund_still_balances(self):
        txns = _transactions() + [_txn("Refund Principal", -20.0, ttype="Refund")]
        self._run(transactions=txns)
        move = self._group().account_move_id
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )

    def test_idempotent_reprocess(self):
        self._run()
        self._run()  # second pull: group exists + already booked
        self.assertEqual(len(self._group()), 1)
        self.assertEqual(len(self._group().account_move_id), 1)

    # ---- reconciliation ----
    def test_reconciliation_matched(self):
        _order, invoice = self._make_invoiced_order(price=100.0)
        self._run(transactions=_transactions(principal=invoice.amount_untaxed))
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "matched")
        self.assertEqual(recon.invoice_id, invoice)

    def test_reconciliation_variance(self):
        _order, invoice = self._make_invoiced_order(price=100.0)
        self._run(transactions=_transactions(principal=invoice.amount_untaxed + 5.0))
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "variance")
        self.assertAlmostEqual(recon.variance, 5.0)

    def test_reconciliation_no_invoice(self):
        self._run()  # PO-1 has no matching SO/invoice
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "no_invoice")

    # ---- cron + error paths ----
    def test_cron_syncs(self):
        with (
            trap_jobs() as trap,
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_BASE}._walmart_request",
                return_value={"transactions": _transactions()},
            ),
        ):
            self.env["sale.channel"]._cron_walmart_sync_settlements()
            trap.perform_enqueued_jobs()
        self.assertTrue(self._group())

    @mute_logger(_MODEL_PATH)
    def test_fetch_error_propagates(self):
        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", side_effect=ValueError("boom")),
        ):
            with self.assertRaises(ValueError):
                self.channel._walmart_pull_settlements()

    @mute_logger(_MODEL_PATH)
    def test_settlement_error_isolated(self):
        txns = _transactions() + [_txn("Product", 50.0, settlement="S2", po="PO-2")]
        orig = type(self.channel)._walmart_process_settlement_group

        def _side(channel, settlement_id, lines):
            if settlement_id == "S1":
                raise ValueError("boom")
            return orig(channel, settlement_id, lines)

        with (
            patch(f"{_BASE}._walmart_get_token", return_value="TOK"),
            patch(f"{_BASE}._walmart_request", return_value={"transactions": txns}),
            patch(
                f"{_PAY}._walmart_process_settlement_group",
                autospec=True,
                side_effect=_side,
            ),
        ):
            processed = self.channel._walmart_pull_settlements()
        # S1 raised and was isolated; S2 still processed.
        self.assertEqual(processed, 1)
        self.assertTrue(self._group("S2"))
        self.assertFalse(self._group("S1").account_move_id)
