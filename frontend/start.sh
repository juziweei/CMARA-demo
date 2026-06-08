#!/bin/bash
echo "========================================"
echo "  CMARA Demo Frontend Launcher"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "Starting local HTTP server on port 8080..."
echo ""
echo "Open this URL in your browser:"
echo "  http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop the server."
echo "========================================"
echo ""

python3 -m http.server 8080 || python -m http.server 8080
