import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db

async def check():
    await connect_db()
    db = get_database()
    for sheet_id in ["6af72005696f938164dd8725", "6af7256c696f938164dd8727"]:
        s = await db.sheets.find_one({"_id": ObjectId(sheet_id)})
        p1 = s.get("per_page_transcripts", [{}])[0].get("text", "")
        print(f"=== Sheet {s.get('file_name')} ===")
        print(p1[:300])
        print("---")
    await close_db()

if __name__ == "__main__":
    asyncio.run(check())

