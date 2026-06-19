# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_API_PATH = "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel"
_MODEL_PATH = "odoo.addons.sale_marketplace_amazon_fees.models.sale_channel"


def _fee_payload(basis=25.0, status="Success", extra_type=None):
    details = [
        {"FeeType": "ReferralFee", "FeeAmount": {"Amount": 3.75}},
        {"FeeType": "FBAFees", "FeeAmount": {"Amount": 2.0}},
        {"FeeType": "VariableClosingFee", "FeeAmount": {"Amount": 0.5}},
    ]
    if extra_type:
        details.append({"FeeType": extra_type, "FeeAmount": {"Amount": 1.0}})
    return {
        "FeesEstimateResult": {
            "Status": status,
            "FeesEstimate": {
                "FeesEstimateIdentifier": {
                    "PriceToEstimateFees": {"ListingPrice": {"Amount": basis}}
                },
                "FeeDetailList": details,
            },
        }
    }


class TestFees(TransactionCase):
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
                "competitive_floor_margin_pct": 10.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Widget", "default_code": "SKU-1", "standard_price": 10.0}
        )
        cls.binding = cls.env["sale.channel.product"].create(
            {
                "sale_channel_id": cls.channel.id,
                "product_id": cls.product.id,
                "external_id": "SKU-1",
                "current_list_price": 25.0,
            }
        )

    def _sync(self, payload):
        api = MagicMock()
        api.get_product_fees_estimate_for_sku.return_value.payload = payload
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            return self.channel._amazon_sync_fees(), api

    # ---- parse + sync ----
    def test_sync_stores_breakdown(self):
        synced, _api = self._sync(_fee_payload())
        self.assertEqual(synced, 1)
        self.assertAlmostEqual(self.binding.referral_fee, 3.75)
        self.assertAlmostEqual(self.binding.fulfillment_fee, 2.0)
        self.assertAlmostEqual(self.binding.variable_closing_fee, 0.5)
        self.assertAlmostEqual(self.binding.total_fees, 6.25)
        self.assertAlmostEqual(self.binding.fee_basis_price, 25.0)
        self.assertTrue(self.channel.last_fee_sync_date)

    def test_margin_math(self):
        self._sync(_fee_payload())
        # 25 - 6.25 fees = 18.75 proceeds; - 10 cost = 8.75 margin; 35% of 25
        self.assertAlmostEqual(self.binding.est_net_proceeds, 18.75)
        self.assertAlmostEqual(self.binding.est_net_margin, 8.75)
        self.assertAlmostEqual(self.binding.est_margin_pct, 35.0)

    def test_below_target_flag(self):
        self._sync(_fee_payload())
        self.assertFalse(self.binding.below_target_margin)  # 35% > 10% target
        self.channel.competitive_floor_margin_pct = 50.0
        self.assertTrue(self.binding.below_target_margin)  # 35% < 50% target

    def test_unrecognized_fee_counted_as_other(self):
        self._sync(_fee_payload(extra_type="WeirdSurcharge"))
        self.assertAlmostEqual(self.binding.other_fees, 1.0)
        self.assertAlmostEqual(self.binding.total_fees, 7.25)

    def test_unsuccessful_status_writes_nothing(self):
        synced, _api = self._sync(_fee_payload(status="ClientError"))
        self.assertEqual(synced, 0)
        self.assertEqual(self.binding.referral_fee, 0.0)

    def test_listing_without_price_skipped(self):
        self.binding.current_list_price = 0.0
        synced, api = self._sync(_fee_payload())
        self.assertEqual(synced, 0)
        api.get_product_fees_estimate_for_sku.assert_not_called()

    # ---- fee-aware floor ----
    def test_fee_aware_floor_raises_above_cost_floor(self):
        # referral 15% (3.75/25), fixed fees 2.5, cost 10, margin 10%
        # denom = 1 - 0.15 - 0.10 = 0.75 ; floor = (10 + 2.5) / 0.75 = 16.667
        self.binding.write(
            {
                "fee_basis_price": 25.0,
                "referral_fee": 3.75,
                "fulfillment_fee": 2.0,
                "variable_closing_fee": 0.5,
            }
        )
        self.assertAlmostEqual(
            self.channel._amazon_price_floor(self.binding), 16.6667, places=3
        )

    def test_fee_aware_floor_denom_guard_falls_back(self):
        # referral 96% of price -> denom <= 0 -> fall back to base floor 10/(1-0.10)
        self.binding.write({"fee_basis_price": 25.0, "referral_fee": 24.0})
        self.assertAlmostEqual(
            self.channel._amazon_price_floor(self.binding), 10.0 / 0.9, places=4
        )

    # ---- cron + error isolation ----
    def test_cron_syncs_fees(self):
        api = MagicMock()
        api.get_product_fees_estimate_for_sku.return_value.payload = _fee_payload()
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            self.env["sale.channel"]._cron_amazon_sync_fees()
        self.assertAlmostEqual(self.binding.referral_fee, 3.75)

    @mute_logger(_MODEL_PATH)
    def test_sync_error_isolation(self):
        api = MagicMock()
        api.get_product_fees_estimate_for_sku.side_effect = Exception("boom")
        with patch(f"{_API_PATH}._amazon_get_api", return_value=api):
            synced = self.channel._amazon_sync_fees()
        self.assertEqual(synced, 0)
        self.assertEqual(self.binding.referral_fee, 0.0)
