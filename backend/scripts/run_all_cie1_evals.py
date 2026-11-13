import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
import asyncio
import time
import argparse
from bson import ObjectId
from app.core.mongodb import get_database, connect_db, close_db
from app.services.unified_vlm_service import get_unified_vlm_service

TARGETS = [
    {
        "name": "1BM25CD005",
        "eval_id": "6af71001037ab2ac4817034a",
        "sheet_id": "6af7102b037ab2ac4817034b",
    },
    {
        "name": "1BM25CD014",
        "eval_id": "6af71fce696f938164dd8724",
        "sheet_id": "6af72005696f938164dd8725",
    },
    {
        "name": "1BM25CD019",
        "eval_id": "6af7253e696f938164dd8726",
        "sheet_id": "6af7256c696f938164dd8727",
    },
]

async def evaluate_target(vlm_svc, target):
    print("\n" + "="*70)
    print(f"STARTING EVALUATION: {target['name']} (Eval: {target['eval_id']}, Sheet: {target['sheet_id']})")
    print("="*70)

    t0 = time.time()
    try:
        result = await vlm_svc.evaluate_sheet(target["eval_id"], target["sheet_id"])
        duration = time.time() - t0

        print(f"\n--- EVALUATION COMPLETED in {duration:.1f}s ---")
        print(f"Student: {result.get('student_name')}")
        print(f"Total Score: {result.get('total_score')} / {result.get('max_score')}")
        print(f"Part Subtotals: {result.get('part_subtotals')}")
        print(f"Grade: {result.get('evaluation_result', {}).get('grade')}")
        print(f"Needs Review: {result.get('needs_human_review')} (Reasons: {result.get('review_reasons')})")
        print(f"OCR Confidence: {result.get('ocr_confidence', 0)*100:.1f}%")
        print(f"Marking Confidence: {result.get('marking_confidence', 0)*100:.1f}%")

        comps = result.get("evaluation_result", {}).get("questions", [{}])[0].get("component_scores", [])
        print("\nComponent Breakdown:")
        for c in comps:
            counted = "Counted" if c.get("is_counted_in_total") else "Skipped"
            print(f"  [{counted}] {c.get('component')}: {c.get('marks_awarded')} / {c.get('max_marks')}")
            if c.get("is_counted_in_total"):
                fb = c.get("feedback", "")
                if len(fb) > 120:
                    fb = fb[:120] + "..."
                print(f"    Feedback: {fb}")

        return result
    except Exception as e:
        print(f"FAILED for {target['name']}: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["1BM25CD005", "1BM25CD014", "1BM25CD019", "all"], default="all")
    args = parser.parse_args()

    print("Connecting to MongoDB...")
    await connect_db()
    vlm_svc = get_unified_vlm_service()
    print(f"Initialized VLM Service (OCR: {vlm_svc.ocr_model}, Eval: {vlm_svc.eval_model})")

    targets_to_run = TARGETS if args.target == "all" else [t for t in TARGETS if t["name"] == args.target]

    summary = []
    for t in targets_to_run:
        res = await evaluate_target(vlm_svc, t)
        if res:
            summary.append({
                "student": res.get("student_name") or t["name"],
                "score": res.get("total_score"),
                "max": res.get("max_score"),
                "subtotals": res.get("part_subtotals"),
                "grade": res.get("evaluation_result", {}).get("grade"),
                "needs_review": res.get("needs_human_review"),
            })

    print("\n" + "="*70)
    print("ALL EVALUATIONS SUMMARY")
    print("="*70)
    for s in summary:
        print(f"Student: {s['student']:<25} | Score: {s['score']}/{s['max']} (Grade: {s['grade']}) | Subtotals: {s['subtotals']} | Review: {s['needs_review']}")

    await close_db()

if __name__ == "__main__":
    asyncio.run(main())

