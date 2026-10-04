#!/bin/bash
# Disposable Odoo 18 verification; source checkout is mounted read-only.
# Usage: ./run-tests-local.sh [comma-separated addons]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_NAME="amazon-ci-$$-${RANDOM}"
NETWORK="${RUN_NAME}"
PG_CONTAINER="${RUN_NAME}-db"
TEST_CONTAINER="${RUN_NAME}-odoo"
OCA_IMAGE="${OCA_IMAGE:-ghcr.io/oca/oca-ci/py3.10-odoo18.0:latest}"
cleanup() {
    docker rm -f "$TEST_CONTAINER" "$PG_CONTAINER" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NETWORK" >/dev/null
docker run -d --name "$PG_CONTAINER" --network "$NETWORK" \
    -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=odoo \
    postgres:16-alpine >/dev/null
docker run -d --name "$TEST_CONTAINER" --platform linux/amd64 \
    --network "$NETWORK" -v "$REPO_DIR":/source:ro -w /workspace \
    -e PGHOST="$PG_CONTAINER" -e PGDATABASE=odoo -e PGUSER=odoo \
    -e PGPASSWORD=odoo -e INCLUDE="${1:-}" \
    --entrypoint tail "$OCA_IMAGE" -f /dev/null >/dev/null
docker exec "$TEST_CONTAINER" sh -ec '
    cp -a /source/. /workspace/
    python -c "from pathlib import Path; import shutil; p=Path(\".git\"); shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)"
    git init -b 18.0
    oca_install_addons
    oca_init_test_database
    oca_run_tests
'
