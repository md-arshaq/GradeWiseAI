import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
from app.services.rubric_parser import normalize_to_paper_format

comps = normalize_to_paper_format([], raw_text="")
print(f"Total slots normalized: {len(comps)}")
for c in comps:
    print(f"  Slot: {c['name']:<65} | Part: {c['part']:<7} | Marks: {c['marks']} | Compulsory: {str(c['is_compulsory']):<5} | Group: {c['choice_group']:<15} | Opt: {c['choice_option']}")

