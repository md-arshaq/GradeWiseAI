import sys, asyncio
sys.path.insert(0, r"d:\gradewiseAI\backend")
from app.core.mongodb import connect_db, get_database
from bson import ObjectId

async def main():
    await connect_db()
    db = get_database()
    ev_id = "6af71001037ab2ac4817034a"
    ev = await db.evaluations.find_one({"_id": ObjectId(ev_id)})
    print("EVAL:", ev.get("name"), "| status:", ev.get("status"), "| pipeline_stage:", ev.get("pipeline_stage"))
    r_id = ev.get("rubric_id")
    if r_id:
        rubric = await db.rubrics.find_one({"_id": ObjectId(r_id)})
        if rubric:
            print("Rubric Components count:", len(rubric.get("components", [])))
            for c in rubric.get("components", []):
                print(f"  - {c.get('name')[:50]:<52} | Marks: {c.get('marks')} | Part: {c.get('part')} | Group: {c.get('choice_group')} | Opt: {c.get('choice_option')}")
    sheets = await db.sheets.find({"evaluation_id": ev_id}).to_list(10)
    for s in sheets:
        print("Sheet:", s.get("_id"), "| file_name:", s.get("file_name"), "| status:", s.get("status"), "| page_count:", s.get("page_count"))

if __name__ == "__main__":
    asyncio.run(main())
