import asyncio,io,json,sys,wave
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
