# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    @staticmethod
    def _amazon_address(partner):
        """Format a partner as an SP-API MerchantFulfillment address dict."""
        return {
            "Name": (partner.name or "")[:50],
            "AddressLine1": partner.street or "",
            "AddressLine2": partner.street2 or "",
            "City": partner.city or "",
            "StateOrProvinceCode": partner.state_id.code or "",
            "PostalCode": partner.zip or "",
            "CountryCode": partner.country_id.code or "US",
            "Phone": partner.phone or "",
        }

    def _amazon_shipment_request(self, picking, weight):
        self.ensure_one()
        ship_from = (
            picking.picking_type_id.warehouse_id.partner_id
            or self.env.company.partner_id
        )
        return {
            "ShipFromAddress": self._amazon_address(ship_from),
            "ShipToAddress": self._amazon_address(picking.partner_id),
            "PackageDimensions": {"PredefinedPackageDimensions": "FedEx_Box_10kg"},
            "Weight": {"Value": weight or 1.0, "Unit": "oz"},
            "ShippingServiceOptions": {
                "DeliveryExperience": "DeliveryConfirmationWithoutSignature",
                "CarrierWillPickUp": False,
            },
        }

    @staticmethod
    def _amazon_parse_rate(service):
        rate = service.get("Rate", {}) or {}
        return {
            "service_id": service.get("ShippingServiceId"),
            "service_offer_id": service.get("ShippingServiceOfferId"),
            "carrier_name": service.get("CarrierName"),
            "service_name": service.get("ShippingServiceName"),
            "amount": rate.get("Amount", 0.0),
            "currency": rate.get("CurrencyCode") or "USD",
        }

    def _amazon_get_shipping_rates(self, picking, weight):
        """Return a list of eligible shipping service rate dicts."""
        self.ensure_one()
        from sp_api.api import MerchantFulfillment

        api = self._amazon_get_api(MerchantFulfillment)
        details = self._amazon_shipment_request(picking, weight)
        try:
            result = api.get_eligible_shipment_services(details)
        except Exception as exc:
            raise UserError(
                _("Could not fetch Amazon shipping rates: %s") % exc
            ) from exc
        services = (result.payload or {}).get("ShippingServiceList", [])
        return [self._amazon_parse_rate(s) for s in services]

    def _amazon_purchase_label(self, picking, service_id, offer_id, weight):
        """Buy a label for the picking; return tracking + label contents."""
        self.ensure_one()
        from sp_api.api import MerchantFulfillment

        api = self._amazon_get_api(MerchantFulfillment)
        details = self._amazon_shipment_request(picking, weight)
        try:
            result = api.create_shipment(
                details,
                shipping_service_id=service_id,
                shipping_service_offer_id=offer_id,
            )
        except Exception as exc:
            raise UserError(_("Could not buy the Amazon label: %s") % exc) from exc
        payload = result.payload or {}
        label = payload.get("Label", {}).get("FileContents", {})
        return {
            "amazon_shipment_id": payload.get("AmazonShipmentId"),
            "tracking_number": payload.get("TrackingId"),
            "carrier_name": payload.get("ShippingService", {}).get("CarrierName"),
            "service_name": payload.get("ShippingService", {}).get(
                "ShippingServiceName"
            ),
            "cost": payload.get("ShippingService", {})
            .get("Rate", {})
            .get("Amount", 0.0),
            "currency": payload.get("ShippingService", {})
            .get("Rate", {})
            .get("CurrencyCode")
            or "USD",
            "label_contents": label.get("Contents"),
        }
