"""Write the audition plan (story 840): every take to synthesize, in order.

    python plan.py <job_dir> <r4 manifest>

Create-only: refuses if <job_dir>/plan.json exists. Lines come from the r4 manifest
verbatim; labels are announcements in one voice that is in no shortlist.
"""
import json
import sys
from pathlib import Path

LABEL_VOICE = "am_michael"  # US male, Kokoro grade C+; no doll is male, so it never sounds like a candidate
NUMBERS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]

# Slot: (role in the brief, r4 lines as (shot, k), shortlist with the current r4 voice first)
SLOTS = {
    "a": ("the captain", [(1, 0), (4, 0)],
          ["bf_emma", "bf_isabella", "bf_lily", "bf_alice", "af_kore", "af_aoede"]),
    "b": ("the chair", [(2, 0), (8, 4), (9, 0)],
          ["af_heart", "af_nova", "af_alloy", "af_sarah", "af_river", "af_kore"]),
    "c": ("the grudge holder", [(3, 0), (6, 0)],
          ["af_nicole", "af_sarah", "af_jessica", "af_aoede", "af_alloy", "af_river"]),
    "d": ("the cheerful one", [(5, 0), (8, 3)],
          ["af_bella", "af_sky", "af_jessica", "af_kore", "bf_lily", "af_heart"]),
}


def r4_lines(manifest):
    out = {}
    for shot in manifest["shots"]:
        lines = shot.get("lines") or ([shot["line"]] if shot.get("line") else [])
        for k, line in enumerate(lines):
            out[(shot["id"], k)] = line
    return out


def spoken_name(voice):
    return voice.split("_", 1)[1].capitalize()


def main(job, manifest_path):
    job = Path(job)
    m = json.loads(Path(manifest_path).read_text())
    lines = r4_lines(m)
    takes = []
    for slot, (role, refs, shortlist) in SLOTS.items():
        takes.append({"id": f"{slot}00-intro", "slot": slot, "candidate": 0, "kind": "label",
                      "voice": LABEL_VOICE, "text": f"Doll {slot.upper()}, {role}."})
        for n, voice in enumerate(shortlist, 1):
            current = " the current voice." if n == 1 else "."
            takes.append({"id": f"{slot}{n:02d}-label", "slot": slot, "candidate": n, "kind": "label",
                          "voice": LABEL_VOICE,
                          "text": f"{NUMBERS[n].capitalize()}. {spoken_name(voice)},{current}"
                          if n == 1 else f"{NUMBERS[n].capitalize()}. {spoken_name(voice)}."})
            for shot, k in refs:
                line = lines[(shot, k)]
                assert line["doll"] == slot, (slot, shot, k)
                takes.append({"id": f"{slot}{n:02d}-{voice}-s{shot}" + (f"-{k}" if k else ""), "slot": slot,
                              "candidate": n, "kind": "line", "voice": voice, "text": line["text"],
                              "r4_line": {"shot": shot, "k": k}, "current_voice": n == 1})
    plan = {"story": "https://work.haynesnetwork.com/work_packages/840",
            "source_manifest": "titles/the-winter-menu/manifest-r4.json",
            "label_voice": LABEL_VOICE, "slots": {s: {"role": r, "shortlist": sl, "lines": [list(x) for x in refs]}
                                                  for s, (r, refs, sl) in SLOTS.items()},
            "takes": takes}
    with (job / "plan.json").open("x") as f:
        json.dump(plan, f, indent=2)
    print(len(takes), "takes;", sum(t["kind"] == "line" for t in takes), "lines,",
          sum(t["kind"] == "label" for t in takes), "labels")


if __name__ == "__main__":
    main(*sys.argv[1:])
