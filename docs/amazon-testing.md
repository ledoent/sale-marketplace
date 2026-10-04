# Testing the Amazon addons

## Offline Odoo suite

In an OCA Odoo 18 CI container with this repository as the working directory and
PostgreSQL configured, run:

```sh
oca_install_addons
oca_init_test_database
oca_run_tests
```

Use a fresh `PGDATABASE` for an installation test. Run module-update tests separately.
`test-requirements.txt` supplies test dependencies. Run `pre-commit run --all-files` for
formatting and static checks. `run-tests-local.sh` provides a disposable Docker runner
with a read-only source checkout.

## SDK contract fixtures

Fixtures in `sale_marketplace_amazon/tests/samples/amazon_contracts.json` are from
[Amazon's published models at the pinned revision](https://github.com/amzn/selling-partner-api-models/tree/3677bb9d96f4450e6843f1f8207005e925d5c867).
They are **published examples, not live recordings**. Tests preserve SDK serialization
and response decoding, validate request bodies against the model schemas and check
required query keys. Authentication and HTTP responses are replaced; unexpected network
access fails. This does not validate every query value or prove Amazon will accept a
call.

FBA inventory, MCF lifecycle, pricing, settlement, label and report-document scenarios
also use constructed responses. Offline tests do not establish live seller acceptance,
SQS delivery, remote purchase recovery, or accounting correctness.

## Sandbox capture

Install the SDK version being tested and provide sandbox application credentials with
the required API roles. From the repository root:

```sh
bash scripts/amazon_sandbox/fetch_models.sh /tmp/amazon-models
python scripts/amazon_sandbox/capture.py --models /tmp/amazon-models \
  --output /tmp/amazon-captures --probe < /path/to/external/sandbox.env
```

The dotenv file may use `AMZ_CLIENT_ID`, `AMZ_CLIENT_SECRET`, `AMZ_REFRESH_TOKEN` or
`AMAZON_SP_API_CLIENT_ID`, `AMAZON_SP_API_CLIENT_SECRET`, `AMAZON_SP_API_REFRESH_TOKEN`.
Credentials are read from stdin and must remain outside version control. The harness
restricts SP-API calls to the North America sandbox. It records sanitized exchanges;
review captures before sharing them. `status_matched` checks the HTTP status only.
Compare response bodies and resulting Odoo records before accepting a scenario.

Static sandbox cases are operation-isolated: IDs returned by one example may not work in
the next operation. Use documented dynamic scenarios for lifecycle verification.
Preserve the source and capture date when adding sanitized recordings to test fixtures.

The manual `amazon-sandbox-smoke` workflow requires its credential secrets and must
exist on the default branch to support workflow dispatch. It runs a credentialed order
import smoke test; it does not cover the full suite. A skipped test is not a pass.
