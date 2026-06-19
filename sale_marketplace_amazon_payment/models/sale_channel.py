# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    amazon_income_account_id = fields.Many2one(
        "account.account", string="Income Account"
    )
    amazon_fee_account_id = fields.Many2one("account.account", string="Fee Account")
    amazon_advertising_account_id = fields.Many2one(
        "account.account", string="Advertising Account"
    )
    amazon_tax_account_id = fields.Many2one("account.account", string="Tax Account")
    amazon_shipping_account_id = fields.Many2one(
        "account.account", string="Shipping Account"
    )
    amazon_promotion_account_id = fields.Many2one(
        "account.account", string="Promotion Account"
    )
    amazon_settlement_journal_id = fields.Many2one(
        "account.journal", string="Settlement Journal"
    )
    last_settlement_sync_date = fields.Datetime(readonly=True)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _amazon_money(node):
        # SP-API delivers CurrencyAmount as a number or a string; coerce.
        return float((node or {}).get("CurrencyAmount", 0.0) or 0.0)

    @api.model
    def _amazon_settlement_dt(self, value):
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        if parsed.tzinfo:
            parsed = parsed.astimezone(pytz.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)

    def _amazon_shipment_vals(self, event, refund=False):
        """Flatten a shipment/refund event into financial-event value dicts."""
        aoid = event.get("AmazonOrderId")
        posted = self._amazon_settlement_dt(event.get("PostedDate"))
        base = {"amazon_order_id": aoid, "posted_date": posted}
        principal_type = "refund" if refund else "shipment"
        vals = []
        items = event.get("ShipmentItemList") or event.get(
            "ShipmentItemAdjustmentList", []
        )
        for item in items:
            charges = item.get("ItemChargeList") or item.get(
                "ItemChargeAdjustmentList", []
            )
            for charge in charges:
                ctype = charge.get("ChargeType") or ""
                amount = self._amazon_money(charge.get("ChargeAmount"))
                if "Tax" in ctype:
                    etype = "tax"
                elif "Shipping" in ctype:
                    etype = "shipping"
                else:
                    etype = principal_type
                vals.append(
                    dict(base, event_type=etype, amount=amount, description=ctype)
                )
            fees = item.get("ItemFeeList") or item.get("ItemFeeAdjustmentList", [])
            for fee in fees:
                ftype = fee.get("FeeType") or ""
                amount = self._amazon_money(fee.get("FeeAmount"))
                if ftype == "Commission":
                    etype = "referral_fee"
                elif ftype.startswith("FBA"):
                    etype = "fba_fee"
                else:
                    etype = "service_fee"
                vals.append(
                    dict(base, event_type=etype, amount=amount, description=ftype)
                )
            promos = item.get("PromotionList") or item.get(
                "PromotionAdjustmentList", []
            )
            for promo in promos:
                amount = self._amazon_money(promo.get("PromotionAmount"))
                vals.append(
                    dict(
                        base,
                        event_type="promotion",
                        amount=amount,
                        description="Promotion",
                    )
                )
        return vals

    def _amazon_simple_fee_vals(self, event, event_type):
        amount = 0.0
        for fee in event.get("FeeList", []):
            amount += self._amazon_money(fee.get("FeeAmount"))
        if not amount:
            amount = self._amazon_money(event.get("TransactionValue"))
        return {
            "amazon_order_id": event.get("AmazonOrderId"),
            "posted_date": self._amazon_settlement_dt(event.get("PostedDate")),
            "event_type": event_type,
            "amount": amount,
            "description": event_type,
        }

    def _amazon_parse_financial_events(self, group, events):
        vals = []
        for event in events.get("ShipmentEventList", []):
            vals += self._amazon_shipment_vals(event, refund=False)
        for event in events.get("RefundEventList", []):
            vals += self._amazon_shipment_vals(event, refund=True)
        for event in events.get("ServiceFeeEventList", []):
            vals.append(self._amazon_simple_fee_vals(event, "service_fee"))
        for event in events.get("ProductAdsPaymentEventList", []):
            vals.append(self._amazon_simple_fee_vals(event, "advertising"))
        if vals:
            self.env["sale.channel.financial.event"].create(
                [
                    dict(
                        v,
                        settlement_group_id=group.id,
                        currency_id=group.currency_id.id or False,
                    )
                    for v in vals
                ]
            )

    # ------------------------------------------------------------------
    # GL entry
    # ------------------------------------------------------------------
    def _amazon_settlement_account(self, event_type):
        # Revenue-side types fall back to income; expense-side types fall back to
        # the fee account -- never route a fee to income (that would corrupt P&L).
        income = self.amazon_income_account_id
        fee = self.amazon_fee_account_id
        mapping = {
            "shipment": income,
            "refund": income,
            "tax": self.amazon_tax_account_id or income,
            "shipping": self.amazon_shipping_account_id or income,
            "referral_fee": fee,
            "fba_fee": fee,
            "service_fee": fee,
            "advertising": self.amazon_advertising_account_id or fee,
            "promotion": self.amazon_promotion_account_id or fee,
            "other": fee,
        }
        return mapping.get(event_type) or fee or income

    def _amazon_create_settlement_entry(self, group):
        """Create a balanced journal entry from the group's financial events."""
        self.ensure_one()
        journal = self.amazon_settlement_journal_id
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
            account = self._amazon_settlement_account(event.event_type)
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
                            "name": group.amazon_group_id,
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
                            "name": group.amazon_group_id,
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
                            "name": "Amazon disbursement",
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
                            "name": "Amazon disbursement",
                        },
                    )
                )
        move = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "move_type": "entry",
                "ref": group.amazon_group_id,
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
    def _amazon_reconcile_settlement(self, group):
        """Match settled principal per order to its posted customer invoice."""
        self.ensure_one()
        currency = (
            group.currency_id
            or self.company_id.currency_id
            or self.env.company.currency_id
        )
        group.reconciliation_ids.unlink()
        order_ids = {
            event.amazon_order_id
            for event in group.financial_event_ids
            if event.event_type == "shipment" and event.amazon_order_id
        }
        recon_vals = []
        for amazon_order_id in order_ids:
            principal = sum(
                event.amount
                for event in group.financial_event_ids
                if event.amazon_order_id == amazon_order_id
                and event.event_type == "shipment"
            )
            order = self.env["sale.order"].search(
                [
                    ("client_order_ref", "=", amazon_order_id),
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
                    "amazon_order_id": amazon_order_id,
                    "order_id": order.id or False,
                    "invoice_id": invoice.id or False,
                    "settled_principal": principal,
                    "invoiced_total": invoiced,
                    "variance": variance,
                    "state": state,
                }
            )
        if recon_vals:
            self.env["sale.channel.settlement.reconciliation"].create(recon_vals)

    # ------------------------------------------------------------------
    # Pull + orchestration
    # ------------------------------------------------------------------
    def _amazon_pull_group_events(self, group):
        self.ensure_one()
        from sp_api.api import Finances

        api = self._amazon_get_api(Finances)
        group.financial_event_ids.unlink()
        next_token = None
        while True:
            kwargs = {"NextToken": next_token} if next_token else {}
            result = api.list_financial_events_by_group_id(
                group.amazon_group_id, **kwargs
            )
            payload = result.payload or {}
            self._amazon_parse_financial_events(
                group, payload.get("FinancialEvents", {})
            )
            next_token = payload.get("NextToken")
            if not next_token:
                break

    def _amazon_process_settlement_group(self, group_data):
        self.ensure_one()
        gid = group_data.get("FinancialEventGroupId")
        if not gid:
            return self.env["sale.channel.settlement.group"]
        total = group_data.get("OriginalTotal", {})
        currency = self.env["res.currency"].search(
            [("name", "=", total.get("CurrencyCode") or "USD")], limit=1
        )
        group = self.env["sale.channel.settlement.group"].search(
            [("sale_channel_id", "=", self.id), ("amazon_group_id", "=", gid)], limit=1
        )
        vals = {
            "processing_status": group_data.get("ProcessingStatus"),
            "fund_transfer_date": self._amazon_settlement_dt(
                group_data.get("FundTransferDate")
            ),
            "original_total": self._amazon_money(total),
            "currency_id": currency.id or False,
        }
        if group:
            group.write(vals)
        else:
            group = self.env["sale.channel.settlement.group"].create(
                dict(vals, sale_channel_id=self.id, amazon_group_id=gid)
            )
        if group.account_move_id:
            # already booked: just re-run reconciliation (idempotent self-heal)
            self._amazon_reconcile_settlement(group)
            return group
        self._amazon_pull_group_events(group)
        self._amazon_create_settlement_entry(group)
        self._amazon_reconcile_settlement(group)
        return group

    def _amazon_pull_settlements(self):
        self.ensure_one()
        from sp_api.api import Finances

        api = self._amazon_get_api(Finances)
        processed = 0
        next_token = None
        while True:
            if next_token:
                kwargs = {"NextToken": next_token}
            else:
                started_after = self.last_settlement_sync_date or (
                    fields.Datetime.now() - timedelta(days=90)
                )
                kwargs = {"FinancialEventGroupStartedAfter": started_after.isoformat()}
            try:
                result = api.list_financial_event_groups(**kwargs)
            except Exception as exc:
                _logger.error("Amazon list settlements failed: %s", exc)
                raise
            payload = result.payload or {}
            for group_data in payload.get("FinancialEventGroupList", []):
                if group_data.get("ProcessingStatus") != "Closed":
                    continue
                try:
                    self._amazon_process_settlement_group(group_data)
                    processed += 1
                except Exception as exc:  # isolate one bad group from the batch
                    _logger.warning(
                        "Amazon settlement group %s failed: %s",
                        group_data.get("FinancialEventGroupId"),
                        exc,
                    )
            next_token = payload.get("NextToken")
            if not next_token:
                break
        self.last_settlement_sync_date = fields.Datetime.now()
        return processed

    def action_amazon_sync_settlements(self):
        self.ensure_one()
        self.with_delay()._amazon_pull_settlements()
        return True

    @api.model
    def _cron_amazon_sync_settlements(self):
        channels = self.search([("channel_type", "=", "amazon")])
        for channel in channels:
            channel._amazon_pull_settlements()
