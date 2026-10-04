# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestMarketplaceSecurity(TransactionCase):
    def test_company_rules_apply_to_sales_managers(self):
        other_company = self.env["res.company"].create({"name": "Other seller"})
        operator = new_test_user(
            self.env,
            login="marketplace_operator",
            groups="sales_team.group_sale_manager",
            company_id=self.env.company.id,
            company_ids=[(6, 0, self.env.company.ids)],
        )
        channels = self.env["sale.channel"].create(
            [
                {"name": "Own seller", "company_id": self.env.company.id},
                {"name": "Other seller", "company_id": other_company.id},
            ]
        )
        product = self.env["product.product"].create({"name": "Shared widget"})
        bindings = self.env["sale.channel.product"].create(
            [
                {
                    "sale_channel_id": c.id,
                    "product_id": product.id,
                    "external_id": "SKU",
                }
                for c in channels
            ]
        )
        self.assertEqual(
            channels.with_user(operator).search([("id", "in", channels.ids)]),
            channels[:1],
        )
        self.assertEqual(
            bindings.with_user(operator).search([("id", "in", bindings.ids)]),
            bindings[:1],
        )
        with self.assertRaises(AccessError):
            bindings[1].with_user(operator).read(["external_id"])
        with self.assertRaises(AccessError):
            channels[1].with_user(operator).write({"name": "Unauthorized"})
