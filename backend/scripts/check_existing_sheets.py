import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from app.core.mongodb import get_database, connect_db, close_db

async def check():
    await connect_db()
    db = get_database()
    for eval_id in ["6af71001037ab2ac4817034a", "6af71fce696f938164dd8724", "6af7253e696f938164dd8726"]:
        e = await db.evaluations.find_one({"_id": eval_id})
        if not e:
            from bson import ObjectId
            e = await db.evaluations.find_one({"_id": ObjectId(eval_id)})
        print(f"\nEvaluation: {e.get('name')} (ID: {eval_id})")
        sheets = await db.sheets.find({"evaluation_id": eval_id}).to_list(10)
        for s in sheets:
            print(f"  Sheet: {s.get('file_name')} | Status: {s.get('status')} | Score: {s.get('total_score')} | Student: {s.get('student_name')}")
    await close_db()

if __name__ == "__main__":
    asyncio.run(check())

