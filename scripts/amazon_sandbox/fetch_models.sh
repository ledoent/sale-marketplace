#!/bin/bash
# Fetch the exact public schemas used by the offline contract fixtures.
set -euo pipefail
revision=3677bb9d96f4450e6843f1f8207005e925d5c867
output="${1:?Usage: fetch_models.sh OUTPUT_DIRECTORY}"
mkdir -p "$output"
for model in fba-inventory-api-model/fbaInventory finances-api-model/financesV0 fulfillment-outbound-api-model/fulfillmentOutbound_2020-07-01 listings-items-api-model/listingsItems_2021-08-01 merchant-fulfillment-api-model/merchantFulfillmentV0 notifications-api-model/notifications orders-api-model/ordersV0 product-fees-api-model/productFeesV0 product-pricing-api-model/productPricingV0 reports-api-model/reports_2021-06-30; do
    curl --fail --silent --show-error --location \
        "https://raw.githubusercontent.com/amzn/selling-partner-api-models/$revision/models/$model.json" \
        --output "$output/${model##*/}.json"
done
printf '%s\n' "$revision" > "$output/revision.txt"
