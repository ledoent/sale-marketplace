# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    mcf_default_speed = fields.Selection(
        [
            ("Standard", "Standard"),
            ("Expedited", "Expedited"),
            ("Priority", "Priority"),
        ],
        default="Standard",
        string="MCF Default Speed",
    )

    def _amz_mcf_body(self, order):
        """Build the createFulfillmentOrder request body."""
        self.ensure_one()
        partner = order.partner_id
        return {
            "marketplaceId": self.amazon_marketplace_id,
            "sellerFulfillmentOrderId": order.name,
            "displayableOrderId": order.displayable_order_id or order.name,
            "displayableOrderDate": fields.Datetime.now().isoformat(),
            "displayableOrderComment": "Fulfilled via Amazon MCF",
            "shippingSpeedCategory": order.shipping_speed or "Standard",
            "destinationAddress": {
                "name": (partner.name or "")[:50],
                "addressLine1": partner.street or "",
                "addressLine2": partner.street2 or "",
                "city": partner.city or "",
                "stateOrRegion": partner.state_id.code or "",
                "postalCode": partner.zip or "",
                "countryCode": partner.country_id.code or "US",
                "phone": partner.phone or "",
            },
            "items": [
                {
                    "sellerSku": line.seller_sku,
                    "sellerFulfillmentOrderItemId": line.item_id or line.seller_sku,
                    "quantity": int(line.quantity),
                }
                for line in order.line_ids
            ],
        }

    def _amz_create_fulfillment_order(self, order):
        self.ensure_one()
        from sp_api.api import FulfillmentOutbound

        api = self._amazon_get_api(FulfillmentOutbound)
        return api.create_fulfillment_order(**self._amz_mcf_body(order))

    def _amz_get_fulfillment_order(self, order):
        self.ensure_one()
        from sp_api.api import FulfillmentOutbound

        api = self._amazon_get_api(FulfillmentOutbound)
        return (api.get_fulfillment_order(order.name).payload) or {}

    def _amz_cancel_fulfillment_order(self, order):
        self.ensure_one()
        from sp_api.api import FulfillmentOutbound

        api = self._amazon_get_api(FulfillmentOutbound)
        return api.cancel_fulfillment_order(order.name)
