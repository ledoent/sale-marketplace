# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    def action_amazon_import_listings(self):
        """Pull active Amazon listings and upsert channel product bindings."""
        self.ensure_one()
        if not self.amazon_seller_id:
            raise UserError(_("Amazon Seller ID is required to import listings."))
        from sp_api.api import ListingsItems
        from sp_api.base import SellingApiException

        api = self._amazon_get_api(ListingsItems)
        binding_model = self.env["sale.channel.product"]
        imported = 0
        next_token = None
        try:
            while True:
                kwargs = {
                    "sellerId": self.amazon_seller_id,
                    "marketplaceIds": [self.amazon_marketplace_id],
                }
                if next_token:
                    kwargs["pageToken"] = next_token

                result = api.search_listings_items(**kwargs)
                payload = result.payload
                for item in payload.get("items", []):
                    sku = item.get("sku")
                    if not sku:
                        continue
                    summaries = item.get("summaries", [])
                    asin = summaries[0].get("asin") if summaries else None
                    product = self.env["product.product"].search(
                        [("default_code", "=", sku)], limit=1
                    )
                    if not product:
                        _logger.warning("no product found for SKU %s; skipping", sku)
                        continue
                    binding_model._amazon_upsert(self, product, sku, asin)
                    imported += 1

                next_token = payload.get("pagination", {}).get("nextToken")
                if not next_token:
                    break
        except SellingApiException as exc:
            _logger.error(
                "Amazon SearchListingsItems failed for channel %s: %s",
                self.display_name,
                exc,
            )
            raise

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Listings imported"),
                "message": _("Imported %(count)d listing(s).", count=imported),
                "type": "success",
            },
        }
