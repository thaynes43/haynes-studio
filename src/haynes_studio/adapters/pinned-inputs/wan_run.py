import sys,json,urllib.request,time
sys.path.insert(0,'/config/video');import api
p=json.load(sys.stdin);job=p['job'];graph=p['graph']
h=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=10))
if h.get('accepting_jobs') is not True or 'active_job' not in h or h['active_job'] is not None:
 raise RuntimeError('Live API busy or hold; no submission')
job['live_admission_readback']={'time':time.time(),'health':h}
raw_engine=api.engine
def original_engine(path,body=None):
 # A read poll can exceed the API's 20 s HTTP timeout while ComfyUI is busy (a 3-chunk S2V
 # job lost its prompt that way): retry reads a few times, never writes, and record it.
 for n in range(6):
  try:return raw_engine(path,body)
  except Exception as e:
   if body is not None or 'timed out' not in str(e) or n==5:raise
   job['engine_read_retries']=job.get('engine_read_retries',0)+1;time.sleep(5)
def observed_engine(path,body=None):
 if path.startswith('/history/'):
  q=original_engine('/queue')
  foreign=[e[1] for e in q.get('queue_running',[])+q.get('queue_pending',[]) if e[1]!=job.get('prompt_id')]
  if foreign:job['unexpected_work_seen']=sorted(set(job.get('unexpected_work_seen',[])+foreign))
 return original_engine(path,body)
api.engine=observed_engine
api.make_graph=lambda *args:graph
api.save(job);api.generate(job,p['prompt'])
print(json.dumps(job))
