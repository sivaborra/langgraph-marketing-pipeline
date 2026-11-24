"""Mint a demo credential (stands in for the OAuth authorization server).

Usage, in the same shell where MCP_EVAL_SECRET is set:
    python issue_token.py [--scope SCOPE] [--ttl SECONDS] [--expired]
Prints the token on stdout. The server verifies it on every call.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import mint_token

TOOL = "evaluate_marketing_draft"


def main():
    secret = os.environ.get("MCP_EVAL_SECRET")
    if not secret:
        print("MCP_EVAL_SECRET is not set", file=sys.stderr)
        raise SystemExit(1)
    parser = argparse.ArgumentParser(description="Mint a demo eval-service credential.")
    parser.add_argument("--scope", default=TOOL)
    parser.add_argument("--ttl", type=int, default=300)
    parser.add_argument("--expired", action="store_true", help="Mint an already-expired token (for testing).")
    args = parser.parse_args()
    ttl = -60 if args.expired else args.ttl
    print(mint_token(secret, args.scope, ttl))


if __name__ == "__main__":
    main()
