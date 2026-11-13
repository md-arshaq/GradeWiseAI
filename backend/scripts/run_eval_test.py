import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
import time
import json
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db
from app.services.unified_vlm_service import get_unified_vlm_service

async def run():
    print("Connecting to MongoDB...")
    await connect_db()
    db = get_database()
    
    eval_id = "6af71001037ab2ac4817034a"
    sheet_id = "6af7102b037ab2ac4817034b"
    
    sheet = await db.sheets.find_one({"_id": ObjectId(sheet_id)})
    if not sheet:
        print(f"Sheet {sheet_id} not found!")
        await close_db()
        return
        
    print(f"Sheet found: {sheet.get('file_name')} ({sheet.get('page_count')} pages)")
    
    vlm_svc = get_unified_vlm_service()
    print(f"OCR Model: {vlm_svc.ocr_model}, Eval Model: {vlm_svc.eval_model}")
    print(f"OCR Concurrency: {vlm_svc.ocr_concurrency}, Batch Size: {vlm_svc.ocr_batch_size}")
    
    t0 = time.time()
    try:
        result = await vlm_svc.evaluate_sheet(eval_id, sheet_id)
        duration = time.time() - t0
        print("\n" + "="*60)
        print(f"EVALUATION COMPLETED IN {duration:.1f}s")
        print("="*60)
        print(f"Student Name: {result.get('student_name')}")
        print(f"Total Score: {result.get('total_score')} / {result.get('max_score')}")
        grade = result.get('evaluation_result', {}).get('grade')
        print(f"Grade: {grade}")
        print(f"Needs Human Review: {result.get('needs_human_review')} (Reasons: {result.get('review_reasons')})")
        print(f"OCR Confidence: {result.get('ocr_confidence')*100:.1f}%")
        print(f"Marking Confidence: {result.get('marking_confidence')*100:.1f}%")
        
        per_page = result.get("per_page_transcripts", [])
        print(f"\nPer-Page Transcripts count: {len(per_page)}")
        for p in per_page:
            print(f"- Page {p.get('page_number')}: {len(p.get('text', ''))} chars | Questions: {p.get('detected_questions')} | OCR Conf: {p.get('page_ocr_confidence')}")
            
        print("\nRubric Component Breakdown:")
        comps = result.get("evaluation_result", {}).get("questions", [{}])[0].get("component_scores", [])
        for c in comps:
            counted = "✓ Counted" if c.get("is_counted_in_total") else "⊘ Skipped"
            print(f"- [{counted}] {c.get('component')}: {c.get('marks_awarded')} / {c.get('max_marks')} (Conf: {c.get('confidence')})")
            
    except Exception as e:
        print(f"Evaluation failed with exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_db()

if __name__ == "__main__":
    asyncio.run(run())

