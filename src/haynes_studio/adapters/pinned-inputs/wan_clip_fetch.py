import sys,hashlib,urllib.request
b=urllib.request.urlopen('http://127.0.0.1:8080/videos/'+sys.argv[1]+'/file',timeout=60).read()
sys.stderr.write('CLIP_SHA256 %s %d\n'%(hashlib.sha256(b).hexdigest(),len(b)));sys.stderr.flush()
sys.stdout.buffer.write(b)
