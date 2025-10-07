#!/usr/bin/env bash
set -euo pipefail

# Usage: ./demo.sh [API_PORT]
PORT=${1:-5000}

echo "Showing side image overlay..."
curl -s -X POST http://localhost:${PORT}/show-overlay \
  -H 'Content-Type: application/json' \
  -d '{"position":"side","type":"image","content":"./tests/media/test.png","width":240,"duration":15}' | jq . || true

sleep 2

echo "Showing bottom ticker..."
curl -s -X POST http://localhost:${PORT}/show-overlay \
  -H 'Content-Type: application/json' \
  -d '{"position":"bottom","type":"text","content":"Demo: Tonight 9PM New Episode","scroll":true,"height":96,"duration":20}' | jq . || true

sleep 5

echo "Playing interrupt ad..."
curl -s -X POST http://localhost:${PORT}/play-interrupt-ad \
  -H 'Content-Type: application/json' \
  -d '{"file":"./tests/media/test_ad.mp4"}' | jq . || true

echo "Demo sequence triggered."


