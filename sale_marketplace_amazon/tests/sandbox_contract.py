# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Strict HTTP-boundary replay of published Amazon sandbox examples.

These fixtures come from Amazon's API models, not from successful live captures.
Authentication is replaced; the real SDK still serializes and decodes every call.
"""

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft4Validator
from sp_api.api import Orders
from sp_api.base import Client

CONTRACTS = json.loads(
    (Path(__file__).parent / "samples" / "amazon_contracts.json").read_text()
)["operations"]


class ContractReplay:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request(self, method, url, **kwargs):
        path = urlsplit(url).path
        matches = [
            (name, contract)
            for name, contract in CONTRACTS.items()
            if method.upper() == contract["method"]
            and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", contract["path"]), path)
        ]
        if len(matches) != 1:
            raise AssertionError(f"Unexpected SP-API request: {method} {path}")
        name, contract = matches[0]
        body = kwargs.get("content") or kwargs.get("data")
        if isinstance(body, str | bytes):
            body = json.loads(body)
        params = dict(kwargs.get("params") or {})
        for parameter in contract["parameters"]:
            location = parameter["in"]
            if location == "body":
                schema = dict(parameter["schema"], definitions=contract["definitions"])
                Draft4Validator(schema).validate(body)
            elif location == "query":
                key = parameter["name"]
                if parameter.get("required") and key not in params:
                    raise AssertionError(f"Missing {name} query parameter: {key}")
        if coverage := os.environ.get("AMAZON_CONTRACT_COVERAGE"):
            with Path(coverage).open("a") as output:
                output.write(name + "\n")
        self.calls.append(
            {"operation": name, "body": body, "params": params, "path": path}
        )
        if name in self.responses:
            response = self.responses[name]
            if isinstance(response, list):
                response = response.pop(0)
            if isinstance(response, Exception):
                raise response
            status, payload = response
        else:
            case = next(c for c in contract["cases"] if c["status"] < 300)
            status, payload = case["status"], case["response"]
        request = httpx.Request(method, url)
        if status == 204:
            return httpx.Response(status, request=request)
        return httpx.Response(status, json=payload, request=request)


@contextmanager
def replay(responses=None, documents=None):
    controller = ContractReplay(responses)

    def document_response(request, **kwargs):
        if documents and str(request.url) in documents:
            return httpx.Response(
                200,
                content=documents[str(request.url)],
                headers={"Content-Type": "text/xml; charset=utf-8"},
                request=request,
            )
        raise AssertionError("Offline test attempted network access")

    client = Orders(
        credentials={
            "lwa_app_id": "test",
            "lwa_client_secret": "test",
            "refresh_token": "test",
        }
    )
    transport = type(client._transport)
    client._transport.close()
    with (
        patch(
            "socket.socket.connect",
            side_effect=AssertionError("Offline test attempted network access"),
        ),
        patch(
            "odoo.addons.sale_marketplace_amazon.models.sale_channel.SaleChannel._amazon_get_credentials",
            return_value={
                "lwa_app_id": "test",
                "lwa_client_secret": "test",
                "refresh_token": "test",
            },
        ),
        patch.object(Client, "headers", new_callable=PropertyMock, return_value={}),
        patch.object(
            Client,
            "grantless_auth",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(access_token="offline"),
        ),
        patch.object(transport, "request", side_effect=controller.request),
        patch.object(httpx.Client, "send", side_effect=document_response),
    ):
        yield controller
