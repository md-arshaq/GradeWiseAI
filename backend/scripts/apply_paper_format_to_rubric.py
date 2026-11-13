import sys, asyncio
sys.path.insert(0, r"d:\gradewiseAI\backend")
from app.core.mongodb import connect_db, get_database
from app.services.rubric_parser import normalize_to_paper_format
from bson import ObjectId

async def main():
    await connect_db()
    db = get_database()
    r_id = "6af710282620d4269223adea"
    rubric = await db.rubrics.find_one({"_id": ObjectId(r_id)})
    existing_comps = rubric.get("components", [])
    
    normalized = normalize_to_paper_format(existing_comps, raw_text="")
    print("New Normalized Components:", len(normalized))
    for c in normalized:
        print(f"  - {c['name']:<65} | {c['part']:<7} | Marks: {c['marks']} | Opt: {c['choice_option']}")
    
    await db.rubrics.update_one(
        {"_id": ObjectId(r_id)},
        {"$set": {"components": normalized, "total_marks": 50.0}}
    )
    print("Successfully updated rubric in MongoDB!")

if __name__ == "__main__":
    asyncio.run(main())

