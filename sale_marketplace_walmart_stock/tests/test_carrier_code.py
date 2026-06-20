# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase

from odoo.addons.sale_marketplace_walmart_stock.models.sale_channel import (
    _walmart_carrier_name,
)


class TestCarrierCode(TransactionCase):
    def test_known_carrier_prefix(self):
        self.assertEqual(_walmart_carrier_name("UPS Ground"), {"carrier": "UPS"})
        self.assertEqual(_walmart_carrier_name("FedEx Home"), {"carrier": "FedEx"})
        self.assertEqual(_walmart_carrier_name("usps first"), {"carrier": "USPS"})

    def test_unknown_carrier_uses_other(self):
        self.assertEqual(
            _walmart_carrier_name("Acme Freight"), {"otherCarrier": "Acme Freight"}
        )

    def test_empty_carrier_defaults_to_other(self):
        self.assertEqual(_walmart_carrier_name(""), {"otherCarrier": "Other"})
        self.assertEqual(_walmart_carrier_name(None), {"otherCarrier": "Other"})
