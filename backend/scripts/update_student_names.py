import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db

async def update_names():
    await connect_db()
    db = get_database()
    await db.sheets.update_one(
        {"_id": ObjectId("6af72005696f938164dd8725")},
        {"$set": {"student_name": "Anjali Umesh Pavaskar (1BM25CD014)"}}
    )
    await db.sheets.update_one(
        {"_id": ObjectId("6af7256c696f938164dd8727")},
        {"$set": {"student_name": "Ashmita Hati (1BM25CD019)"}}
    )
    print("Updated student names successfully.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(update_names())

