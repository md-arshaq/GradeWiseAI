import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
from app.services.rubric_parser import parse_rubric_file

comps = parse_rubric_file(r"d:\gradewiseAI\CIE_1_PAPERS\CIE1_Scheme_of_Evaluation.docx")
print(f"Component count: {len(comps)}")
for c in comps:
    print(f"- {c.get('name')} [{c.get('part')}] -> {c.get('marks')}M (choice: {c.get('choice_group')}:{c.get('choice_option')})")
    print(f"  Model answer length: {len(c.get('model_answer', ''))}")
