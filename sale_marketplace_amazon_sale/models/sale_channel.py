# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import datetime
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Orders not (yet) importable: cancelled/unfulfillable, or still pending
# (pending orders have no pricing or shipping address yet — they import on a
# later poll once Amazon moves them to Unshipped).
_SKIP_STATUSES = {"Canceled", "Unfulfillable", "Pending", "PendingAvailability"}


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    @api.model
    def _cron_amazon_import_orders(self):
        """Cron entry point: enqueue an import job per active Amazon channel."""
        channels = self.search([("channel_type", "=", "amazon"), ("active", "=", True)])
        for channel in channels:
            channel.with_delay(
                description=f"Import Amazon orders for {channel.display_name}"
            )._amazon_import_orders()

    def _amazon_import_orders(self):
        """Poll GetOrders and enqueue one import job per order.

        Updates ``amazon_last_import_date`` on success.
        """
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        if self.amazon_last_import_date:
            since = self.amazon_last_import_date
        else:
            since = fields.Datetime.now() - datetime.timedelta(
                days=self.amazon_import_days_back or 7
            )

        api = self._amazon_get_api(Orders)
        # Capture the cursor BEFORE polling so orders updated during the (possibly
        # paginated) poll are not skipped on the next run.
        poll_start = fields.Datetime.now()
        next_token = None
        imported = 0
        try:
            while True:
                if self.amazon_sandbox:
                    kwargs = {
                        "MarketplaceIds": [self.amazon_marketplace_id],
                        "CreatedAfter": "TEST_CASE_200",
                    }
                else:
                    kwargs = {
                        "MarketplaceIds": [self.amazon_marketplace_id],
                        "LastUpdatedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                if next_token:
                    kwargs["NextToken"] = next_token

                res = api.get_orders(**kwargs)
                payload = res.payload
                for order_data in payload.get("Orders", []):
                    if order_data.get("OrderStatus", "") in _SKIP_STATUSES:
                        continue
                    order_id = order_data["AmazonOrderId"]
                    self.with_delay(
                        description=f"Import Amazon order {order_id}"
                    )._amazon_import_order(order_id)
                    imported += 1

                next_token = payload.get("NextToken")
                if not next_token:
                    break
        except SellingApiException as exc:
            _logger.error(
                "Amazon GetOrders failed for channel %s: %s", self.display_name, exc
            )
            raise

        self.amazon_last_import_date = poll_start
        _logger.info(
            "Channel %s: enqueued %d order import jobs.", self.display_name, imported
        )

    def _amazon_import_order(self, amazon_order_id):
        """Fetch an Amazon order and import it as a native sale.order.

        Builds a ``sale.import.payload`` matching the ``sale_import_base`` schema
        and runs it through the standard importer, which creates the sale order,
        the ``sale.channel.partner`` binding and (optionally) confirms/invoices.
        """
        self.ensure_one()
        from sp_api.api import Orders

        existing = self.env["sale.order"].search(
            [
                ("client_order_ref", "=", amazon_order_id),
                ("sale_channel_id", "=", self.id),
            ],
            limit=1,
        )
        if existing:
            _logger.info(
                "Amazon order %s already imported (SO %s); skipping.",
                amazon_order_id,
                existing.name,
            )
            return existing

        api = self._amazon_get_api(Orders)
        # Let SP-API errors propagate so the queue job retries instead of
        # silently dropping the order (the poll cursor has already advanced).
        order_items = self._amazon_get_all_order_items(api, amazon_order_id)
        address_res = api.get_order_address(amazon_order_id)

        data = self._amazon_order_to_payload(
            amazon_order_id, order_items, address_res.payload
        )
        # Creating the payload enqueues its own processing job
        # (sale.import.payload.create -> enqueue_job), so we do not call
        # process() here to avoid importing the order twice.
        return self.env["sale.import.payload"].create(
            {
                "data_str": json.dumps(data),
                "sale_channel_id": self.id,
                "company_id": self.company_id.id,
            }
        )

    def _amazon_order_to_payload(self, amazon_order_id, order_items, address_payload):
        """Map Amazon order data to the sale_import_base SaleOrder schema dict."""
        self.ensure_one()
        shipping = address_payload.get("ShippingAddress", {})
        state_code = shipping.get("StateOrRegion") or None
        # Amazon sends a state code for some marketplaces and a full region name
        # for others; only forward short codes to avoid a failed state lookup.
        if state_code and len(state_code) > 3:
            state_code = None
        address = {
            "name": shipping.get("Name") or f"Amazon {amazon_order_id}",
            "street": shipping.get("AddressLine1") or "",
            "street2": shipping.get("AddressLine2") or None,
            "zip": shipping.get("PostalCode") or "",
            "city": shipping.get("City") or "",
            "country_code": shipping.get("CountryCode") or "US",
            "state_code": state_code,
            "phone": shipping.get("Phone") or None,
        }
        customer = dict(address, external_id=amazon_order_id)

        lines = []
        for item in order_items:
            sku = item.get("SellerSKU", "")
            qty = item.get("QuantityOrdered", 1) or 1
            amount = float(item.get("ItemPrice", {}).get("Amount", 0) or 0)
            lines.append(
                {
                    "product_code": sku,
                    "qty": qty,
                    "price_unit": amount / qty if qty else amount,
                    "description": (item.get("Title") or sku or "Amazon Product")[:255],
                }
            )

        return {
            "name": amazon_order_id,
            "address_customer": customer,
            "address_shipping": address,
            "address_invoicing": address,
            "lines": lines,
        }
