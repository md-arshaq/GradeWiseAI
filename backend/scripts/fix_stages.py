import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db

async def fix():
    await connect_db()
    db = get_database()
    await db.evaluations.update_many(
        {"_id": {"$in": [ObjectId("6af71001037ab2ac4817034a"), ObjectId("6af71fce696f938164dd8724"), ObjectId("6af7253e696f938164dd8726")]}},
        {"$set": {"pipeline_stage": "completed", "status": "completed"}}
    )
    print("Updated all 3 to completed.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(fix())

