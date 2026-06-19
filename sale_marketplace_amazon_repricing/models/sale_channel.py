# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# Safety cap on receive_message iterations per drain (each returns up to 10).
_MAX_DRAIN_LOOPS = 100


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    aws_access_key_id = fields.Char("AWS Access Key ID", groups="base.group_system")
    aws_secret_access_key = fields.Char(
        "AWS Secret Access Key", groups="base.group_system"
    )
    aws_region = fields.Char("AWS Region", default="us-east-1")
    sqs_queue_url = fields.Char("SQS Queue URL")
    notifications_enabled = fields.Boolean()

    # ------------------------------------------------------------------
    # AWS SQS client
    # ------------------------------------------------------------------
    def _amazon_get_sqs_client(self):
        self.ensure_one()
        try:
            import boto3
        except ImportError as exc:
            raise UserError(_("The boto3 Python package is required for SQS.")) from exc
        return boto3.client(
            "sqs",
            region_name=self.aws_region or "us-east-1",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )

    def action_amazon_setup_notifications(self):
        """Register the SQS destination + ANY_OFFER_CHANGED subscription."""
        self.ensure_one()
        if not self.sqs_queue_url:
            raise UserError(_("An SQS Queue URL is required."))
        from sp_api.api import Notifications

        sqs = self._amazon_get_sqs_client()
        attrs = sqs.get_queue_attributes(
            QueueUrl=self.sqs_queue_url, AttributeNames=["QueueArn"]
        )
        arn = attrs["Attributes"]["QueueArn"]
        api = self._amazon_get_api(Notifications)
        destination = api.create_destination(
            name=f"odoo-{self.id}", resource={"sqs": {"arn": arn}}
        )
        destination_id = destination.payload.get("destinationId")
        api.create_subscription("ANY_OFFER_CHANGED", destination_id=destination_id)
        self.notifications_enabled = True
        return True

    # ------------------------------------------------------------------
    # Drain + process
    # ------------------------------------------------------------------
    def _amazon_drain_sqs_queue(self):
        """Receive and process ANY_OFFER_CHANGED messages from the SQS queue.

        Messages are deleted only on successful processing (failed ones are left
        for redelivery). Duplicate redeliveries within a drain are de-duplicated
        by message id so a listing is not snapshotted twice for one change.
        """
        self.ensure_one()
        sqs = self._amazon_get_sqs_client()
        seen = set()
        for _loop in range(_MAX_DRAIN_LOOPS):
            resp = sqs.receive_message(
                QueueUrl=self.sqs_queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=0,
            )
            messages = resp.get("Messages", [])
            if not messages:
                break
            for msg in messages:
                msg_id = msg.get("MessageId")
                if msg_id and msg_id in seen:
                    # duplicate redelivery this drain: ack and skip reprocessing
                    sqs.delete_message(
                        QueueUrl=self.sqs_queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                    continue
                try:
                    self._amazon_process_offer_notification(json.loads(msg["Body"]))
                except Exception as exc:  # pragma: no cover - logged, left to retry
                    _logger.warning("Amazon offer notification failed: %s", exc)
                    continue  # do not delete -> SQS will redeliver
                if msg_id:
                    seen.add(msg_id)
                sqs.delete_message(
                    QueueUrl=self.sqs_queue_url, ReceiptHandle=msg["ReceiptHandle"]
                )

    def _amazon_process_offer_notification(self, payload):
        """Apply one ANY_OFFER_CHANGED notification to this channel's listing."""
        self.ensure_one()
        payload = payload or {}
        notif = payload.get("Payload", {}).get("AnyOfferChangedNotification", {})
        asin = notif.get("OfferChangeTrigger", {}).get("ASIN")
        if not asin:
            return
        offers = notif.get("Offers", [])
        # Scope strictly to THIS channel so a shared ASIN never cross-updates.
        binding = self.env["sale.channel.product"].search(
            [("sale_channel_id", "=", self.id), ("asin", "=", asin)], limit=1
        )
        if not binding:
            return
        buy_box = next((o for o in offers if o.get("IsBuyBoxWinner")), None)
        if buy_box:
            binding.buy_box_price = buy_box.get("ListingPrice", {}).get("Amount", 0.0)
            binding.buy_box_winner = buy_box.get("SellerId") == self.amazon_seller_id
        self._amazon_snapshot_offers(binding, offers)
        if self.price_push_enabled:
            self._amazon_reprice_listing(binding)

    def _amazon_snapshot_offers(self, binding, offers):
        snapshot = self.env["sale.channel.product.offer.snapshot"].sudo()
        for offer in offers:
            snapshot.create(
                {
                    "sale_channel_product_id": binding.id,
                    "seller_id": offer.get("SellerId"),
                    "is_own_offer": offer.get("SellerId") == self.amazon_seller_id,
                    "is_buy_box_winner": bool(offer.get("IsBuyBoxWinner")),
                    "price": offer.get("ListingPrice", {}).get("Amount", 0.0),
                }
            )

    def _amazon_reprice_listing(self, binding):
        self.ensure_one()
        target = self._amazon_compute_listing_price(binding)
        if not target:
            return
        if float_compare(target, binding.current_list_price, precision_digits=2) == 0:
            return
        from sp_api.api import ListingsItems

        api = self._amazon_get_api(ListingsItems)
        try:
            self._amazon_patch_listing_price(api, binding, target)
        except Exception as exc:  # pragma: no cover - logged and skipped
            _logger.warning(
                "Amazon reprice failed for SKU %s: %s", binding.external_id, exc
            )
            return
        old_price = binding.current_list_price
        binding.current_list_price = target
        rule = self.competitive_rule if self.pricing_mode == "competitive" else False
        binding._log_price_change(old_price, target, "notification", rule)

    @api.model
    def _cron_amazon_poll_offer_notifications(self):
        channels = self.search(
            [
                ("channel_type", "=", "amazon"),
                ("notifications_enabled", "=", True),
                ("sqs_queue_url", "!=", False),
            ]
        )
        for channel in channels:
            channel._amazon_drain_sqs_queue()
