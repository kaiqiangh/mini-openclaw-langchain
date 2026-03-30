#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${SANDBOX_IMAGE_NAME:-python-repl-sandbox}"
IMAGE_TAG="${SANDBOX_IMAGE_TAG:-latest}"

echo "Building ${IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "${SCRIPT_DIR}"
echo "Done. Run with: docker run --rm -i ${IMAGE_NAME}:${IMAGE_TAG}"
