import sys
sys.path.insert(0, r"d:\gradewiseAI\backend")
from app.services.rubric_parser import parse_rubric_file

comps = parse_rubric_file(r"d:\gradewiseAI\CIE_1_PAPERS\CIE1_Scheme_of_Evaluation.docx")
for i, c in enumerate(comps):
    print(f"[{i+1}] {c['name']} ({c['marks']}M, {c['part']})")
    print(f"    Choice: {c.get('choice_group')}:{c.get('choice_option')} | Compulsory: {c.get('is_compulsory')}")
    print(f"    Model Answer ({len(c.get('model_answer',''))} chars): {c.get('model_answer','')[:150]}...")
    print(f"    Mark Bands: {c.get('mark_bands','')}\n")

