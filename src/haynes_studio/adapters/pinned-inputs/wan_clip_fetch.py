import sys,hashlib,urllib.request
u='http://127.0.0.1:8080/videos/'+sys.argv[1]+'/file'
r=urllib.request.urlopen(u,timeout=60);b=r.read()
if r.geturl()!=u:raise RuntimeError('the clip read was redirected; refusing it')
sys.stderr.write('CLIP_SHA256 %s %d\n'%(hashlib.sha256(b).hexdigest(),len(b)));sys.stderr.flush()
sys.stdout.buffer.write(b)
