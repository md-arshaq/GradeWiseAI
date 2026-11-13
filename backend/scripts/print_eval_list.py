import urllib.request
import json

resp = urllib.request.urlopen('http://127.0.0.1:8000/api/evaluations')
data = json.loads(resp.read().decode())
print("Evaluations on Home Page:")
for e in data.get('evaluations', []):
    print(f"- {e.get('name')} (ID: {e.get('id')}) | Status: {e.get('status')} | Stage: {e.get('pipeline_stage')}")

