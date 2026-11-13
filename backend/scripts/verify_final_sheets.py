import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db

async def verify():
    await connect_db()
    db = get_database()
    sheet_ids = ["6af7102b037ab2ac4817034b", "6af72005696f938164dd8725", "6af7256c696f938164dd8727"]
    for sid in sheet_ids:
        s = await db.sheets.find_one({"_id": ObjectId(sid)})
        print(f"\n==========================================")
        print(f"Student: {s.get('student_name')}")
        print(f"File: {s.get('file_name')} ({s.get('page_count')} pages)")
        print(f"Evaluation ID: {s.get('evaluation_id')}")
        print(f"Status: {s.get('status')}")
        print(f"Total Score: {s.get('total_score')} / {s.get('max_score')} (Grade: {s.get('evaluation_result',{}).get('grade')})")
        print(f"Part Subtotals: {s.get('part_subtotals')}")
        print(f"Marking Confidence: {s.get('marking_confidence')*100:.1f}% | OCR: {s.get('ocr_confidence')*100:.1f}%")
        comps = s.get('evaluation_result',{}).get('questions',[{}])[0].get('component_scores',[])
        print("Component Breakdown:")
        for c in comps:
            counted = "Counted" if c.get("is_counted_in_total") else "Skipped"
            print(f"  - [{counted}] {c.get('component')}: {c.get('marks_awarded')}/{c.get('max_marks')}")
    await close_db()

if __name__ == "__main__":
    asyncio.run(verify())

