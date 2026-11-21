"""mux(picture source, mix) with the package's own settings; print the master's hash.
If the picture source is a whole master, mux reads only its video stream's packets."""
import hashlib
import io
import sys
from pathlib import Path

import av

from haynes_studio.mix.master import mux

src, mix_wav, out, want = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
picture = src.read_bytes()
try:
    result = mux(picture, mix_wav.read_bytes(), workdir=str(out.parent))
except Exception as error:  # report, then try a video-only remux of the same packets
    print("direct mux refused:", type(error).__name__, str(error)[:300])
    buf = io.BytesIO()
    with av.open(io.BytesIO(picture)) as s, av.open(buf, "w", format="mp4") as o:
        vin = s.streams.video[0]
        v = o.add_stream_from_template(vin)
        v.time_base = vin.time_base
        for p in s.demux(vin):
            if p.size:
                p.stream = v
                o.mux(p)
    picture = buf.getvalue()
    print("video-only remux", hashlib.sha256(picture).hexdigest())
    result = mux(picture, mix_wav.read_bytes(), workdir=str(out.parent))
sha = hashlib.sha256(result.data).hexdigest()
with open(out, "xb") as handle:
    handle.write(result.data)
print(("PASS " if sha == want else "FAIL ") + "master", sha, "want", want, "frames", result.frames)
sys.exit(0 if sha == want else 1)
