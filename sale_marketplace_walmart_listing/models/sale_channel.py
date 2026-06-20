# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Walmart maps an internal feed status to one of our four states.
_FEED_STATE_MAP = {
    "RECEIVED": "processing",
    "INPROGRESS": "processing",
    "INPROGRESS_FINISHED": "processing",
    "PROCESSED": "done",
    "ERROR": "error",
}


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    def action_walmart_import_listings(self):
        """Pull Walmart items and upsert channel product (SKU) bindings."""
        self.ensure_one()
        token = self._walmart_get_token()
        binding_model = self.env["sale.channel.product"]
        imported = 0
        next_cursor = None
        while True:
            params = {"limit": 50}
            if next_cursor:
                params["nextCursor"] = next_cursor
            response = self._walmart_request(
                "GET", "/v3/items", params=params, token=token
            )
            response = response or {}
            for item in response.get("ItemResponse", []) or []:
                sku = item.get("sku")
                if not sku:
                    continue
                wpid = item.get("wpid")
                product = self.env["product.product"].search(
                    [("default_code", "=", sku)], limit=1
                )
                if not product:
                    _logger.warning("no product found for SKU %s; skipping", sku)
                    self._walmart_log(
                        "listing_import",
                        f"No Odoo product for SKU {sku}; skipped.",
                        level="warning",
                        reference=sku,
                    )
                    continue
                binding_model._walmart_upsert(self, product, sku, wpid)
                imported += 1

            next_cursor = response.get("nextCursor")
            if not next_cursor:
                break

        self._walmart_log("listing_import", f"Imported {imported} listing(s).")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Listings imported"),
                "message": _("Imported %(count)d listing(s).", count=imported),
                "type": "success",
            },
        }

    # ------------------------------------------------------------------
    # Listing export (item feed)
    #
    # Publishes/maintains Walmart listings from Odoo via the Feeds API. Each
    # binding flagged ``walmart_publish`` becomes one MP_ITEM entry; the feed is
    # submitted and tracked as a sale.channel.walmart.feed record.
    # ------------------------------------------------------------------
    def _walmart_item_feed_entry(self, binding):
        """Build a single MP_ITEM feed entry from a channel-product binding."""
        product = binding.product_id
        item = {
            "sku": binding.external_id,
            "productName": product.display_name,
            "price": product.list_price,
        }
        if product.barcode:
            item["productIdentifiers"] = [
                {"productIdType": "GTIN", "productId": product.barcode}
            ]
        return {"Item": item}

    def _walmart_build_item_feed(self, bindings):
        """Build the MP_ITEM feed document for the given bindings."""
        self.ensure_one()
        return {
            "MPItemFeedHeader": {
                "sellingChannel": "marketplace",
                "version": "4.2",
                "locale": "en",
            },
            "MPItem": [self._walmart_item_feed_entry(b) for b in bindings],
        }

    def _walmart_submit_item_feed(self, bindings=None):
        """Submit an item feed for the channel's publishable bindings."""
        self.ensure_one()
        if bindings is None:
            bindings = self.env["sale.channel.product"].search(
                [
                    ("sale_channel_id", "=", self.id),
                    ("active", "=", True),
                    ("walmart_publish", "=", True),
                ]
            )
        if not bindings:
            _logger.info(
                "No publishable bindings on %s; skipping item feed.",
                self.display_name,
            )
            return self.env["sale.channel.walmart.feed"]
        token = self._walmart_get_token()
        feed = self._walmart_build_item_feed(bindings)
        response = (
            self._walmart_request(
                "POST",
                "/v3/feeds",
                params={"feedType": "item"},
                payload=feed,
                token=token,
            )
            or {}
        )
        feed_id = response.get("feedId")
        if not feed_id:
            _logger.warning(
                "Walmart item feed for %s returned no feedId.", self.display_name
            )
            return self.env["sale.channel.walmart.feed"]
        return self.env["sale.channel.walmart.feed"].create(
            {
                "sale_channel_id": self.id,
                "feed_id": feed_id,
                "feed_type": "item",
                "state": "submitted",
            }
        )

    def _walmart_refresh_feed(self, feed):
        """Poll a submitted feed's status and update its counters."""
        self.ensure_one()
        response = self._walmart_request("GET", f"/v3/feeds/{feed.feed_id}") or {}
        status = response.get("feedStatus")
        feed.write(
            {
                "state": _FEED_STATE_MAP.get(status, feed.state),
                "items_received": response.get("itemsReceived", feed.items_received),
                "items_succeeded": response.get("itemsSucceeded", feed.items_succeeded),
                "items_failed": response.get("itemsFailed", feed.items_failed),
                "error_message": response.get("ingestionErrors")
                and str(response.get("ingestionErrors")),
            }
        )
        return feed

    def action_walmart_export_listings(self):
        self.ensure_one()
        self.with_delay(
            description=f"Export Walmart listings for {self.display_name}"
        )._walmart_submit_item_feed()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Listing Export Queued"),
                "message": _("An item feed submission has been queued."),
                "type": "info",
            },
        }

    @api.model
    def _cron_walmart_refresh_feeds(self):
        feeds = self.env["sale.channel.walmart.feed"].search(
            [("state", "in", ("submitted", "processing"))]
        )
        for feed in feeds:
            feed.sale_channel_id.with_delay(
                description=f"Refresh Walmart feed {feed.feed_id}"
            )._walmart_refresh_feed(feed)
