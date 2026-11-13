import json, urllib.request
q = json.loads(urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=30).read())
print(json.dumps({'running': len(q['queue_running']), 'pending': len(q['queue_pending'])}))
