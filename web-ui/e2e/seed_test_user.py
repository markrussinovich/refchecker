"""
Seed a test user into the refchecker database and print a valid JWT token.
Used by Playwright e2e tests to simulate an authenticated session.

Usage:
    python web-ui/e2e/seed_test_user.py
    # prints the JWT token to stdout
"""
import sys
import os
import asyncio
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
except ImportError:
    pass

from backend.database import db
from backend.auth import create_access_token


async def main():
    await db.init_db()
    user_id = await db.create_or_update_user(
        provider="github",
        provider_id="test-playwright-user-12345",
        email="playwright@test.local",
        name="Playwright Test User",
        avatar_url=None,
    )
    token = create_access_token(user_id, "playwright@test.local", "Playwright Test User")
    # Print JSON so Playwright can parse it
    print(json.dumps({"user_id": user_id, "token": token}))


if __name__ == "__main__":
    asyncio.run(main())
