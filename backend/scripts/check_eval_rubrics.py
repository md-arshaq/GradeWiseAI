import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from app.core.mongodb import get_database, connect_db, close_db

async def check():
    await connect_db()
    db = get_database()
    for eval_id in ["6af71001037ab2ac4817034a", "6af71fce696f938164dd8724", "6af7253e696f938164dd8726"]:
        r = await db.rubrics.find_one({"evaluation_id": eval_id})
        e = await db.evaluations.find_one({"_id": eval_id})
        if not e:
            from bson import ObjectId
            e = await db.evaluations.find_one({"_id": ObjectId(eval_id)})
        print(f"Eval: {e.get('name')} (ID: {eval_id})")
        if r:
            print(f"  Rubric subject: {r.get('subject')} | comps: {len(r.get('components', []))}")
            for c in r.get('components', []):
                print(f"    - {c.get('name')} [{c.get('marks')}M]")
        else:
            print("  No rubric found!")
    await close_db()

if __name__ == "__main__":
    asyncio.run(check())

