# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase

from odoo.addons.sale_marketplace_amazon_stock.models.sale_channel import (
    _map_carrier_code,
)


class TestCarrierCode(TransactionCase):
    def test_known_carriers(self):
        self.assertEqual(_map_carrier_code("UPS Ground"), "UPS")
        self.assertEqual(_map_carrier_code("usps priority"), "USPS")
        self.assertEqual(_map_carrier_code("FedEx Home"), "FedEx")

    def test_unknown_carrier(self):
        self.assertEqual(_map_carrier_code("Royal Mail"), "Other")
        self.assertEqual(_map_carrier_code(""), "Other")
