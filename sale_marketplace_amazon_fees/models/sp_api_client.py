# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from sp_api.api import ProductFees


def _without_none(value):
    if isinstance(value, dict):
        return {
            key: _without_none(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


class ProductFeesClient(ProductFees):
    """Omit optional nulls emitted by the SDK's fee-request convenience method.

    Amazon's published request schema makes these properties optional, but
    does not permit null values. Keep numeric zero and false unchanged.
    """

    def _request(self, path, **kwargs):
        if "data" in kwargs:
            kwargs["data"] = _without_none(kwargs["data"])
        return super()._request(path, **kwargs)
