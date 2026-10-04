# Copyright 2026 Ledo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Record documented sandbox cases through the installed SP-API SDK.

Credentials arrive on stdin as dotenv text; never written to the evidence directory.
Only the SDK's SP-API transport is recorded, never the authentication transport.
"""

import argparse
import copy
import hashlib
import json
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from sp_api import api

OPERATIONS = {
    "getOrders": ("Orders", "get_orders"),
    "getOrder": ("Orders", "get_order"),
    "getOrderItems": ("Orders", "get_order_items"),
    "getOrderAddress": ("Orders", "get_order_address"),
    "confirmShipment": ("Orders", "confirm_shipment"),
    "searchListingsItems": ("ListingsItems", "search_listings_items"),
    "patchListingsItem": ("ListingsItems", "patch_listings_item"),
    "getInventorySummaries": ("Inventories", "get_inventory_summary_marketplace"),
    "listFinancialEventGroups": ("Finances", "list_financial_event_groups"),
    "listFinancialEventsByGroupId": ("Finances", "list_financial_events_by_group_id"),
    "getCompetitivePricing": ("Products", "get_competitive_pricing_for_asins"),
    "getMyFeesEstimateForSKU": ("ProductFees", "get_product_fees_estimate_for_sku"),
    "getEligibleShipmentServices": (
        "MerchantFulfillment",
        "get_eligible_shipment_services",
    ),
    "createShipment": ("MerchantFulfillment", "create_shipment"),
    "createFulfillmentOrder": ("FulfillmentOutbound", "create_fulfillment_order"),
    "getFulfillmentOrder": ("FulfillmentOutbound", "get_fulfillment_order"),
    "cancelFulfillmentOrder": ("FulfillmentOutbound", "cancel_fulfillment_order"),
    "createDestination": ("Notifications", "create_destination"),
    "createSubscription": ("Notifications", "create_subscription"),
    "createReport": ("Reports", "create_report"),
    "getReport": ("Reports", "get_report"),
    "getReportDocument": ("Reports", "get_report_document"),
}


def invoke(client, operation, parameters):
    """Adapt documented parameter names to SDK convenience-method signatures."""
    p = copy.deepcopy(parameters)
    body = p.pop("body", {})
    call = getattr(client, OPERATIONS[operation][1])
    if operation in {"getOrder", "getOrderItems", "getOrderAddress", "confirmShipment"}:
        return call(p.pop("orderId", "TEST_CASE_200"), **p, **body)
    if operation == "searchListingsItems":
        return call(p.pop("sellerId", "TEST_CASE_200"), **p)
    if operation == "patchListingsItem":
        body = body or {
            "productType": "PRODUCT",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [{"fulfillment_channel_code": "DEFAULT", "quantity": 5}],
                }
            ],
        }
        return call(
            p.pop("sellerId", "TEST_CASE_200"),
            p.pop("sku", "TEST_CASE_200"),
            body=body,
            **p,
        )
    if operation == "listFinancialEventsByGroupId":
        return call(p.pop("eventGroupId"), **p)
    if operation == "getCompetitivePricing":
        p.pop("ItemType", None)
        return call(p.pop("Asins", ["B000P6Q7MY"]), **p)
    if operation == "getMyFeesEstimateForSKU":
        req = body["FeesEstimateRequest"]
        prices = req["PriceToEstimateFees"]
        return call(
            p.pop("SellerSKU", req["Identifier"]),
            prices["ListingPrice"]["Amount"],
            shipping_price=prices.get("Shipping", {}).get("Amount"),
            currency=prices["ListingPrice"]["CurrencyCode"],
            is_fba=req["IsAmazonFulfilled"],
            points=prices.get("Points"),
            marketplace_id=req["MarketplaceId"],
        )
    if operation in {"getEligibleShipmentServices", "createShipment"}:
        details = body.pop("ShipmentRequestDetails")
        if operation == "createShipment":
            return call(details, body.pop("ShippingServiceId"), **body)
        return call(details, **body)
    if operation in {"createFulfillmentOrder", "createReport"}:
        return call(**body)
    if operation in {"getFulfillmentOrder", "cancelFulfillmentOrder"}:
        return call(p.pop("sellerFulfillmentOrderId"), **p)
    if operation == "createDestination":
        return call(
            name="sandbox-verification",
            arn="arn:aws:sqs:us-east-1:123456789012:sandbox",
        )
    if operation == "createSubscription":
        return call("ANY_OFFER_CHANGED", destination_id="TEST_CASE_200")
    if operation == "getReport":
        return call(p.pop("reportId"), **p)
    if operation == "getReportDocument":
        return call(p.pop("reportDocumentId"), decrypt=False, **p)
    return call(**p)


class Recorder:
    def __init__(self, transport):
        self.transport = transport
        self.exchanges = []

    def request(self, method, url, **kwargs):
        if urlsplit(url).hostname != "sandbox.sellingpartnerapi-na.amazon.com":
            raise RuntimeError("Non-sandbox SP-API endpoint refused")
        content = kwargs.get("content") or kwargs.get("data")
        if isinstance(content, bytes):
            content = content.decode()
        if isinstance(content, str):
            content = json.loads(content)
        exchange = {
            "method": method,
            "path": urlsplit(url).path,
            "params": kwargs.get("params"),
            "body": content,
        }
        response = self.transport.request(method, url, **kwargs)
        exchange["status"] = response.status_code
        try:
            exchange["response"] = response.json()
        except ValueError:
            exchange["response"] = None
        self.exchanges.append(exchange)
        return response


def dynamic_parameters(operation):
    order_id = "sandbox-fulfillment-test"
    if operation == "getInventorySummaries":
        return {
            "granularityType": "Marketplace",
            "granularityId": "ATVPDKIKX0DER",
            "marketplaceIds": ["ATVPDKIKX0DER"],
            "details": True,
        }
    if operation in {"getFulfillmentOrder", "cancelFulfillmentOrder"}:
        return {"sellerFulfillmentOrderId": order_id}
    if operation == "createFulfillmentOrder":
        return {
            "body": {
                "marketplaceId": "ATVPDKIKX0DER",
                "sellerFulfillmentOrderId": order_id,
                "displayableOrderId": order_id,
                "displayableOrderDate": "2026-10-04T00:00:00Z",
                "displayableOrderComment": "Sandbox verification",
                "shippingSpeedCategory": "Standard",
                "destinationAddress": {
                    "name": "Sandbox Buyer",
                    "addressLine1": "123 Main St",
                    "city": "Seattle",
                    "stateOrRegion": "WA",
                    "postalCode": "98101",
                    "countryCode": "US",
                },
                "items": [
                    {
                        "sellerSku": "TEST_CASE_200",
                        "sellerFulfillmentOrderItemId": "item-1",
                        "quantity": 1,
                    }
                ],
            }
        }
    return None


def cases(models):
    for filename in sorted(models.glob("*.json")):
        model = json.loads(filename.read_text())
        for path, item in model["paths"].items():
            for method, operation in item.items():
                if (
                    not isinstance(operation, dict)
                    or operation.get("operationId") not in OPERATIONS
                ):
                    continue
                op = operation["operationId"]
                found = False
                for status, response in operation["responses"].items():
                    for i, case in enumerate(
                        response.get("x-amzn-api-sandbox", {}).get("static", [])
                    ):
                        found = True
                        parameters = {
                            k: v["value"]
                            for k, v in case.get("request", {})
                            .get("parameters", {})
                            .items()
                            if "value" in v
                        }
                        yield {
                            "id": f"{op}-{status}-{i}",
                            "operation": op,
                            "schema": filename.name,
                            "path": path,
                            "method": method,
                            "expected_status": int(status),
                            "parameters": parameters,
                            "expected_response": case.get("response"),
                            "kind": "static",
                        }
                if not found:
                    yield {
                        "id": op,
                        "operation": op,
                        "schema": filename.name,
                        "path": path,
                        "method": method,
                        "expected_status": int(
                            next(c for c in operation["responses"] if c.startswith("2"))
                        ),
                        "kind": "dynamic_probe",
                        "parameters": dynamic_parameters(op),
                    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operation", action="append")
    parser.add_argument(
        "--probe", action="store_true", help="One success case per operation"
    )
    args = parser.parse_args()
    env = {}
    for line in sys.stdin:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.strip().removeprefix("export ").split("=", 1)
            tokens = shlex.split(value, comments=True)
            env[key.strip()] = tokens[0] if tokens else ""
    credentials = {
        "lwa_app_id": env.get("AMZ_CLIENT_ID") or env.get("AMAZON_SP_API_CLIENT_ID"),
        "lwa_client_secret": env.get("AMZ_CLIENT_SECRET")
        or env.get("AMAZON_SP_API_CLIENT_SECRET"),
        "refresh_token": env.get("AMZ_REFRESH_TOKEN")
        or env.get("AMAZON_SP_API_REFRESH_TOKEN"),
    }
    if not all(credentials.values()):
        raise SystemExit("Required credentials missing")
    marketplace = SimpleNamespace(
        endpoint="https://sandbox.sellingpartnerapi-na.amazon.com",
        marketplace_id="ATVPDKIKX0DER",
        region="us-east-1",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    seen = set()
    for case in cases(args.models):
        if args.operation and case["operation"] not in args.operation:
            continue
        if args.probe and (
            case["operation"] in seen or case.get("expected_status", 200) >= 400
        ):
            continue
        seen.add(case["operation"])
        record = {
            **case,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "schema_sha256": hashlib.sha256(
                (args.models / case["schema"]).read_bytes()
            ).hexdigest(),
        }
        if case["parameters"] is None:
            record["result"] = "needs_dynamic_scenario"
        else:
            client = getattr(api, OPERATIONS[case["operation"]][0])(
                marketplace=marketplace, credentials=credentials, timeout=25
            )
            recorder = Recorder(client._transport)
            client._transport = recorder
            try:
                invoke(client, case["operation"], case["parameters"])
            except Exception as exc:
                # SDK exceptions can contain tokens or HTTP bodies: record type only.
                record["exception_type"] = type(exc).__name__
            record["exchanges"] = recorder.exchanges
            status = recorder.exchanges[-1]["status"] if recorder.exchanges else None
            record["result"] = (
                "status_matched" if status == case["expected_status"] else "failed"
            )
            recorder.transport.close()
            time.sleep(0.4)
        serialized = json.dumps(record, indent=2, default=str)
        for secret in credentials.values():
            serialized = serialized.replace(secret, "[REDACTED]")
        (args.output / (case["id"] + ".json")).write_text(serialized + "\n")
        results.append({"id": case["id"], "result": record["result"]})
        sys.stdout.write(f"{case['id']} {record['result']}\n")
        sys.stdout.flush()
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    if any(result["result"] != "status_matched" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
