# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.queue_job.tests.common import trap_jobs

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_payment.models.sale_channel"


def _groups(extra_open=False):
    groups = [
        {
            "FinancialEventGroupId": "G1",
            "ProcessingStatus": "Closed",
            "FundTransferDate": "2026-06-01T00:00:00Z",
            "OriginalTotal": {"CurrencyAmount": 93.0, "CurrencyCode": "USD"},
        }
    ]
    if extra_open:
        groups.append({"FinancialEventGroupId": "G2", "ProcessingStatus": "Open"})
    return {"FinancialEventGroupList": groups}


def _events(principal=100.0, refund=None):
    fe = {
        "ShipmentEventList": [
            {
                "AmazonOrderId": "ORDER-1",
                "PostedDate": "2026-06-01T00:00:00Z",
                "ShipmentItemList": [
                    {
                        "ItemChargeList": [
                            {
                                "ChargeType": "Principal",
                                "ChargeAmount": {"CurrencyAmount": principal},
                            },
                            {
                                "ChargeType": "Tax",
                                "ChargeAmount": {"CurrencyAmount": 8.0},
                            },
                        ],
                        "ItemFeeList": [
                            {
                                "FeeType": "Commission",
                                "FeeAmount": {"CurrencyAmount": -15.0},
                            },
                        ],
                    }
                ],
            }
        ]
    }
    if refund is not None:
        fe["RefundEventList"] = [
            {
                "AmazonOrderId": "ORDER-1",
                "PostedDate": "2026-06-02T00:00:00Z",
                "ShipmentItemAdjustmentList": [
                    {
                        "ItemChargeAdjustmentList": [
                            {
                                "ChargeType": "Principal",
                                "ChargeAmount": {"CurrencyAmount": refund},
                            },
                        ]
                    }
                ],
            }
        ]
    return {"FinancialEvents": fe}


@tagged("post_install", "-at_install")
class TestPayment(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        revenue = cls.company_data["default_account_revenue"]
        expense = cls.company_data["default_account_expense"]
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Amazon",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER1",
                "amazon_marketplace_id": "ATVPDKIKX0DER",
                "amazon_settlement_journal_id": cls.company_data[
                    "default_journal_bank"
                ].id,
                "amazon_income_account_id": revenue.id,
                "amazon_fee_account_id": expense.id,
                "amazon_advertising_account_id": expense.id,
                "amazon_tax_account_id": revenue.id,
                "amazon_shipping_account_id": revenue.id,
                "amazon_promotion_account_id": expense.id,
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

    def _run(self, groups=None, events=None):
        api = MagicMock()
        api.list_financial_event_groups.return_value.payload = groups or _groups()
        api.list_financial_events_by_group_id.return_value.payload = events or _events()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            return self.channel._amazon_pull_settlements()

    def _group(self):
        return self.env["sale.channel.settlement.group"].search(
            [("sale_channel_id", "=", self.channel.id), ("amazon_group_id", "=", "G1")]
        )

    def _make_invoiced_order(self, price=100.0):
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

    # ---- pull + parse ----
    def test_pull_skips_open_groups(self):
        self._run(groups=_groups(extra_open=True))
        groups = self.env["sale.channel.settlement.group"].search(
            [("sale_channel_id", "=", self.channel.id)]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups.amazon_group_id, "G1")

    def test_event_parsing(self):
        self._run()
        events = self._group().financial_event_ids
        by_type = {e.event_type: e.amount for e in events}
        self.assertEqual(by_type.get("shipment"), 100.0)
        self.assertEqual(by_type.get("tax"), 8.0)
        self.assertEqual(by_type.get("referral_fee"), -15.0)

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

    def test_negative_refund_still_balances(self):
        self._run(events=_events(refund=-20.0))
        move = self._group().account_move_id
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")), sum(move.line_ids.mapped("credit"))
        )

    def test_idempotent_reprocess(self):
        self._run()
        self._run()  # second pull: group exists + already booked
        self.assertEqual(len(self._group()), 1)
        # already-booked group re-reconciles, does not duplicate events
        self.assertEqual(len(self._group().account_move_id), 1)

    # ---- reconciliation ----
    def test_reconciliation_matched(self):
        _order, invoice = self._make_invoiced_order(price=100.0)
        self._run(events=_events(principal=invoice.amount_untaxed))
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "matched")
        self.assertEqual(recon.invoice_id, invoice)

    def test_reconciliation_variance(self):
        _order, invoice = self._make_invoiced_order(price=100.0)
        self._run(events=_events(principal=invoice.amount_untaxed + 5.0))
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "variance")
        self.assertAlmostEqual(recon.variance, 5.0)

    def test_reconciliation_no_invoice(self):
        self._run()  # ORDER-1 has no matching SO/invoice
        recon = self._group().reconciliation_ids
        self.assertEqual(recon.state, "no_invoice")

    # ---- cron + error path ----
    def test_cron_syncs(self):
        api = MagicMock()
        api.list_financial_event_groups.return_value.payload = _groups()
        api.list_financial_events_by_group_id.return_value.payload = _events()
        with (
            trap_jobs() as trap,
            patch(f"{_API_PATH}._amazon_get_api", return_value=api),
        ):
            self.env["sale.channel"]._cron_amazon_sync_settlements()
            trap.perform_enqueued_jobs()
        self.assertTrue(self._group())

    @mute_logger(_MODEL_PATH)
    def test_pull_error_reraises(self):
        api = MagicMock()
        api.list_financial_event_groups.side_effect = ValueError("boom")
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            with self.assertRaises(ValueError):
                self.channel._amazon_pull_settlements()

    def test_fee_posts_to_fee_account_not_income(self):
        # referral fee (-15) must land on the expense account, never on income
        self._run()
        move = self._group().account_move_id
        fee_acct = self.company_data["default_account_expense"]
        income_acct = self.company_data["default_account_revenue"]
        fee_lines = move.line_ids.filtered(lambda line: line.account_id == fee_acct)
        income_lines = move.line_ids.filtered(
            lambda line: line.account_id == income_acct
        )
        self.assertAlmostEqual(sum(fee_lines.mapped("debit")), 15.0)
        self.assertAlmostEqual(sum(income_lines.mapped("credit")), 108.0)
