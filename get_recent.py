import urllib.request
import json
url = "http://localhost:8888/memory/search"
data = json.dumps({"query": "review before merge", "limit": 20, "project": "shared-memory-monitor"}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + open('.env').read().split('AGENT_TOKEN=')[1].split('\n')[0]})
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(e)
