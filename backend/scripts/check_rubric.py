import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db

async def check():
    await connect_db()
    db = get_database()
    rubric = await db.rubrics.find_one({"evaluation_id": "6af58e618f4af877349910e9"})
    if not rubric:
        eval_doc = await db.evaluations.find_one({"_id": ObjectId("6af58e618f4af877349910e9")})
        if eval_doc and eval_doc.get("rubric_id"):
            rubric = await db.rubrics.find_one({"_id": ObjectId(eval_doc["rubric_id"])})
    print("Rubric title:", rubric.get("title") if rubric else None)
    comps = rubric.get("components", []) if rubric else []
    print(f"Total components: {len(comps)}")
    for c in comps:
        print(f"- {c.get('name')}: Part='{c.get('part')}', marks={c.get('marks')}, compulsory={c.get('is_compulsory')}, choice_group='{c.get('choice_group')}', choice_opt='{c.get('choice_option')}'")
    await close_db()

if __name__ == "__main__":
    asyncio.run(check())

