"""Build takes.json from takes.jsonl (story 840): one record per planned take, every
attempt kept, the final check result under the declared tolerances, and per-voice
measurements (median pitch, speaking rate). No service calls.

    python records.py <job_dir> <out takes.json>
"""
import hashlib
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

# Declared before the run (tools/take.py): the r4 manifest's two, and label digits.
BEFORE = {"340": "three hundred forty", "mos": "moss",
          **{str(i): w for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six"])}}
# Declared after reading the results, each with its reason; applied word by word (a
# heard word) or as an exact phrase, as poc/edit.py applies a manifest's tolerances.
AFTER_PHRASES = [
    {"heard": "need salt", "means": "needs salt", "applies_to": "line",
     "why": "the same af_heart bytes were heard as 'Need salt.' in r2, r3 and r4 (evidence-r2..r4/speech.json, "
            "sha256 4e12138ee373...); an s-s merge at the word boundary that the recognizer makes"},
    {"heard": "is abella", "means": "isabella", "applies_to": "label",
     "why": "proper name the recognizer does not know; the card shows the voice ID"},
]
AFTER_WORDS = [
    {"heard": "core", "means": "kore", "applies_to": "label", "why": "proper name; 'core' is how Kore is said"},
    {"heard": "corn", "means": "kore", "applies_to": "label",
     "why": "proper name; heard as 'Corn' in the whole-reel transcript of reel A's first build"},
    {"heard": "auled", "means": "aoede", "applies_to": "label", "why": "proper name the recognizer does not know"},
    {"heard": "ayuled", "means": "aoede", "applies_to": "label", "why": "proper name the recognizer does not know"},
    {"heard": "dahl", "means": "doll", "applies_to": "label",
     "why": "American 'doll' heard as the name Dahl (the A and D intros were heard as 'Doll')"},
]
GRADES = {  # Kokoro VOICES.md (hexgrad/Kokoro-82M), read 2026-11-13: target quality / overall grade
    "af_heart": ("A", "flagship, overall grade not printed"), "af_bella": ("A", "A-"), "af_nicole": ("B", "B-"),
    "bf_emma": ("B", "B-"), "af_aoede": ("B", "C+"), "af_kore": ("B", "C+"), "af_sarah": ("B", "C+"),
    "af_alloy": ("B", "C"), "af_nova": ("B", "C"), "bf_isabella": ("B", "C"), "af_sky": ("B", "C-"),
    "af_jessica": ("C", "D"), "af_river": ("C", "D"), "bf_alice": ("C", "D"), "bf_lily": ("C", "D"),
    "am_michael": ("B", "C+"),
}
# Duration check: a line within half to double the r4 take of the same line (the timing
# Tom signed off); a label 0.5 to 4 s. Speaking rate is whitespace words per second.
LINE_RATIO = (0.5, 2.0)
LABEL_S = (0.5, 4.0)
R4_SPEECH = "titles/the-winter-menu/evidence-r4/speech.json"


def words(s):
    return re.sub("[^a-z0-9 ]", " ", s.lower()).split()


def tolerated(heard, text, kind):
    tol = {k: v.split() for k, v in BEFORE.items()}
    tol.update({w["heard"]: w["means"].split() for w in AFTER_WORDS if w["applies_to"] == kind})
    got = [x for w in words(heard) for x in tol.get(w, [w])]
    used = sorted({w for w in words(heard) if w in tol and tol[w] != [w]})
    for p in AFTER_PHRASES:
        if p["applies_to"] != kind:
            continue
        wrong, right = words(p["heard"]), words(p["means"])
        for i in range(len(got) - len(wrong) + 1):
            if got[i:i + len(wrong)] == wrong:
                got = got[:i] + right + got[i + len(wrong):]
                used.append(p["heard"])
                break
    return got == words(text), used


def median_f0(path):
    """Median pitch over voiced 40 ms frames (normalized autocorrelation, 70 to 450 Hz)."""
    with wave.open(str(path)) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    n, hop = int(0.04 * rate), int(0.01 * rate)
    lo, hi = int(rate / 450), int(rate / 70)
    level = np.sqrt(np.mean(x ** 2))
    f0 = []
    for s in range(0, len(x) - n, hop):
        fr = x[s:s + n] - x[s:s + n].mean()
        if np.sqrt(np.mean(fr ** 2)) < 0.5 * level:
            continue
        ac = np.correlate(fr, fr, "full")[n - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.5:
            f0.append(rate / lag)
    return round(float(np.median(f0)), 1) if f0 else None


def main(job, out, repo="."):
    job = Path(job)
    r4 = {(l["shot"], l["k"]): l["duration_s"] for l in json.loads((Path(repo) / R4_SPEECH).read_text())["lines"]}
    plan = json.loads((job / "plan.json").read_text())
    attempts = [json.loads(line) for line in (job / "takes.jsonl").read_text().splitlines()]
    takes, voices = [], {}
    for t in plan["takes"]:
        tries = [a for a in attempts if a["plan_id"] == t["id"]]
        final = tries[-1]
        wav = job / final["file"]
        assert hashlib.sha256(wav.read_bytes()).hexdigest() == final["sha256"]
        wps = round(len(final["text"].split()) / final["duration_s"], 2)
        if t["kind"] == "line":
            r4_s = r4[(t["r4_line"]["shot"], t["r4_line"]["k"])]
            ratio = round(final["duration_s"] / r4_s, 2)
            dur_ok = LINE_RATIO[0] <= ratio <= LINE_RATIO[1]
        else:
            r4_s = ratio = None
            dur_ok = LABEL_S[0] <= final["duration_s"] <= LABEL_S[1]
        decodes = final["decode"]["decoded_frames"] == final["decode"]["frames"] and final["decode"]["channels"] == 1
        clipped = final["decode"]["peak_dbfs"] is not None and final["decode"]["peak_dbfs"] >= -0.01
        if final.get("heard") is None:
            tmatch, used = False, []
        else:
            tmatch, used = tolerated(final["heard"], final["text"], t["kind"])
        passed = decodes and dur_ok and tmatch
        problems = []
        if not decodes:
            problems.append("does not decode")
        if not dur_ok:
            problems.append(f"duration {final['duration_s']} s outside the bound" +
                            (f" ({ratio} x the r4 take)" if ratio else ""))
        if not tmatch:
            problems.append(f"transcript check: heard {final.get('heard')!r}")
        reason = "; ".join(problems) or None
        f0 = median_f0(wav)
        rec = {"id": t["id"], "slot": t["slot"], "candidate": t["candidate"], "kind": t["kind"],
               "voice": t["voice"], "current_voice": t.get("current_voice", False), "r4_line": t.get("r4_line"),
               "setting": final["setting"], "text": final["text"], "text_sha256": final["text_sha256"],
               "signature": final["signature"], "file": final["file"], "sha256": final["sha256"],
               "bytes": final["bytes"], "rate": final["decode"]["rate"], "frames": final["decode"]["frames"],
               "duration_s": final["duration_s"], "duration_ms": final["duration_ms"],
               "words_per_s": wps, "r4_duration_s": r4_s, "duration_vs_r4": ratio, "rms_dbfs": final["decode"]["rms_dbfs"],
               "peak_dbfs": final["decode"]["peak_dbfs"], "median_f0_hz": f0,
               "checks": {"decodes": decodes, "duration_ok": dur_ok,
                          "full_scale_samples_warning": clipped,
                          "heard": final.get("heard"), "exact_match": final.get("heard_matches"),
                          "match_with_tolerances": tmatch, "tolerances_used": used},
               "status": "passed" if passed else "failed", "reason": reason,
               "attempts": [{"take_id": a["take_id"], "started_at": a["started_at"], "sha256": a.get("sha256"),
                             "text": a["text"], "status_at_run": a["status"], "reason_at_run": a["reason"],
                             "heard": a.get("heard"), "requests": a["requests"], "tts_s": a.get("tts_s"),
                             "asr_s": a.get("asr_s"), "retry_of": a.get("retry_of"),
                             "recheck_of": a.get("recheck_of")} for a in tries]}
        takes.append(rec)
        if t["kind"] == "line":
            v = voices.setdefault(t["voice"], {"f0": [], "wps": [], "takes": 0, "passed": 0})
            v["takes"] += 1
            v["passed"] += passed
            v["wps"].append(wps)
            if f0:
                v["f0"].append(f0)
    lab = [r for r in takes if r["voice"] == plan["label_voice"]]
    voice_facts = {}
    for name, v in sorted(voices.items()):
        voice_facts[name] = {"accent": {"a": "American English", "b": "British English"}[name[0]], "sex": "female",
                             "kokoro_target_quality": GRADES[name][0], "kokoro_overall_grade": GRADES[name][1],
                             "median_f0_hz": round(float(np.median(v["f0"])), 1) if v["f0"] else None,
                             "median_words_per_s": round(float(np.median(v["wps"])), 2),
                             "takes": v["takes"], "passed": v["passed"]}
    doc = {"story": plan["story"], "source_manifest": plan["source_manifest"], "label_voice": plan["label_voice"],
           "engine": "Kokoro-82M v1.0",
           "requests": {"tts": sum(a["requests"]["tts"] for a in attempts),
                        "asr": sum(a["requests"]["asr"] for a in attempts), "cap_each": 150},
           "tolerances": {"declared_before_run": BEFORE, "declared_after_run_words": AFTER_WORDS,
                          "declared_after_run_phrases": AFTER_PHRASES},
           "duration_rule": {"line": f"{LINE_RATIO[0]} to {LINE_RATIO[1]} times the r4 take of the same line ({R4_SPEECH})",
                             "label": f"{LABEL_S[0]} to {LABEL_S[1]} s"},
           "summary": {"planned": len(takes), "passed": sum(r["status"] == "passed" for r in takes),
                       "failed": [r["id"] for r in takes if r["status"] == "failed"],
                       "label_voice_median_f0_hz": round(float(np.median([r["median_f0_hz"] for r in lab
                                                                           if r["median_f0_hz"]])), 1)},
           "voices": voice_facts, "takes": takes}
    with open(out, "x") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(json.dumps(doc["summary"], indent=1))
    for k, v in voice_facts.items():
        print(k, v)


if __name__ == "__main__":
    main(*sys.argv[1:])
