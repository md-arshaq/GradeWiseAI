import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from app.core.mongodb import get_database, connect_db, close_db

async def check():
    await connect_db()
    db = get_database()
    for eval_id in ["6af71001037ab2ac4817034a", "6af71fce696f938164dd8724", "6af7253e696f938164dd8726"]:
        sheets = await db.sheets.find({"evaluation_id": eval_id}).to_list(10)
        for s in sheets:
            print(f"{s.get('file_name')} -> completed_at: {s.get('evaluation_completed_at')} | score: {s.get('total_score')} | pages: {s.get('page_count')}")
    await close_db()

if __name__ == "__main__":
    asyncio.run(check())

