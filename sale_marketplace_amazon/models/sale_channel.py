# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import types

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MARKETPLACES = [
    ("ATVPDKIKX0DER", "US — amazon.com"),
    ("A2EUQ1WTGCTBG2", "Canada — amazon.ca"),
    ("A1AM78C64UM0Y8", "Mexico — amazon.com.mx"),
    ("A2Q3Y263D00KWC", "Brazil — amazon.com.br"),
    ("A1RKKUPIHCS9HS", "Spain — amazon.es"),
    ("A1F83G8C2ARO7P", "UK — amazon.co.uk"),
    ("A13V1IB3VIYZZH", "France — amazon.fr"),
    ("A1PA6795UKMFR9", "Germany — amazon.de"),
    ("APJ6JRA9NG5V4", "Italy — amazon.it"),
    ("A2NODRKZP88ZB9", "Netherlands — amazon.nl"),
    ("A1805IZSGTT6HS", "Poland — amazon.pl"),
    ("A2VIGQ35RCS4UG", "UAE — amazon.ae"),
    ("A21TJRUUN4KGV", "India — amazon.in"),
    ("A39IBJ37TRP1C6", "Australia — amazon.com.au"),
    ("A1VC38T7YXB528", "Japan — amazon.co.jp"),
    ("A19VAU5U5O7RUS", "Singapore — amazon.sg"),
]

# NA marketplaces use sellingpartnerapi-na, EU use -eu, FE use -fe
_MARKETPLACE_REGION_SUFFIX = {
    "ATVPDKIKX0DER": "na",
    "A2EUQ1WTGCTBG2": "na",
    "A1AM78C64UM0Y8": "na",
    "A2Q3Y263D00KWC": "na",
    "A1RKKUPIHCS9HS": "eu",
    "A1F83G8C2ARO7P": "eu",
    "A13V1IB3VIYZZH": "eu",
    "A1PA6795UKMFR9": "eu",
    "APJ6JRA9NG5V4": "eu",
    "A2NODRKZP88ZB9": "eu",
    "A1805IZSGTT6HS": "eu",
    "A2VIGQ35RCS4UG": "eu",
    "A21TJRUUN4KGV": "eu",
    "A39IBJ37TRP1C6": "fe",
    "A1VC38T7YXB528": "fe",
    "A19VAU5U5O7RUS": "fe",
}


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    channel_type = fields.Selection(
        selection_add=[("amazon", "Amazon")],
        ondelete={"amazon": "set null"},
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        help="Warehouse fulfilling and stocking this Amazon channel.",
    )

    # SP-API credentials
    amazon_client_id = fields.Char("LWA Client ID")
    amazon_client_secret = fields.Char("LWA Client Secret", groups="base.group_system")
    amazon_refresh_token = fields.Char("LWA Refresh Token", groups="base.group_system")
    amazon_seller_id = fields.Char("Seller ID", help="Seller Central merchant token.")
    amazon_marketplace_id = fields.Selection(
        MARKETPLACES,
        string="Marketplace",
        default="ATVPDKIKX0DER",
    )
    amazon_sandbox = fields.Boolean(
        "Sandbox Mode",
        help="Use Amazon SP-API sandbox endpoints. "
        "Requires credentials created in the developer sandbox.",
    )
    amazon_import_days_back = fields.Integer(
        "Initial Import Days Back",
        default=7,
        help="On first import, fetch orders updated this many days ago.",
    )
    amazon_last_import_date = fields.Datetime(
        "Last Order Import",
        readonly=True,
        copy=False,
        help="Cursor for incremental order polling.",
    )

    @api.model
    def _marketplace_channel_types(self):
        return super()._marketplace_channel_types() + ["amazon"]

    def _amazon_get_credentials(self):
        self.ensure_one()
        return {
            "lwa_app_id": self.amazon_client_id,
            "lwa_client_secret": self.amazon_client_secret,
            "refresh_token": self.amazon_refresh_token,
        }

    def _amazon_get_api(self, api_class):
        """Return an SP-API client instance for this channel.

        Builds a synthetic marketplace namespace to avoid mutating the
        module-level AWS_ENV global, which is not thread-safe.
        """
        self.ensure_one()
        from sp_api.base import Marketplaces

        suffix = _MARKETPLACE_REGION_SUFFIX.get(self.amazon_marketplace_id, "na")
        base = (
            "sandbox.sellingpartnerapi" if self.amazon_sandbox else "sellingpartnerapi"
        )
        endpoint = f"https://{base}-{suffix}.amazon.com"

        # Find the matching Marketplace enum member for region metadata
        sp_marketplace = next(
            (m for m in Marketplaces if m.marketplace_id == self.amazon_marketplace_id),
            Marketplaces.US,
        )

        fake_marketplace = types.SimpleNamespace(
            endpoint=endpoint,
            marketplace_id=self.amazon_marketplace_id,
            region=sp_marketplace.region,
        )

        return api_class(
            marketplace=fake_marketplace,
            credentials=self._amazon_get_credentials(),
        )

    def action_amazon_test_connection(self):
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        try:
            api = self._amazon_get_api(Orders)
            if self.amazon_sandbox:
                res = api.get_orders(
                    CreatedAfter="TEST_CASE_200",
                    MarketplaceIds=[self.amazon_marketplace_id],
                )
            else:
                import datetime

                since = fields.Datetime.now() - datetime.timedelta(days=1)
                res = api.get_orders(
                    CreatedAfter=since.isoformat() + "Z",
                    MarketplaceIds=[self.amazon_marketplace_id],
                )
            order_count = len(res.payload.get("Orders", []))
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection successful"),
                    "message": _(
                        "Retrieved %(count)d order(s) from Amazon.",
                        count=order_count,
                    ),
                    "type": "success",
                },
            }
        except SellingApiException as exc:
            raise UserError(_("Amazon SP-API error: %s", exc)) from exc
        except Exception as exc:
            raise UserError(_("Connection failed: %s", exc)) from exc

    def _amazon_get_all_order_items(self, api, amazon_order_id):
        """Return every order item, following GetOrderItems NextToken pagination.

        GetOrderItems is paginated; fetching only the first page silently drops
        lines for orders with many items.
        """
        items = []
        next_token = None
        while True:
            kwargs = {"NextToken": next_token} if next_token else {}
            res = api.get_order_items(amazon_order_id, **kwargs)
            items.extend(res.payload.get("OrderItems", []))
            next_token = res.payload.get("NextToken")
            if not next_token:
                break
        return items
