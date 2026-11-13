import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db
from app.services.rubric_parser import parse_rubric_file

async def sync_rubrics():
    await connect_db()
    db = get_database()
    docx_path = r"d:\gradewiseAI\CIE_1_PAPERS\CIE1_Scheme_of_Evaluation.docx"
    print("Parsing Scheme of Evaluation from DOCX...")
    docx_comps = parse_rubric_file(docx_path)
    print(f"Extracted {len(docx_comps)} components from DOCX.")

    eval_ids = [
        "6af71001037ab2ac4817034a",
        "6af71fce696f938164dd8724",
        "6af7253e696f938164dd8726"
    ]

    for eid in eval_ids:
        await db.rubrics.update_one(
            {"evaluation_id": eid},
            {
                "$set": {
                    "evaluation_id": eid,
                    "subject": "DLCA",
                    "max_marks": 50.0,
                    "total_marks": 50.0,
                    "components": docx_comps,
                }
            },
            upsert=True
        )
        print(f"Synced rubric for Evaluation {eid} (10 slots, 50.0M).")

    await close_db()

if __name__ == "__main__":
    asyncio.run(sync_rubrics())

