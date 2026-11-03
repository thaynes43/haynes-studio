"""Shared helpers for the PoC media scripts (runbook stages 3 to 7).

Lifted from the OP345 scripts in haynes-ops scripts/wan-video/ (edit_short.py,
edit_butter.py, butter_speech.py, check_butter_dialogue.py) so the manifest-driven
scripts here do not depend on that production's hard-coded paths.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')  # CPU rule in AGENTS.md; set before numpy loads
import hashlib, json, subprocess, wave
from pathlib import Path

RATE = 48000


def load_manifest(path):
    """Read a title manifest and resolve its job directory."""
    m = json.loads(Path(path).read_text())
    m['_job'] = Path(os.path.expanduser(m['job_dir']))
    m['_path'] = Path(path)
    return m


def lines_of(shot):
    """A shot's lines as [(k, line)]: one `line`, or several `lines` spoken in order.
    The first line has `start` (seconds into the shot); later ones have `gap` (seconds
    after the previous line ends)."""
    if shot.get('lines'):
        return list(enumerate(shot['lines']))
    return [(0, shot['line'])] if shot.get('line') else []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ffmpeg(args):
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-n',
                        '-threads', '2', '-filter_threads', '2', '-filter_complex_threads', '2'] + args,
                       capture_output=True, text=True, check=True)
    return r.stderr


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def read_audio(path):
    """Any audio file to float32 stereo at 48 kHz, shape (samples, 2)."""
    import av, numpy as np
    c = av.open(str(path)); s = c.streams.audio[0]; s.thread_count = 2
    resampler = av.AudioResampler(format='fltp', layout='stereo', rate=RATE)
    chunks = []
    for frame in c.decode(s):
        chunks.extend(f.to_ndarray() for f in resampler.resample(frame))
    chunks.extend(f.to_ndarray() for f in resampler.resample(None)); c.close()
    return np.concatenate(chunks, axis=1).T


def write_audio(path, a):
    import numpy as np
    assert np.isfinite(a).all() and np.max(np.abs(a)) < 1
    with open(path, 'xb') as f, wave.open(f, 'wb') as w:  # create-only
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((a * 32767).astype('<i2').tobytes())


def levels(path):
    log = subprocess.run([ffmpeg_exe(), '-hide_banner', '-nostdin', '-threads', '2', '-i', str(path), '-vn',
                          '-af', 'loudnorm=I=-20:TP=-3:LRA=11:print_format=json', '-f', 'null', '-'],
                         capture_output=True, text=True, check=True).stderr
    return json.JSONDecoder().raw_decode(log[log.rfind('{'):])[0]


# Kokoro (Wyoming TTS, 127.0.0.1:10210 inside ai/deploy/kokoro). Reads {"voice","text"}
# on stdin, writes a WAV on stdout. From haynes-ops butter_speech.py.
TTS = '''import asyncio,io,json,sys,wave
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize,SynthesizeVoice
from wyoming.audio import AudioStart,AudioChunk,AudioStop
async def main():
 p=json.load(sys.stdin);chunks=[];fmt=None;total=0
 async with AsyncTcpClient('127.0.0.1',10210) as client:
  await client.write_event(Synthesize(text=p['text'],voice=SynthesizeVoice(name=p['voice'])).event())
  while True:
   event=await asyncio.wait_for(client.read_event(),30)
   if event is None: raise RuntimeError('TTS disconnected')
   if AudioStart.is_type(event.type): fmt=AudioStart.from_event(event)
   elif AudioChunk.is_type(event.type):
    part=AudioChunk.from_event(event);total+=len(part.audio)
    if total>2000000: raise RuntimeError('Unexpectedly long speech')
    chunks.append(part.audio)
   elif AudioStop.is_type(event.type): break
   elif event.type=='error': raise RuntimeError('TTS error')
 if fmt is None or not chunks: raise RuntimeError('No speech returned')
 buf=io.BytesIO()
 with wave.open(buf,'wb') as w:
  w.setnchannels(fmt.channels);w.setsampwidth(fmt.width);w.setframerate(fmt.rate);w.writeframes(b''.join(chunks))
 sys.stdout.buffer.write(buf.getvalue())
asyncio.run(asyncio.wait_for(main(),45))
'''

# Whisper pod's Wyoming ASR (127.0.0.1:10300 inside ai/deploy/whisper). Reads a WAV on
# stdin, prints {"transcript"}. From haynes-ops check_butter_dialogue.py.
ASR = '''import asyncio,io,json,sys,wave
from wyoming.client import AsyncTcpClient
from wyoming.asr import Transcribe,Transcript
from wyoming.audio import AudioStart,AudioChunk,AudioStop
async def run():
 w=wave.open(io.BytesIO(sys.stdin.buffer.read()),'rb');rate=w.getframerate();width=w.getsampwidth();channels=w.getnchannels()
 async with AsyncTcpClient('127.0.0.1',10300) as c:
  await c.write_event(Transcribe(language='en').event())
  await c.write_event(AudioStart(rate=rate,width=width,channels=channels).event())
  while True:
   b=w.readframes(8000)
   if not b:break
   await c.write_event(AudioChunk(rate=rate,width=width,channels=channels,audio=b).event())
  await c.write_event(AudioStop().event())
  while True:
   e=await asyncio.wait_for(c.read_event(),30)
   if e is None:raise RuntimeError('STT disconnected')
   if Transcript.is_type(e.type):print(json.dumps({'transcript':Transcript.from_event(e).text}));break
   if e.type=='error':raise RuntimeError('STT error')
asyncio.run(asyncio.wait_for(run(),45))
'''


def synthesize(voice, text):
    r = subprocess.run(['kubectl', 'exec', '-i', '-n', 'ai', 'deploy/kokoro', '-c', 'app', '--', 'python', '-c', TTS],
                       input=json.dumps({'voice': voice, 'text': text}).encode(), capture_output=True, check=True, timeout=55)
    return r.stdout


def transcribe(wav_path):
    with open(wav_path, 'rb') as f:
        r = subprocess.run(['kubectl', 'exec', '-i', '-n', 'ai', 'deploy/whisper', '-c', 'app', '--', 'python', '-c', ASR],
                           stdin=f, capture_output=True, check=True, timeout=55)
    return json.loads(r.stdout)['transcript']
