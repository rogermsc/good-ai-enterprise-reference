#!/bin/bash
# Ticket Triage Agent - Example curl commands
# Usage: ./curl.sh [p0|p2|p3|all]

set -e

BASE_URL="${API_URL:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOADS_DIR="$SCRIPT_DIR/payloads"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Common headers
HEADERS=(
    -H "Content-Type: application/json"
    -H "X-User-Id: agent-001"
    -H "X-Tenant-Id: acme-corp"
    -H "X-Roles: support_agent"
)

run_request() {
    local name=$1
    local file=$2

    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${YELLOW}Running: $name${NC}"
    echo -e "${BLUE}========================================${NC}\n"

    echo -e "${GREEN}Payload:${NC}"
    cat "$file" | jq .

    echo -e "\n${GREEN}Response:${NC}"
    curl -s -X POST "$BASE_URL/tickets/triage" \
        "${HEADERS[@]}" \
        -d @"$file" | jq .
}

run_p0() {
    run_request "P0 - Data Leak (Critical)" "$PAYLOADS_DIR/p0_data_leak.json"
}

run_p2() {
    run_request "P2 - Password Reset (Low)" "$PAYLOADS_DIR/p2_password_reset.json"
}

run_p3() {
    run_request "P3 - General Question (Info)" "$PAYLOADS_DIR/p3_general_question.json"
}

run_health() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${YELLOW}Health Check${NC}"
    echo -e "${BLUE}========================================${NC}\n"

    curl -s "$BASE_URL/health" | jq .
}

run_all() {
    run_health
    run_p0
    run_p2
    run_p3
}

# Show usage
usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  p0      Run P0 (Critical) data leak example"
    echo "  p2      Run P2 (Low) password reset example"
    echo "  p3      Run P3 (Info) general question example"
    echo "  health  Run health check"
    echo "  all     Run all examples (default)"
    echo ""
    echo "Environment variables:"
    echo "  API_URL  Base URL for API (default: http://localhost:8000)"
}

# Main
case "${1:-all}" in
    p0)
        run_p0
        ;;
    p2)
        run_p2
        ;;
    p3)
        run_p3
        ;;
    health)
        run_health
        ;;
    all)
        run_all
        ;;
    -h|--help)
        usage
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        usage
        exit 1
        ;;
esac

echo -e "\n${GREEN}Done!${NC}"
