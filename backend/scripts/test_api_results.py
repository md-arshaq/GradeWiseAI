import urllib.request
import json

for eid in ['6af71001037ab2ac4817034a', '6af71fce696f938164dd8724', '6af7253e696f938164dd8726']:
    url = f'http://127.0.0.1:8000/api/evaluations/{eid}/results'
    try:
        req = urllib.request.urlopen(url)
        data = json.loads(req.read().decode())
        print(f"\nEval {eid}:")
        print(f"  Summary: {data.get('summary')}")
        print(f"  Sheets count: {len(data.get('sheets', []))}")
        for s in data.get('sheets', []):
            print(f"    - Student: {s.get('student_name')} | Score: {s.get('score')} | Status: {s.get('status')}")
    except Exception as e:
        print(f"Eval {eid} ERROR -> {e}")

