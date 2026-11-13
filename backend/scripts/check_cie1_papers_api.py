import urllib.request
import json

url = 'http://127.0.0.1:8000/api/evaluations/6af7432333bb05d1ec4d6ace/results'
data = json.loads(urllib.request.urlopen(url).read().decode())
print('Summary:', data.get('summary'))
print('Total results:', len(data.get('results', [])))
for r in data.get('results', []):
    print(f"  - {r.get('student_name')}: {r.get('total_score')}/{r.get('max_score')} ({r.get('percentage')}%, Grade: {r.get('grade')})")

