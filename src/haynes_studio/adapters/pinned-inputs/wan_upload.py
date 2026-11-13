import pathlib,sys,hashlib
p=pathlib.Path('/workspace/input/studio-e0')/sys.argv[1];p.parent.mkdir(parents=True,exist_ok=True)
b=sys.stdin.buffer.read();assert len(b)<20000000 and hashlib.sha256(b).hexdigest()==sys.argv[2]
if p.exists():
 assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2],'different file already uploaded'
else:
 with p.open('xb') as f:f.write(b)
print(hashlib.sha256(p.read_bytes()).hexdigest())
