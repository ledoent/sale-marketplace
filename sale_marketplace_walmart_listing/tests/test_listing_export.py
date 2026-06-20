# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.queue_job.tests.common import trap_jobs

_MODEL = "odoo.addons.sale_marketplace_walmart.models.sale_channel.SaleChannel"


class TestListingExport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["sale.channel"].create(
            {
                "name": "Walmart",
                "channel_type": "walmart",
                "walmart_client_id": "client",
                "walmart_client_secret": "secret",
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "default_code": "SKU-1",
                "list_price": 25.0,
                "barcode": "0001112223334",
            }
        )
        cls.product2 = cls.env["product.product"].create(
            {"name": "Gadget", "default_code": "SKU-2", "list_price": 10.0}
        )
        Binding = cls.env["sale.channel.product"]
        cls.binding = Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
            }
        )
        cls.binding_off = Binding.create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product2.id,
                "external_id": "SKU-2",
                "walmart_publish": False,
            }
        )

    def test_build_item_feed_only_includes_published(self):
        feed = self.channel._walmart_build_item_feed(self.binding)
        self.assertEqual(feed["MPItemFeedHeader"]["sellingChannel"], "marketplace")
        items = feed["MPItem"]
        self.assertEqual(len(items), 1)
        item = items[0]["Item"]
        self.assertEqual(item["sku"], "SKU-1")
        self.assertEqual(item["price"], 25.0)
        self.assertEqual(item["productIdentifiers"][0]["productId"], "0001112223334")

    def test_submit_item_feed_creates_feed_record(self):
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(
                f"{_MODEL}._walmart_request", return_value={"feedId": "FEED-1"}
            ) as req,
        ):
            feed = self.channel._walmart_submit_item_feed()
        self.assertEqual(feed.feed_id, "FEED-1")
        self.assertEqual(feed.state, "submitted")
        post = [c for c in req.call_args_list if c.args[0] == "POST"]
        self.assertEqual(len(post), 1)
        self.assertEqual(post[0].args[1], "/v3/feeds")
        self.assertEqual(post[0].kwargs["params"]["feedType"], "item")
        # only the publishable binding is in the feed
        items = post[0].kwargs["payload"]["MPItem"]
        self.assertEqual([i["Item"]["sku"] for i in items], ["SKU-1"])

    def test_submit_without_bindings_is_noop(self):
        self.binding.walmart_publish = False
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request") as req,
        ):
            feed = self.channel._walmart_submit_item_feed()
        self.assertFalse(feed)
        req.assert_not_called()

    def test_refresh_feed_maps_status_and_counts(self):
        feed = self.env["sale.channel.walmart.feed"].create(
            {
                "sale_channel_id": self.channel.id,
                "feed_id": "FEED-1",
                "state": "submitted",
            }
        )
        status = {
            "feedStatus": "PROCESSED",
            "itemsReceived": 5,
            "itemsSucceeded": 4,
            "itemsFailed": 1,
        }
        with (
            patch(f"{_MODEL}._walmart_get_token", return_value="TOK"),
            patch(f"{_MODEL}._walmart_request", return_value=status),
        ):
            self.channel._walmart_refresh_feed(feed)
        self.assertEqual(feed.state, "done")
        self.assertEqual(feed.items_received, 5)
        self.assertEqual(feed.items_succeeded, 4)
        self.assertEqual(feed.items_failed, 1)

    def test_cron_refreshes_open_feeds(self):
        self.env["sale.channel.walmart.feed"].create(
            {
                "sale_channel_id": self.channel.id,
                "feed_id": "FEED-OPEN",
                "state": "submitted",
            }
        )
        self.env["sale.channel.walmart.feed"].create(
            {
                "sale_channel_id": self.channel.id,
                "feed_id": "FEED-DONE",
                "state": "done",
            }
        )
        with trap_jobs() as trap:
            self.env["sale.channel"]._cron_walmart_refresh_feeds()
            trap.assert_jobs_count(1)
