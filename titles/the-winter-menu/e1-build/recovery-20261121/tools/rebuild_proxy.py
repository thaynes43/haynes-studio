import hashlib, sys
from haynes_studio.delivery.media import make_proxy
from haynes_studio.delivery.model import PROXY_SIZES, SHORT, proxy_byte_limit
src, dest, want = sys.argv[1:4]
w, h = PROXY_SIZES[SHORT]
make_proxy(src, dest, width=w, height=h, frames=1087, threads=2)
data = open(dest, "rb").read(); sha = hashlib.sha256(data).hexdigest()
print(("PASS " if sha == want else "FAIL ") + "proxy", sha, "want", want, len(data), "bytes, limit", proxy_byte_limit(1087))
sys.exit(0 if sha == want else 1)
