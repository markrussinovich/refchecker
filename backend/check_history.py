import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from database import Database

async def main():
    db = Database()
    await db.init_db()
    history = await db.get_history(limit=10)
    with open('history_output.txt', 'w') as f:
        f.write(f"Found {len(history)} history entries\n")
        for h in history:
            f.write(f"  ID={h['id']}: {h['paper_title'][:50]}... refs={h['total_refs']}\n")
    print("Output written to history_output.txt")

asyncio.run(main())
