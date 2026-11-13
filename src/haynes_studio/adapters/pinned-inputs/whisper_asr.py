import asyncio,io,json,sys,wave
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
