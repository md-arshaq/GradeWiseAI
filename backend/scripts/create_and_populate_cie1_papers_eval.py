import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import os
import shutil
import asyncio
from datetime import datetime, timezone
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db
from app.services.rubric_parser import parse_rubric_file

async def setup():
    await connect_db()
    db = get_database()

    # 1. Parse DOCX rubric
    docx_path = r"d:\gradewiseAI\CIE_1_PAPERS\CIE1_Scheme_of_Evaluation.docx"
    print("Parsing Scheme of Evaluation from DOCX...")
    docx_comps = parse_rubric_file(docx_path)
    print(f"Extracted {len(docx_comps)} components.")

    # 2. Check if CIE_1_PAPERS evaluation already exists
    existing = await db.evaluations.find_one({"name": "CIE_1_PAPERS"})
    if existing:
        eval_id = str(existing["_id"])
        print(f"Found existing evaluation CIE_1_PAPERS (ID: {eval_id})")
    else:
        eval_obj_id = ObjectId()
        eval_id = str(eval_obj_id)
        rubric_obj_id = ObjectId()
        eval_doc = {
            "_id": eval_obj_id,
            "name": "CIE_1_PAPERS",
            "subject": "DLCA",
            "max_marks": 50.0,
            "total_marks": 50.0,
            "answer_type": "handwritten",
            "status": "completed",
            "pipeline_stage": "completed",
            "rubric_id": str(rubric_obj_id),
            "rubric_file": "CIE1_Scheme_of_Evaluation.docx",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "latest_run_id": "run_cie_1_papers",
        }
        await db.evaluations.insert_one(eval_doc)
        print(f"Created new evaluation CIE_1_PAPERS (ID: {eval_id})")

    # 3. Insert or update Rubric
    await db.rubrics.update_one(
        {"evaluation_id": eval_id},
        {
            "$set": {
                "evaluation_id": eval_id,
                "subject": "DLCA",
                "max_marks": 50.0,
                "total_marks": 50.0,
                "components": docx_comps,
            }
        },
        upsert=True
    )
    print(f"Rubric synced for CIE_1_PAPERS.")

    # 4. Prepare target upload directory
    target_upload_dir = os.path.join(r"d:\gradewiseAI\backend\uploads", eval_id)
    os.makedirs(target_upload_dir, exist_ok=True)

    # 5. Source evaluations to copy sheet data from
    source_sheets_info = [
        {"eval_id": "6af71001037ab2ac4817034a", "sheet_id": "6af7102b037ab2ac4817034b", "name": "Aayushi Choudhury (1BM25CD005)"},
        {"eval_id": "6af71fce696f938164dd8724", "sheet_id": "6af72005696f938164dd8725", "name": "Anjali Umesh Pavaskar (1BM25CD014)"},
        {"eval_id": "6af7253e696f938164dd8726", "sheet_id": "6af7256c696f938164dd8727", "name": "Ashmita Hati (1BM25CD019)"},
    ]

    # Clean existing sheets in this evaluation to prevent duplicates
    await db.sheets.delete_many({"evaluation_id": eval_id})

    for info in source_sheets_info:
        src_sheet = await db.sheets.find_one({"_id": ObjectId(info["sheet_id"])})
        if not src_sheet:
            print(f"Warning: could not find source sheet {info['sheet_id']}")
            continue

        src_upload_dir = os.path.join(r"d:\gradewiseAI\backend\uploads", info["eval_id"])
        
        # Copy page images
        new_pages = []
        for p in src_sheet.get("pages", []):
            fn = p.get("file_name", "")
            src_file = os.path.join(src_upload_dir, fn)
            dst_file = os.path.join(target_upload_dir, fn)
            if os.path.exists(src_file) and not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)
            
            new_pages.append({
                "page_number": p.get("page_number", 1),
                "file_name": fn,
                "file_path": os.path.relpath(dst_file, r"d:\gradewiseAI\backend"),
                "file_size": p.get("file_size", 0),
            })

        new_sheet_doc = dict(src_sheet)
        new_sheet_doc["_id"] = ObjectId()
        new_sheet_doc["evaluation_id"] = eval_id
        new_sheet_doc["student_name"] = info["name"]
        new_sheet_doc["pages"] = new_pages
        if new_pages:
            new_sheet_doc["file_path"] = new_pages[0]["file_path"]

        await db.sheets.insert_one(new_sheet_doc)
        print(f"Added sheet for {info['name']}: {new_sheet_doc['total_score']} / {new_sheet_doc['max_score']} (Grade: {new_sheet_doc.get('evaluation_result',{}).get('grade')})")

    # Update evaluation status
    await db.evaluations.update_one(
        {"_id": ObjectId(eval_id)},
        {"$set": {"status": "completed", "pipeline_stage": "completed"}}
    )
    print("\nCIE_1_PAPERS evaluation successfully created and populated in MongoDB!")
    await close_db()

if __name__ == "__main__":
    asyncio.run(setup())

