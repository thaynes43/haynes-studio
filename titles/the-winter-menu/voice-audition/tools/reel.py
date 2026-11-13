"""Build one private audition reel for one cast slot (story 840), in the shape that
poc/deliver.py delivers: a reel job directory with speech.json, the takes, title cards,
and reel/{final.mp4, soundtrack.wav, dialogue-only.wav, timeline.json, shots.json,
frame-transforms.json, validation.json, dialogue-transcript.json, contact-sheet.jpg}.

    python reel.py <job_dir> <takes.json> <slot> <repo> <reel manifest out>

Everything is create-only. The mix follows poc/edit.py: each take at -22 dBFS RMS with
5 ms edges, then -20 LUFS with a limiter 1 dB under the -3.5 dBTP target, 48 kHz
24-bit. The picture is one still card per candidate (no motion), H.264 CRF 18 at 12
fps with 2 threads, AAC 192 kbit/s. One transcript request checks the whole reel.
"""
import hashlib
import json
import math
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 12
LUFS, TP = -20.0, -3.5
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
BG, INK, ACCENT, DIM = (20, 33, 61), (240, 240, 240), (252, 196, 17), (160, 170, 190)
ROLES = {  # from titles/the-winter-menu/brief.md (cast table)
    "a": ("the captain", "proud survivalist; ash-blonde, crown of twigs; r4 lines 1 and 4"),
    "b": ("the chair", "deadpan chair of the meeting; r4 lines 2, 8 (Motion carried) and 9"),
    "c": ("the grudge holder", "suspicious, arms crossed; r4 lines 3 and 6"),
    "d": ("the cheerful one", "cheerful, protests in r4; lines 5 and 8 (Nay!)"),
}
ACCENT_NAME = {"a": "American English", "b": "British English"}
GAP_AFTER_LABEL, GAP_LINE, GAP_CANDIDATE, LEAD, TAIL, SILENT_CARD = 0.5, 0.8, 1.2, 0.6, 1.2, 3.5


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def card(path, header, big, sub, body, footer):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=ACCENT)
    y = 50
    for line in header:
        d.text((48, y), line, font=font(FONT, 28), fill=DIM)
        y += 40
    y += 20
    for size, text in big:
        d.text((48, y), text, font=font(BOLD, size), fill=ACCENT if size >= 70 else INK)
        y += int(size * 1.2)
    y += 10
    for para in sub:
        for line in textwrap.wrap(para, 40):
            d.text((48, y), line, font=font(FONT, 32), fill=INK)
            y += 44
    y += 30
    for para in body:
        for line in textwrap.wrap(para, 38):
            d.text((48, y), line, font=font(FONT, 30), fill=INK if not para.startswith("Not played") else DIM)
            y += 40
        y += 18
    fy = H - 60 - 44 * len(footer)
    for line in footer:
        d.text((48, fy), line, font=font(BOLD, 34), fill=ACCENT)
        fy += 44
    with open(path, "xb") as f:
        im.save(f, "PNG")


