import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from app.core.mongodb import get_database, connect_db, close_db

async def main():
    await connect_db()
    db = get_database()
    evals = await db.evaluations.find().to_list(100)
    for e in evals:
        print(f"ID: {e['_id']} | Name: {e.get('name')} | Subject: {e.get('subject')} | Status: {e.get('status')} | Total Marks: {e.get('total_marks')}")
    await close_db()

if __name__ == "__main__":
    asyncio.run(main())

