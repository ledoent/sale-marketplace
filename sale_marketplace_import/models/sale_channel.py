# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo import models


class SaleChannel(models.Model):
    _inherit = "sale.channel"

    def _create_import_payload(self, data, **vals):
        """Enqueue a marketplace order import through ``sale_import_base``.

        This is the single seam between marketplace connectors and
        sale-channel's ``sale.import.payload`` ingest pipeline. A connector
        builds the ``sale_import_base`` schema dict and calls this method
        instead of touching ``sale.import.payload`` directly, so the dependency
        on sale-channel's import framework lives only in
        ``sale_marketplace_import`` -- connectors depend on the marketplace
        boundary, never on ``sale_import_base``.

        Creating the payload enqueues its own processing job
        (``sale.import.payload.create`` -> ``enqueue_job``), so callers must not
        also call ``process()`` -- doing so would import the order twice.

        :param data: the ``sale_import_base`` SaleOrder schema dict.
        :param vals: extra values to set on the created payload.
        :return: the created ``sale.import.payload`` record.
        """
        self.ensure_one()
        return self.env["sale.import.payload"].create(
            {
                "data_str": json.dumps(data),
                "sale_channel_id": self.id,
                "company_id": self.company_id.id,
                **vals,
            }
        )
