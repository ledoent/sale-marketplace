# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from collections import defaultdict
from datetime import datetime

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    walmart_income_account_id = fields.Many2one(
        "account.account",
        string="Walmart Income Account",
        help="Revenue account for settled sales, refunds, tax and shipping.",
    )
    walmart_fee_account_id = fields.Many2one(
        "account.account",
        string="Walmart Fee Account",
        help="Expense account for Walmart commission and other fees. Fees are "
        "never routed to the income account; if this is unset the fee line is "
        "absorbed into the bank/clearing offset instead.",
    )
    walmart_tax_account_id = fields.Many2one(
        "account.account",
        string="Walmart Tax Account",
        help="Account for collected sales tax (falls back to income if unset).",
    )
    walmart_shipping_account_id = fields.Many2one(
        "account.account",
        string="Walmart Shipping Account",
        help="Account for settled shipping (falls back to income if unset).",
    )
    walmart_settlement_journal_id = fields.Many2one(
        "account.journal",
        string="Walmart Settlement Journal",
        help="Journal for the settlement entry; its default account is the "
        "bank/clearing line that balances each settlement.",
    )
    walmart_last_settlement_sync_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _walmart_money(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _walmart_settlement_dt(self, value):
        """Parse a Walmart timestamp (epoch millis or ISO 8601) to naive UTC."""
        if not value:
            return False
        if isinstance(value, int | float):
            return datetime.utcfromtimestamp(value / 1000.0).replace(microsecond=0)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        if parsed.tzinfo:
            parsed = parsed.astimezone(pytz.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)

    @staticmethod
    def _walmart_event_type(transaction_type, description):
        """Classify a settlement transaction into a financial-event type."""
        ttype = (transaction_type or "").lower()
        desc = (description or "").lower()
        if "commission" in desc or "referral" in desc or "fee" in desc:
            return "commission"
        if "ship" in desc:
            return "shipping"
        if "tax" in desc:
            return "tax"
        if ttype == "refund" or "refund" in desc:
            return "refund"
        if ttype == "sale":
            return "sale"
        return "other"

    # ------------------------------------------------------------------
    # GL accounts
    # ------------------------------------------------------------------
    def _walmart_settlement_account(self, event_type):
        # Revenue-side types fall back to income; expense-side types resolve to
        # the fee account ONLY -- never fall back to income (that would book a fee
        # as revenue and corrupt the P&L). If no fee account is configured, the
        # expense line is dropped by the caller's `if not account: continue` and
        # absorbed into the bank/clearing offset rather than mis-posted.
        income = self.walmart_income_account_id
        revenue = {
            "sale": income,
            "refund": income,
            "tax": self.walmart_tax_account_id or income,
            "shipping": self.walmart_shipping_account_id or income,
        }
        if event_type in revenue:
            return revenue[event_type]
        # expense-side (commission / other / unknown)
        return self.walmart_fee_account_id

    # ------------------------------------------------------------------
    # Financial events
    # ------------------------------------------------------------------
    def _walmart_create_financial_events(self, group, lines):
        self.ensure_one()
        group.financial_event_ids.unlink()
        vals = []
        for line in lines:
            event_type = self._walmart_event_type(
                line.get("transactionType"), line.get("transactionDescription")
            )
            vals.append(
                {
                    "settlement_group_id": group.id,
                    "event_type": event_type,
                    "purchase_order_id": line.get("purchaseOrderId"),
                    "posted_date": self._walmart_settlement_dt(
                        line.get("postedTimestamp")
                    ),
                    "amount": self._walmart_money(line.get("amount")),
                    "description": line.get("transactionDescription"),
                    "currency_id": group.currency_id.id or False,
                }
            )
        if vals:
            self.env["sale.channel.walmart.financial.event"].create(vals)

    # ------------------------------------------------------------------
    # GL entry
    # ------------------------------------------------------------------
    def _walmart_create_settlement_entry(self, group):
        """Create a balanced journal entry from the group's financial events."""
        self.ensure_one()
        journal = self.walmart_settlement_journal_id
        if not journal or not journal.default_account_id:
            _logger.info(
                "No settlement journal/bank account on %s; skipping entry.",
                self.display_name,
            )
            return self.env["account.move"]
        currency = (
            group.currency_id
            or self.company_id.currency_id
            or self.env.company.currency_id
        )
        totals = {}
        for event in group.financial_event_ids:
            account = self._walmart_settlement_account(event.event_type)
            if not account:
                continue
            totals[account] = totals.get(account, 0.0) + event.amount
        lines = []
        for account, total in totals.items():
            total = currency.round(total)
            if currency.is_zero(total):
                continue
            if total > 0:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "account_id": account.id,
                            "credit": total,
                            "debit": 0.0,
                            "name": group.walmart_settlement_id,
                        },
                    )
                )
            else:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "account_id": account.id,
                            "debit": -total,
                            "credit": 0.0,
                            "name": group.walmart_settlement_id,
                        },
                    )
                )
        if not lines:
            return self.env["account.move"]
        # offset with the bank/clearing line so the entry balances exactly
        balance = currency.round(
            sum(line[2]["credit"] - line[2]["debit"] for line in lines)
        )
        bank = journal.default_account_id
        if not currency.is_zero(balance):
            if balance > 0:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "account_id": bank.id,
                            "debit": balance,
                            "credit": 0.0,
                            "name": "Walmart disbursement",
                        },
                    )
                )
            else:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "account_id": bank.id,
                            "credit": -balance,
                            "debit": 0.0,
                            "name": "Walmart disbursement",
                        },
                    )
                )
        move = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "move_type": "entry",
                "ref": group.walmart_settlement_id,
                "date": fields.Date.context_today(self),
                "line_ids": lines,
            }
        )
        move.action_post()
        group.account_move_id = move.id
        return move

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    def _walmart_reconcile_settlement(self, group):
        """Match settled principal per order to its posted customer invoice."""
        self.ensure_one()
        currency = (
            group.currency_id
            or self.company_id.currency_id
            or self.env.company.currency_id
        )
        group.reconciliation_ids.unlink()
        order_ids = {
            event.purchase_order_id
            for event in group.financial_event_ids
            if event.event_type == "sale" and event.purchase_order_id
        }
        recon_vals = []
        for purchase_order_id in order_ids:
            principal = sum(
                event.amount
                for event in group.financial_event_ids
                if event.purchase_order_id == purchase_order_id
                and event.event_type == "sale"
            )
            order = self.env["sale.order"].search(
                [
                    ("client_order_ref", "=", purchase_order_id),
                    ("sale_channel_id", "=", self.id),
                ],
                limit=1,
            )
            invoice = order.invoice_ids.filtered(
                lambda m: m.move_type == "out_invoice" and m.state == "posted"
            )[:1]
            invoiced = invoice.amount_untaxed if invoice else 0.0
            variance = currency.round(principal - invoiced)
            if not invoice:
                state = "no_invoice"
            elif currency.is_zero(variance):
                state = "matched"
            else:
                state = "variance"
            recon_vals.append(
                {
                    "settlement_group_id": group.id,
                    "purchase_order_id": purchase_order_id,
                    "order_id": order.id or False,
                    "invoice_id": invoice.id or False,
                    "settled_principal": principal,
                    "invoiced_total": invoiced,
                    "variance": variance,
                    "state": state,
                }
            )
        if recon_vals:
            self.env["sale.channel.walmart.settlement.reconciliation"].create(
                recon_vals
            )

    # ------------------------------------------------------------------
    # Pull + orchestration
    # ------------------------------------------------------------------
    def _walmart_fetch_settlement_transactions(self, token=None):
        """Return normalized settlement transaction rows from Walmart.

        Integration seam: each row is a dict with ``settlementId``,
        ``purchaseOrderId``, ``transactionType``, ``transactionDescription``,
        ``amount``, ``currency`` and ``postedTimestamp``. The Walmart settlement
        report is a downloadable recon file; this method normalizes it into rows
        the parser consumes.
        """
        self.ensure_one()
        token = token or self._walmart_get_token()
        response = (
            self._walmart_request(
                "GET",
                "/v3/report/settlementreport/v1",
                params={"version": "v1"},
                token=token,
            )
            or {}
        )
        return response.get("transactions", []) or []

    def _walmart_process_settlement_group(self, settlement_id, lines):
        self.ensure_one()
        currency = self.env["res.currency"].search(
            [("name", "=", (lines[0].get("currency") if lines else None) or "USD")],
            limit=1,
        )
        group = self.env["sale.channel.walmart.settlement.group"].search(
            [
                ("sale_channel_id", "=", self.id),
                ("walmart_settlement_id", "=", settlement_id),
            ],
            limit=1,
        )
        settlement_date = self._walmart_settlement_dt(
            lines[0].get("postedTimestamp") if lines else None
        )
        vals = {
            "settlement_date": settlement_date,
            "original_total": sum(self._walmart_money(t.get("amount")) for t in lines),
            "currency_id": currency.id or False,
        }
        if group:
            group.write(vals)
        else:
            group = self.env["sale.channel.walmart.settlement.group"].create(
                dict(vals, sale_channel_id=self.id, walmart_settlement_id=settlement_id)
            )
        if group.account_move_id:
            # already booked: just re-run reconciliation (idempotent self-heal)
            self._walmart_reconcile_settlement(group)
            return group
        self._walmart_create_financial_events(group, lines)
        self._walmart_create_settlement_entry(group)
        self._walmart_reconcile_settlement(group)
        return group

    def _walmart_pull_settlements(self):
        self.ensure_one()
        token = self._walmart_get_token()
        transactions = self._walmart_fetch_settlement_transactions(token=token)
        by_settlement = defaultdict(list)
        for transaction in transactions:
            by_settlement[transaction.get("settlementId")].append(transaction)
        processed = 0
        for settlement_id, lines in by_settlement.items():
            if not settlement_id:
                continue
            try:
                self._walmart_process_settlement_group(settlement_id, lines)
                processed += 1
            except Exception as exc:  # isolate one bad settlement from the batch
                _logger.warning("Walmart settlement %s failed: %s", settlement_id, exc)
        self.walmart_last_settlement_sync_date = fields.Datetime.now()
        self._walmart_log("settlement_sync", f"Processed {processed} settlement(s).")
        return processed

    def action_walmart_sync_settlements(self):
        self.ensure_one()
        self.with_delay(
            description=f"Sync Walmart settlements for {self.display_name}"
        )._walmart_pull_settlements()
        return True

    @api.model
    def _cron_walmart_sync_settlements(self):
        channels = self.search(
            [("channel_type", "=", "walmart"), ("active", "=", True)]
        )
        for channel in channels:
            channel.with_delay(
                description=f"Sync Walmart settlements for {channel.display_name}"
            )._walmart_pull_settlements()
