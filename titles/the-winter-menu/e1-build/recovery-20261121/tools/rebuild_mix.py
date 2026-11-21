"""Rebuild the board voice tracks and the mix of a recorded Winter Menu run, checking
every key and hash against the committed run record. Writes only into OUT (new)."""
import hashlib
import json
import sys
from pathlib import Path

from haynes_studio.cache.keys import board_voice_track_key, mix_key
from haynes_studio.mix.mixer import MIXER, mix
from haynes_studio.voice.track import assemble, read_wav

run_path, inputs_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out_dir.mkdir()  # must be new
run = json.loads(run_path.read_text())
o = run["outputs"]
p = o["placement"]

blobs = {}
for f in inputs_dir.iterdir():
    data = f.read_bytes()
    blobs[hashlib.sha256(data).hexdigest()] = data

report = {"run": run["id"], "checks": []}


def check(name, got, want):
    ok = got == want
    report["checks"].append({"check": name, "got": got, "want": want, "ok": ok})
    print(("PASS " if ok else "FAIL ") + name, got[:20], want[:20])
    return ok


# Takes per spoken board, in stage order (one stage per board; board 7 has no take).
takes_by_board = [[a["sha256"] for a in st["artifacts"] if a["kind"] == "voice_take"]
                  for st in run["stages"]]
takes_by_board = [t for t in takes_by_board if t]
tracks_lines = {}
for line in p["lines"]:
    tracks_lines.setdefault(line["track"], []).append(line)
assert len(takes_by_board) == len(tracks_lines), (len(takes_by_board), len(tracks_lines))

voice_tracks = []
for t in sorted(tracks_lines):
    lines = sorted(tracks_lines[t], key=lambda x: x["line"])
    takes = takes_by_board[t]
    assert len(takes) == len(lines)
    spans = [[x["board_start_ms"], x["board_end_ms"]] for x in lines]
    data = assemble([read_wav(blobs[h]) for h in takes], [s[0] for s in spans], spans[-1][1])
    sha = hashlib.sha256(data).hexdigest()
    check(f"voice_track/{t}", sha, lines[0]["track_sha256"])
    blobs[sha] = data
    voice_tracks.append({"track": sha, "start_frame": lines[0]["start_frame"], "spans": spans})

sounds = [{"sound": s["sha256"], "start_sample": s["start_sample"], "trim_ms": s["trim_ms"],
           "level_rms_dbfs": s["level_rms_dbfs"]} for s in p["sounds"]]
beds = [{"sound": b["sha256"], "level_rms_dbfs": b["level_rms_dbfs"], "clock": "film"}
        for b in p["beds"]]
key = mix_key(voice_tracks=voice_tracks, sounds=sounds, beds=beds, line_rms_dbfs=-22,
              master_lufs=-20, true_peak_dbtp=-3.5, frames=o["frames"], rate=p["rate"],
              mixer=p["mixer"])
if not check("mix_key", key.value, o["keys"]["mix"]):
    (out_dir / "report.json").write_text(json.dumps(report, indent=1))
    sys.exit(2)
check("mixer_version", MIXER.version(), p["mixer"])

result = mix(key.document, lambda sha, where: blobs[sha])
wav = result.wav if hasattr(result, "wav") else result.data
sha = hashlib.sha256(wav).hexdigest()
ok = check("mix", sha, o["mix_sha256"])
(out_dir / "mix.wav").write_bytes(wav)
report["mix_key_document"] = json.loads(json.dumps(key.document, default=list))
(out_dir / "report.json").write_text(json.dumps(report, indent=1))
sys.exit(0 if ok else 1)
