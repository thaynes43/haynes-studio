"""Synthesize and check audition takes, one request at a time (story 840).

    python take.py <job_dir> run [--only ID ...] [--limit N]
    python take.py <job_dir> retry ID          # one retry of a failed take, by hand

Uses the story 425 clients (KokoroClient, WhisperClient) with SubprocessRunner. Each
take: one TTS request, the WAV written create-only to takes/<id>.wav, a decode check
(header, PyAV decode, level), its duration, then one transcript request and the PoC's
comparison plus declared recognizer spellings. One JSON record per attempt is appended
to takes.jsonl. Nothing retries by itself; `run` stops at the first service error, and
refuses to go past 150 TTS or 150 transcript requests in all.
"""
import argparse
import hashlib
import io
import json
import math
import re
import sys
import time
import unicodedata
import wave
from datetime import datetime, timezone
from pathlib import Path

from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest
from haynes_studio.adapters.runner import SubprocessRunner
from haynes_studio.adapters.whisper import TranscriptRequest, WhisperClient, heard_matches
from haynes_studio.library.model import KOKORO, take_signature

CAP = 150
SPEED = 1.0  # the client sends none; the server applies KOKORO_SPEED=1.0 to every request
# Recognizer spellings declared before the run, applied word by word (poc/edit.py's rule):
# the r4 manifest's own two, and digits for the label numbers.
TOLERANCES = {"340": "three hundred forty", "mos": "moss",
              **{str(i): w for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six"])}}


def words(s):
    return re.sub("[^a-z0-9 ]", " ", s.lower()).split()


def tolerated_match(heard, text, extra=None):
    tol = {**TOLERANCES, **(extra or {})}
    tol = {k.lower(): v.lower().split() for k, v in tol.items()}
    got = [w for word in words(heard) for w in tol.get(word, [word])]
    return got == words(text)


def decode_check(wav):
    """Header, a full decode with PyAV, and the level. Returns (facts, problem or None)."""
    import av
    import numpy as np
    with wave.open(io.BytesIO(wav)) as w:
        ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        pcm = np.frombuffer(w.readframes(frames), dtype="<i2").astype(np.float64) / 32768
    c = av.open(io.BytesIO(wav))
    decoded = sum(f.samples for f in c.decode(audio=0))
    c.close()
    rms = math.sqrt(float(np.mean(pcm ** 2))) if pcm.size else 0.0
    peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
    facts = {"channels": ch, "sample_width": width, "rate": rate, "frames": frames, "decoded_frames": decoded,
             "rms_dbfs": round(20 * math.log10(rms), 2) if rms > 0 else None,
             "peak_dbfs": round(20 * math.log10(peak), 2) if peak > 0 else None}
    problem = None
    if (ch, width) != (1, 2):
        problem = f"format {ch} ch {8 * width}-bit, expected mono 16-bit"
    elif decoded != frames:
        problem = f"decoded {decoded} frames, header says {frames}"
    elif rms <= 0 or 20 * math.log10(rms) < -45:
        problem = "near silent"
    elif peak >= 0.999:
        problem = "clipped"
    return facts, problem


def counts(log):
    tts = asr = 0
    if log.exists():
        for line in log.read_text().splitlines():
            r = json.loads(line)
            tts += r["requests"]["tts"]
            asr += r["requests"]["asr"]
    return tts, asr


def recheck(job, rec0):
    """Transcribe an existing take whose decode check stopped it before transcription."""
    log = job / "takes.jsonl"
    tts_n, asr_n = counts(log)
    if asr_n >= CAP:
        raise SystemExit("transcript cap reached")
    wav = (job / rec0["file"]).read_bytes()
    assert hashlib.sha256(wav).hexdigest() == rec0["sha256"]
    rec = {**rec0, "take_id": rec0["take_id"], "recheck_of": rec0["take_id"], "requests": {"tts": 0, "asr": 1},
           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    t1 = time.monotonic()
    try:
        heard = WhisperClient(SubprocessRunner()).transcribe(TranscriptRequest(wav)).text
    except AdapterError as e:
        rec.update(status="failed", reason=f"asr {e.code}: {e}")
        _append(log, rec)
        return
    rec["asr_s"] = round(time.monotonic() - t1, 2)
    tol = tolerated_match(heard, rec["text"])
    rec.update(heard=heard, heard_matches=heard_matches(heard, rec["text"]), match_with_tolerances=tol,
               status="passed" if tol else "failed",
               reason=None if tol else "transcript differs from the text after the declared tolerances")
    _append(log, rec)


def attempt(job, take, attempt_id, retry_of=None):
    log = job / "takes.jsonl"
    tts_n, asr_n = counts(log)
    if tts_n >= CAP or asr_n >= CAP:
        raise SystemExit(f"request cap reached: {tts_n} TTS, {asr_n} transcript")
    out = job / "takes" / f"{attempt_id}.wav"
    if out.exists():
        raise FileExistsError(out)
    text = unicodedata.normalize("NFC", take["text"])
    rec = {"take_id": attempt_id, "plan_id": take["id"], "retry_of": retry_of, "slot": take["slot"],
           "candidate": take["candidate"], "kind": take["kind"], "voice": take["voice"],
           "setting": {"speed": SPEED, "source": "server default (KOKORO_SPEED=1.0); the client sends no speed"},
           "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "signature": take_signature(KOKORO, take["voice"], text, SPEED),
           "r4_line": take.get("r4_line"), "current_voice": take.get("current_voice", False),
           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "requests": {"tts": 0, "asr": 0}, "status": None, "reason": None}
    runner = SubprocessRunner()
    t0 = time.monotonic()
    try:
        rec["requests"]["tts"] = 1
        sp = KokoroClient(runner).synthesize(SpeechRequest(take["voice"], text))
    except AdapterError as e:
        rec.update(status="failed", reason=f"tts {e.code}: {e}", tts_s=round(time.monotonic() - t0, 2))
        _append(log, rec)
        return rec, True
    rec["tts_s"] = round(time.monotonic() - t0, 2)
    out.parent.mkdir(exist_ok=True)
    with out.open("xb") as f:
        f.write(sp.wav)
    rec.update(file=f"takes/{out.name}", bytes=sp.bytes, sha256=sp.sha256,
               duration_s=sp.legacy_duration_s, duration_ms=math.ceil(sp.frames * 1000 / sp.rate))
    facts, problem = decode_check(sp.wav)
    rec["decode"] = facts
    rec["words_per_s"] = round(len(words(text)) / (sp.frames / sp.rate), 2)
    if problem:
        rec.update(status="failed", reason=f"decode check: {problem}")
        _append(log, rec)
        return rec, False
    t1 = time.monotonic()
    try:
        rec["requests"]["asr"] = 1
        heard = WhisperClient(runner).transcribe(TranscriptRequest(sp.wav)).text
    except AdapterError as e:
        rec.update(status="failed", reason=f"asr {e.code}: {e}", asr_s=round(time.monotonic() - t1, 2))
        _append(log, rec)
        return rec, True
    rec["asr_s"] = round(time.monotonic() - t1, 2)
    exact = heard_matches(heard, text)
    tol = tolerated_match(heard, text)
    rec.update(heard=heard, heard_matches=exact, match_with_tolerances=tol,
               status="passed" if tol else "failed",
               reason=None if tol else "transcript differs from the text after the declared tolerances")
    _append(log, rec)
    return rec, False


def _append(log, rec):
    with log.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    short = {k: rec.get(k) for k in ("take_id", "voice", "status", "duration_s", "tts_s", "asr_s", "heard", "reason")}
    print(json.dumps(short), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("mode", choices=["run", "retry", "recheck"])
    ap.add_argument("--text", help="retry only: new wording for a label (never for a script line)")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    job = Path(a.job)
    plan = {t["id"]: t for t in json.loads((job / "plan.json").read_text())["takes"]}
    log = job / "takes.jsonl"
    done = set()
    if log.exists():
        done = {json.loads(line)["plan_id"] for line in log.read_text().splitlines()}
    if a.mode == "retry":
        (pid,) = a.ids
        prior = [json.loads(line) for line in log.read_text().splitlines() if json.loads(line)["plan_id"] == pid]
        assert prior and all(r["status"] == "failed" for r in prior), "retry only a failed take"
        assert len(prior) == 1, "one retry per failed take"
        take = dict(plan[pid])
        if a.text:
            assert take["kind"] == "label", "only a label may be re-worded"
            take["text"] = a.text
        attempt(job, take, f"{pid}-retry1", retry_of=prior[0]["take_id"])
        return
    if a.mode == "recheck":
        (pid,) = a.ids
        prior = [json.loads(line) for line in log.read_text().splitlines() if json.loads(line)["plan_id"] == pid]
        assert len(prior) == 1 and prior[0]["reason"] == "decode check: clipped" and prior[0].get("heard") is None
        recheck(job, prior[0])
        return
    todo = [pid for pid in plan if pid not in done and (not a.ids or pid in a.ids)]
    if a.limit:
        todo = todo[:a.limit]
    for pid in todo:
        rec, service_error = attempt(job, plan[pid], pid)
        if service_error:
            sys.exit(f"stopped: service error on {pid}; nothing retried")


if __name__ == "__main__":
    main()
