# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_REPRICE_PATH = (
    "odoo.addons.sale_marketplace_amazon_repricing.models.sale_channel.SaleChannel"
)
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_repricing.models.sale_channel"


def _notif(asin="ASIN1", price=18.0, winner="SELLER1", offers=None):
    if offers is None:
        offers = [
            {
                "SellerId": winner,
                "IsBuyBoxWinner": True,
                "ListingPrice": {"Amount": price},
            },
            {
                "SellerId": "COMP1",
                "IsBuyBoxWinner": False,
                "ListingPrice": {"Amount": price + 1},
            },
        ]
    return {
        "Payload": {
            "AnyOfferChangedNotification": {
                "OfferChangeTrigger": {"ASIN": asin},
                "Offers": offers,
            }
        }
    }


class TestRepricing(TransactionCase):
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
                "sqs_queue_url": "https://sqs.test/q",
                "notifications_enabled": True,
                "pricing_mode": "competitive",
                "competitive_rule": "match_buy_box",
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1"}
        )
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
                "asin": "ASIN1",
            }
        )

    # ---- notification processing ----
    def test_process_updates_buy_box_we_win(self):
        self.channel._amazon_process_offer_notification(_notif(price=18.0))
        self.assertEqual(self.binding.buy_box_price, 18.0)
        self.assertTrue(self.binding.buy_box_winner)

    def test_process_competitor_wins(self):
        self.channel._amazon_process_offer_notification(_notif(winner="COMPX"))
        self.assertFalse(self.binding.buy_box_winner)

    def test_process_scoped_to_channel(self):
        other = self.env["sale.channel"].create(
            {
                "name": "Amazon 2",
                "channel_type": "amazon",
                "amazon_seller_id": "SELLER2",
                "warehouse_id": self.warehouse.id,
            }
        )
        other_binding = self.env["sale.channel.product"].create(
            {
                "sale_channel_id": other.id,
                "product_id": self.product.id,
                "external_id": "SKU-1",
                "asin": "ASIN1",
            }
        )
        self.channel._amazon_process_offer_notification(_notif(price=18.0))
        self.assertEqual(self.binding.buy_box_price, 18.0)
        self.assertEqual(other_binding.buy_box_price, 0.0)  # not cross-updated

    def test_process_snapshots_offers(self):
        self.channel._amazon_process_offer_notification(_notif())
        snaps = self.binding.env["sale.channel.product.offer.snapshot"].search(
            [("sale_channel_product_id", "=", self.binding.id)]
        )
        self.assertEqual(len(snaps), 2)
        self.assertTrue(snaps.filtered(lambda s: s.is_own_offer))

    def test_process_unknown_asin_skips(self):
        self.channel._amazon_process_offer_notification(_notif(asin="ZZZ"))
        self.assertEqual(self.binding.buy_box_price, 0.0)

    def test_process_triggers_reprice_when_enabled(self):
        self.channel.price_push_enabled = True
        api = MagicMock()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.channel._amazon_process_offer_notification(_notif(price=18.0))
        self.assertEqual(self.binding.current_list_price, 18.0)
        self.assertTrue(api.patch_listings_item.called)

    # ---- SQS drain ----
    def _msg(self, msg_id="m1", payload=None):
        return {
            "MessageId": msg_id,
            "ReceiptHandle": f"rh-{msg_id}",
            "Body": json.dumps(payload or _notif()),
        }

    def test_drain_processes_and_deletes(self):
        sqs = MagicMock()
        sqs.receive_message.side_effect = [{"Messages": [self._msg()]}, {}]
        with patch(f"{_REPRICE_PATH}._amazon_get_sqs_client", return_value=sqs):
            self.channel._amazon_drain_sqs_queue()
        self.assertEqual(self.binding.buy_box_price, 18.0)
        self.assertEqual(sqs.delete_message.call_count, 1)

    def test_drain_dedup_skips_duplicate(self):
        # same MessageId twice -> processed once, both acked (deleted)
        sqs = MagicMock()
        sqs.receive_message.side_effect = [
            {"Messages": [self._msg("dup"), self._msg("dup")]},
            {},
        ]
        with patch(f"{_REPRICE_PATH}._amazon_get_sqs_client", return_value=sqs):
            self.channel._amazon_drain_sqs_queue()
        snaps = self.binding.env["sale.channel.product.offer.snapshot"].search(
            [("sale_channel_product_id", "=", self.binding.id)]
        )
        self.assertEqual(len(snaps), 2)  # one notification's offers, not doubled
        self.assertEqual(sqs.delete_message.call_count, 2)  # both acked

    @mute_logger(_MODEL_PATH)
    def test_drain_nack_on_error(self):
        sqs = MagicMock()
        bad = {"MessageId": "bad", "ReceiptHandle": "rh", "Body": "not-json"}
        sqs.receive_message.side_effect = [{"Messages": [bad]}, {}]
        with patch(f"{_REPRICE_PATH}._amazon_get_sqs_client", return_value=sqs):
            self.channel._amazon_drain_sqs_queue()
        sqs.delete_message.assert_not_called()  # left for redelivery

    def test_cron_skips_channel_without_queue(self):
        self.channel.sqs_queue_url = False
        with patch(f"{_REPRICE_PATH}._amazon_get_sqs_client") as get_client:
            self.env["sale.channel"]._cron_amazon_poll_offer_notifications()
        get_client.assert_not_called()

    # ---- setup ----
    def test_setup_notifications(self):
        sqs = MagicMock()
        sqs.get_queue_attributes.return_value = {"Attributes": {"QueueArn": "arn:x"}}
        api = MagicMock()
        api.create_destination.return_value.payload = {"destinationId": "d1"}
        with (
            patch(f"{_REPRICE_PATH}._amazon_get_sqs_client", return_value=sqs),
            patch(f"{_API_PATH}._amazon_get_api", return_value=api),
        ):
            self.channel.action_amazon_setup_notifications()
        self.assertTrue(self.channel.notifications_enabled)
        self.assertTrue(api.create_subscription.called)

    def test_process_no_winner_resets_buy_box(self):
        # we were winning; a notification with no buy-box winner must clear it
        self.binding.buy_box_winner = True
        notif = _notif(
            offers=[
                {
                    "SellerId": "X",
                    "IsBuyBoxWinner": False,
                    "ListingPrice": {"Amount": 9},
                }
            ]
        )
        self.channel._amazon_process_offer_notification(notif)
        self.assertFalse(self.binding.buy_box_winner)