def main(job, records, slot, repo, manifest_out, build=None):
    job, repo = Path(job), Path(repo)
    sys.path.insert(0, str(repo / "poc"))
    from studio import ffmpeg, levels, read_audio, write_audio  # PoC helpers, 2 threads
    from haynes_studio.adapters.runner import SubprocessRunner
    from haynes_studio.adapters.whisper import TranscriptRequest, WhisperClient
    sys.path.insert(0, str(Path(__file__).parent))
    from records import AFTER_PHRASES, AFTER_WORDS, BEFORE, words

    doc = json.loads(Path(records).read_text())
    takes = [t for t in doc["takes"] if t["slot"] == slot]
    shortlist = json.loads((job / "plan.json").read_text())["slots"][slot]["shortlist"]
    role, about = ROLES[slot]
    build = build or f"reel-{slot}"
    reel = job / build
    reel.mkdir()  # create-only: a second build of the same slot is refused
    for sub in ("takes", "cards", "reel"):
        (reel / sub).mkdir()
    out = reel / "reel"

    # Timeline: intro label, then per candidate its label and its passed lines.
    t = LEAD
    placed, cards, speech_lines, notes = [], [], [], []
    intro = next(x for x in takes if x["candidate"] == 0)

    def place(take, at):
        link = reel / take["file"]
        link.hardlink_to(job / take["file"])
        assert sha(link) == take["sha256"] and take["status"] == "passed"
        placed.append({"take": take["id"], "kind": take["kind"], "voice": take["voice"], "text": take["text"],
                       "file": take["file"], "sha256": take["sha256"], "start_s": round(at, 3),
                       "end_s": round(at + take["duration_s"], 3)})
        speech_lines.append({"shot": take["candidate"], "k": len([p for p in placed
                                                                  if p["take"][:3] == take["id"][:3]]) - 1,
                             "doll": slot, "take_id": take["id"], "kind": take["kind"], "voice": take["voice"],
                             "text": take["text"], "file": take["file"], "duration_s": take["duration_s"],
                             "sha256": take["sha256"], "heard": take["checks"]["heard"],
                             "heard_matches": take["checks"]["exact_match"],
                             "match_with_tolerances": take["checks"]["match_with_tolerances"],
                             "tolerances_used": take["checks"]["tolerances_used"]})
        return at + take["duration_s"]

    cards.append({"start_s": 0.0, "candidate": 0, "file": "cards/00-intro.png"})
    t = place(intro, t) + GAP_CANDIDATE
    for n, voice in enumerate(shortlist, 1):
        label = next(x for x in takes if x["candidate"] == n and x["kind"] == "label")
        lines = [x for x in takes if x["candidate"] == n and x["kind"] == "line"]
        ok = [x for x in lines if x["status"] == "passed"]
        bad = [x for x in lines if x["status"] != "passed"]
        start = t - 0.4
        cards.append({"start_s": round(start, 3), "candidate": n, "voice": voice,
                      "file": f"cards/{n:02d}-{voice}.png", "played": [x["id"] for x in ok],
                      "not_played": [{"take": x["id"], "reason": x["reason"]} for x in bad]})
        if ok:
            t = place(label, t) + GAP_AFTER_LABEL
            for i, x in enumerate(ok):
                t = place(x, t) + (GAP_LINE if i < len(ok) - 1 else GAP_CANDIDATE)
        else:
            notes.append(f"candidate {n} ({voice}): no line passed its checks, so the card shows silently "
                         f"for {SILENT_CARD} s and its label is not played")
            t = start + 0.4 + SILENT_CARD
    total = round(t - GAP_CANDIDATE + TAIL, 3)
    for i, c in enumerate(cards):
        c["end_s"] = cards[i + 1]["start_s"] if i + 1 < len(cards) else total

    # Cards.
    current = shortlist[0]
    head = ["THE WINTER MENU  ·  VOICE AUDITION 1", f"Doll {slot.upper()}  ·  {role}"]
    roster = [f"{n}  {v}" + ("  (current r4 voice)" if n == 1 else "") for n, v in enumerate(shortlist, 1)]
    card(reel / cards[0]["file"], ["THE WINTER MENU  ·  VOICE AUDITION 1"],
         [(64, f"Doll {slot.upper()}"), (44, role)],
         [about, "Kokoro-82M v1.0 stock voices, all at", "speed 1.0 (the server's only setting)"],
         roster, [f"Reply:  {slot.upper()}: <voice id>"])
    by_id = {x["id"]: x for x in takes}
    for c in cards[1:]:
        v = c["voice"]
        g = doc["voices"][v]
        body = [f"“{by_id[i]['text']}”" for i in c["played"]]
        body += [f"Not played: “{by_id[x['take']]['text']}” ({x['reason']})" for x in c["not_played"]]
        card(reel / c["file"], head, [(96, f"{c['candidate']}"), (58, v)],
             [f"{v.split('_')[1].capitalize()}  ·  {ACCENT_NAME[v[0]]}  ·  female",
              f"Kokoro grade {g['kokoro_overall_grade'] if len(g['kokoro_overall_grade']) <= 2 else 'A (flagship)'}"
              f"  ·  speed 1.0" + ("  ·  CURRENT" if v == current and c["candidate"] == 1 else "")],
             body, [f"Reply:  {slot.upper()}: {v}"])

    # Audio, as poc/edit.py mixes a film.
    RATE = 48000
    mix = np.zeros((round(total * RATE) + RATE // 10, 2), np.float32)
    for p in placed:
        a = read_audio(reel / p["file"])
        a *= 10 ** (-22 / 20) / max(float(np.sqrt(np.mean(a * a))), 1e-8)
        edge = 240
        a[:edge] *= np.linspace(0, 1, edge)[:, None]
        a[-edge:] *= np.linspace(1, 0, edge)[:, None]
        n = round(p["start_s"] * RATE)
        mix[n:n + len(a)] += a
    mix = mix[:round(total * RATE)]
    write_audio(out / "dialogue-only.wav", np.clip(mix, -0.99, 0.99))
    peak = float(np.max(np.abs(mix)))
    headroom_db = 0.0
    if peak > 0.5:
        mix *= 0.5 / peak
        headroom_db = 20 * math.log10(0.5 / peak)
    write_audio(out / "premaster.wav", mix)
    first = levels(out / "premaster.wav")
    gain = LUFS - float(first["input_i"])
    limit = 10 ** ((TP - 1) / 20)
    ffmpeg(["-i", str(out / "premaster.wav"), "-af",
            f"volume={gain}dB,alimiter=limit={limit:.4f}:attack=2:release=60:level=0", "-ar", "48000",
            "-c:a", "pcm_s24le", str(out / "soundtrack.wav")])
    (out / "premaster.wav").unlink()  # an intermediate of this build only

    # Picture: exactly round(total * FPS) frames piped to x264 (as poc/edit.py renders),
    # frame i showing the card whose interval holds i / FPS; then mux.
    import subprocess
    from studio import ffmpeg_exe
    nframes_want = round(total * FPS)
    pixels = {c["file"]: np.asarray(Image.open(reel / c["file"]).convert("RGB")).tobytes() for c in cards}
    enc = subprocess.Popen([ffmpeg_exe(), "-hide_banner", "-nostdin", "-n", "-threads", "2", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an",
                            "-c:v", "libx264", "-threads", "2", "-preset", "fast", "-tune", "stillimage",
                            "-crf", "18", "-pix_fmt", "yuv420p", str(out / "picture.mp4")],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for i in range(nframes_want):
        at = i / FPS
        enc.stdin.write(pixels[[c for c in cards if c["start_s"] <= at][-1]["file"]])
    enc.stdin.close()
    err = enc.stderr.read()
    if enc.wait() != 0:
        raise RuntimeError(err.decode()[-600:])
    ffmpeg(["-i", str(out / "picture.mp4"), "-i", str(out / "soundtrack.wav"), "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out / "final.mp4")])
    (out / "picture.mp4").unlink()

    # Contact sheet of the cards.
    thumbs = [Image.open(reel / c["file"]).resize((240, 427)) for c in cards]
    sheet = Image.new("RGB", (240 * 4, 427 * math.ceil(len(thumbs) / 4)), BG)
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % 4) * 240, (i // 4) * 427))
    with (out / "contact-sheet.jpg").open("xb") as f:
        sheet.save(f, "JPEG", quality=85)

    # Records the delivery route expects.
    frames = [{"card": c["file"], "first_frame": round(c["start_s"] * FPS), "last_frame": round(c["end_s"] * FPS) - 1}
              for c in cards]
    for name, body in (("timeline.json", {"total_s": total, "audio": placed, "cards": cards,
                                          "premaster_headroom_db": headroom_db, "master_gain_db": gain,
                                          "notes": notes}),
                       ("shots.json", {"shots": cards}),
                       ("frame-transforms.json", {"fps": FPS, "note": "still title cards, no transforms",
                                                  "cards": frames})):
        with (out / name).open("x") as f:
            json.dump(body, f, indent=2)
    with (reel / "speech.json").open("x") as f:
        json.dump({"service": "ai/deploy/kokoro (Kokoro-82M v1.0, Wyoming), via haynes_studio.adapters.KokoroClient",
                   "lines": speech_lines}, f, indent=2)

    # Validation.
    import av
    c = av.open(str(out / "final.mp4"))
    vs, au = c.streams.video[0], c.streams.audio[0]
    vs.thread_count = 2
    mids = {round((cd["start_s"] + cd["end_s"]) / 2 * FPS): cd["file"] for cd in cards}
    refs = {f: np.asarray(Image.open(reel / f).convert("RGB"), dtype=np.int16) for f in pixels}
    placement = {}
    nframes = 0
    for fr in c.decode(vs):
        if nframes in mids:
            got = fr.to_ndarray(format="rgb24").astype(np.int16)
            diffs = {f: float(np.mean(np.abs(got - ref))) for f, ref in refs.items()}
            placement[mids[nframes]] = {"frame": nframes, "closest": min(diffs, key=diffs.get),
                                        "mean_abs_diff": round(diffs[mids[nframes]], 2)}
        nframes += 1
    vinfo = {"codec": vs.codec_context.name, "width": vs.codec_context.width, "height": vs.codec_context.height,
             "pix_fmt": vs.codec_context.format.name, "frames": nframes, "audio_codec": au.codec_context.name,
             "audio_rate": au.codec_context.sample_rate, "audio_channels": au.codec_context.layout.nb_channels,
             "duration_s": round(float(c.duration) / 1e6, 3)}
    c.close()
    final_levels = levels(out / "final.mp4")
    sound = read_audio(out / "soundtrack.wav")
    checks = {
        "h264_720x1280_yuv420p": (vinfo["codec"], vinfo["width"], vinfo["height"], vinfo["pix_fmt"])
        == ("h264", W, H, "yuv420p"),
        "aac_48k_stereo": (vinfo["audio_codec"], vinfo["audio_rate"], vinfo["audio_channels"]) == ("aac", 48000, 2),
        "frames_match_timeline": nframes == round(total * FPS),
        "each_card_in_its_interval": len(placement) == len(cards)
        and all(v["closest"] == f and v["mean_abs_diff"] < 3 for f, v in placement.items()),
        "duration_matches_timeline": abs(vinfo["duration_s"] - total) <= 0.1,
        "loudness_within_1_5_lu": abs(float(final_levels["input_i"]) - LUFS) <= 1.5,
        "true_peak_at_most_-2_5_dbtp": float(final_levels["input_tp"]) <= -2.5,
        "no_clipping": float(np.max(np.abs(sound))) < 0.999,
        "every_take_passed_and_hash_matches": all(sha(reel / p["file"]) == p["sha256"] for p in placed)
        and all(by_id[p["take"]]["status"] == "passed" for p in placed),
    }

    # Whole-reel transcript (one request), as stage 6 checks a film.
    log = job / "reel-asr.jsonl"
    used = sum(json.loads(x)["requests"]["asr"] for x in (job / "takes.jsonl").read_text().splitlines())
    used += len(log.read_text().splitlines()) if log.exists() else 0
    if used >= 150:
        raise SystemExit("transcript cap reached")
    ffmpeg(["-i", str(out / "soundtrack.wav"), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out / "dialogue-check.wav")])
    wav16 = (out / "dialogue-check.wav").read_bytes()
    t0 = datetime.now(timezone.utc)
    from haynes_studio.adapters.errors import AdapterError
    try:
        heard = WhisperClient(SubprocessRunner()).transcribe(TranscriptRequest(wav16)).text
    except AdapterError as e:
        heard = f"<no transcript: {e.code}>"
    with log.open("a") as f:
        f.write(json.dumps({"slot": slot, "at": t0.isoformat(timespec="seconds"), "requests": {"tts": 0, "asr": 1},
                            "heard": heard}) + "\n")
    (out / "dialogue-check.wav").unlink()
    import difflib
    expected = " ".join(p["text"] for p in placed)
    # Expected words, each flagged when it is a voice name or "doll" inside a label:
    # proper names the recognizer cannot know (Isabella, Kore, Aoede were heard four ways).
    exp, is_name = [], []
    names = {v.split("_", 1)[1] for v in shortlist}
    for p in placed:
        for w in words(p["text"]):
            exp.append(w)
            is_name.append(p["kind"] == "label" and (w in names or w == "doll"))
    tol = {k: v.split() for k, v in BEFORE.items()}  # digits and the r4 manifest's two
    got = [x for w in words(heard) for x in tol.get(w, [w])]
    for p in AFTER_PHRASES:
        if p["applies_to"] != "line":
            continue
        wrong, right = words(p["heard"]), words(p["means"])
        for i in range(len(got) - len(wrong) + 1):
            if got[i:i + len(wrong)] == wrong:
                got = got[:i] + right + got[i + len(wrong):]
    ops = difflib.SequenceMatcher(a=exp, b=got, autojunk=False).get_opcodes()
    differences, outside = [], []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        item = {"expected": " ".join(exp[i1:i2]), "heard": " ".join(got[j1:j2])}
        if op == "replace" and all(is_name[i1:i2]):
            differences.append(item)
        else:
            outside.append(item)
    reel_match = not outside
    per_take = all(by_id[p["take"]]["checks"]["match_with_tolerances"] for p in placed)
    transcript = {"method": "each take transcribed on its own before assembly (take records), and the whole "
                            "reel's soundtrack at 16 kHz mono in one request",
                  "rule": "the whole-reel transcript must equal the script word for word after the digits and the "
                          "r4 manifest's tolerances, except that a voice name or 'doll' inside a label may be heard "
                          "as other words (word-level alignment, difflib)",
                  "expected": expected, "heard": heard, "exact_match": words(heard) == words(expected),
                  "name_positions_heard_differently": differences, "differences_outside_names": outside,
                  "reel_match_with_tolerances": reel_match, "every_take_matched": per_take,
                  "match_with_tolerances": reel_match and per_take,
                  "tolerances": {"before_run": BEFORE, "after_run_words": AFTER_WORDS,
                                 "after_run_phrases": AFTER_PHRASES},
                  "recognizer": "ai/deploy/whisper (Wyoming ASR), via haynes_studio.adapters.WhisperClient"}
    with (out / "dialogue-transcript.json").open("x") as f:
        json.dump(transcript, f, indent=2)
    final_sha = sha(out / "final.mp4")
    validation = {"passed": all(checks.values()), "checks": checks, "video": vinfo, "card_placement": placement,
                  "levels": {k: final_levels[k] for k in ("input_i", "input_tp", "input_lra")},
                  "sha256": final_sha, "bytes": (out / "final.mp4").stat().st_size, "total_s": total}
    with (out / "validation.json").open("x") as f:
        json.dump(validation, f, indent=2)

    # The manifest poc/deliver.py reads for this reel.
    manifest = {
        "title": f"The Winter Menu voice audition 1, doll {slot.upper()} ({role})",
        "story": "https://work.haynesnetwork.com/work_packages/840",
        "job": f"the-winter-menu-voices-1-{slot}",
        "job_dir": f"~/studio-jobs/{job.name}/{build}",
        "revision_note": "Voice audition reel: a spoken label, then each candidate's r4 lines; still title cards.",
        "cast": {**{str(n): {"name": f"candidate {n}", "voice": v} for n, v in enumerate(shortlist, 1)},
                 "label": {"name": "announcer (labels only)", "voice": doc["label_voice"]}},
        "shots": [{"id": c["candidate"], "dolls": {"card": c["file"]}} for c in cards],
        "set": {"image": cards[0]["file"]},
        "sfx": {},
        "provenance": {"images": "Title cards drawn with Pillow (text only), no generated images.",
                       "motion": "None: one still card per candidate.",
                       "takes": "titles/the-winter-menu/voice-audition/takes.json"},
    }
    with open(manifest_out, "x") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(json.dumps({"slot": slot, "total_s": total, "passed": validation["passed"], "checks": checks,
                      "levels": validation["levels"], "reel_transcript_match": reel_match, "heard": heard,
                      "notes": notes, "sha256": final_sha}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
