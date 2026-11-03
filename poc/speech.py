"""Synthesize every line in a title manifest with Kokoro (runbook stage 3).

    python3 poc/speech.py titles/<slug>/manifest.json

Writes <job>/voices/line-<shot>.wav and <job>/speech.json (voice, text, duration,
sha256), create-only. Each line is also transcribed on its own so a misread word
shows up now, not after the edit.
"""
import io, json, re, sys, wave
from studio import load_manifest, sha, synthesize, transcribe, lines_of


def norm(s):
    return re.sub('[^a-z0-9]', '', s.lower())


def main(path):
    m = load_manifest(path); out = m['_job'] / 'voices'
    out.mkdir(exist_ok=True)
    if (m['_job'] / 'speech.json').exists():
        raise FileExistsError('speech.json already exists; start a new revision to redo voices')
    lines = []
    for shot in m['shots']:
        for k, line in lines_of(shot):
            voice = m['cast'][line['doll']]['voice']
            data = synthesize(voice, line['text'])
            target = out / (f"line-{shot['id']}.wav" if k == 0 else f"line-{shot['id']}-{k}.wav")
            with target.open('xb') as f:
                f.write(data)
            with wave.open(io.BytesIO(data)) as w:
                duration = w.getnframes() / w.getframerate()
            heard = transcribe(target)
            rec = {'shot': shot['id'], 'k': k, 'doll': line['doll'], 'voice': voice, 'text': line['text'],
                   'file': f'voices/{target.name}', 'duration_s': round(duration, 3), 'sha256': sha(target),
                   'heard': heard, 'heard_matches': norm(heard) == norm(line['text'])}
            lines.append(rec)
            print(json.dumps(rec))
    with (m['_job'] / 'speech.json').open('x') as f:
        json.dump({'service': 'ai/deploy/kokoro (Kokoro-82M v1.0, Wyoming)', 'lines': lines}, f, indent=2)


if __name__ == '__main__':
    main(sys.argv[1])
