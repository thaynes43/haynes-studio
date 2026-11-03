"""Wan 2.2 speech-to-video for one talking shot (E0.4): keyframe + the line's voice WAV in,
a clip whose motion follows the speech out. Same sanctioned path as poc/wan.py (the Wan
API's own generate() under the compute lease, cool-idle gate, ledger).

Settings follow ComfyUI's own video_wan2_2_14B_s2v template in the Wan pod: 20 steps,
cfg 6, uni_pc/simple, shift 8, 16 fps, plus our two-GPU CFG split (MultiGPU_WorkUnits):
on one 3090 a 53-frame 576x1024 job ran 61 s/step and missed the API's 20-minute limit. Length is sized to the line (4k+1 frames).

    python poc/s2v.py --job DIR --name s2-s2v --image KEY.png --audio LINE.wav \
        --prompt-file p.txt --seed 1 [--width 576 --height 1024] [--pad-s 0.4]
"""
import argparse, hashlib, json, math, subprocess, time, uuid, wave
from pathlib import Path
from wan import REMOTE, UPLOAD, RUN, NEGATIVE, remote, wait_cool

FPS = 16


def upload(path, suffix):
    data = Path(path).read_bytes(); digest = hashlib.sha256(data).hexdigest(); name = f'{digest[:16]}{suffix}'
    r = subprocess.run(REMOTE + [UPLOAD, name, digest], input=data, capture_output=True, timeout=30)
    if r.returncode or r.stdout.decode().strip() != digest:
        raise RuntimeError('upload failed: ' + r.stderr.decode()[-500:])
    return 'studio-e0/' + name, digest


def graph(prompt, negative, image, audio, width, height, length, seed, prefix):
    return {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'wan2.2_s2v_14B_fp8_scaled.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': negative}},
        '6': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}},
        '7': {'class_type': 'AudioEncoderLoader', 'inputs': {'audio_encoder_name': 'wav2vec2_large_english_fp16.safetensors'}},
        '8': {'class_type': 'LoadAudio', 'inputs': {'audio': audio}},
        '9': {'class_type': 'AudioEncoderEncode', 'inputs': {'audio_encoder': ['7', 0], 'audio': ['8', 0]}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        '11': {'class_type': 'WanSoundImageToVideo', 'inputs': {'positive': ['4', 0], 'negative': ['5', 0], 'vae': ['3', 0],
               'width': width, 'height': height, 'length': length, 'batch_size': 1,
               'audio_encoder_output': ['9', 0], 'ref_image': ['10', 0]}},
        # Both 3090s: the CFG passes split across two model copies, as in the Wan workflow.json.
        '16': {'class_type': 'MultiGPU_WorkUnits', 'inputs': {'model': ['6', 0], 'max_gpus': 2}},
        '12': {'class_type': 'KSampler', 'inputs': {'model': ['16', 0], 'positive': ['11', 0], 'negative': ['11', 1],
               'latent_image': ['11', 2], 'seed': seed, 'steps': 20, 'cfg': 6.0, 'sampler_name': 'uni_pc',
               'scheduler': 'simple', 'denoise': 1.0}},
        '13': {'class_type': 'VAEDecode', 'inputs': {'samples': ['12', 0], 'vae': ['3', 0]}},
        '14': {'class_type': 'CreateVideo', 'inputs': {'images': ['13', 0], 'fps': float(FPS), 'audio': ['8', 0]}},
        '15': {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': prefix, 'format': 'mp4', 'codec': 'h264'}},
    }


def main():
    import av
    ap = argparse.ArgumentParser()
    for n in ('--job', '--name', '--image', '--audio'):
        ap.add_argument(n, required=True)
    ap.add_argument('--prompt'); ap.add_argument('--prompt-file'); ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--width', type=int, default=576); ap.add_argument('--height', type=int, default=1024)
    ap.add_argument('--pad-s', type=float, default=0.4)
    a = ap.parse_args(); prompt = a.prompt or Path(a.prompt_file).read_text().strip()
    job_dir = Path(a.job); clips = job_dir / 'clips'; clip = clips / f'{a.name}.mp4'
    if clip.exists():
        raise FileExistsError(clip)
    with wave.open(a.audio) as w:
        dur = w.getnframes() / w.getframerate()
    length = 4 * math.ceil((dur + a.pad_s) * FPS / 4) + 1
    t0 = time.time(); cooled_s, temps = wait_cool()
    image, image_sha = upload(a.image, '.png'); audio, audio_sha = upload(a.audio, '.wav')
    jid = uuid.uuid4().hex
    g = graph(prompt, NEGATIVE, image, audio, a.width, a.height, length, a.seed, 'video/' + jid)
    job = {'id': jid, 'state': 'queued', 'preset': f'studio-e0-s2v-{a.width}x{a.height}-{length}f', 'seed': a.seed,
           'created_at': time.time(), 'telemetry': [], 'kind': 'reference_conditioned_render', 'reference_image': image,
           'reference_sha256': image_sha, 'audio': audio, 'audio_sha256': audio_sha,
           'story': 'https://work.haynesnetwork.com/work_packages/394'}
    ts = time.time()
    result = json.loads(remote(RUN, {'job': job, 'graph': g, 'prompt': prompt}, timeout=1500))
    td = time.time()
    if result['state'] != 'succeeded':
        raise RuntimeError(f"S2V job {jid} ended {result['state']}: {json.dumps(result)[-800:]}")
    fetch = 'import urllib.request,sys;sys.stdout.buffer.write(urllib.request.urlopen("http://127.0.0.1:8080/videos/' + jid + '/file",timeout=60).read())'
    body = remote(fetch, timeout=90)
    with clip.open('xb') as f:
        f.write(body)
    c = av.open(str(clip)); s = c.streams.video[0]; s.thread_count = 2; n = 0
    for fr in c.decode(s):
        if n == 0:
            fr.to_image().save(clips / f'{a.name}-first.png')
        last = fr; n += 1
    last.to_image().save(clips / f'{a.name}-last.png'); c.close()
    peak = max((g2.get('memory_mib') or 0) for t in result.get('telemetry', []) for g2 in t.get('gpus', []))
    rec = {'name': a.name, 'job_id': jid, 'method': 's2v', 'seed': a.seed, 'width': a.width, 'height': a.height, 'length': length,
           'fps': FPS, 'frames': n, 'audio_s': round(dur, 3), 'image_sha256': image_sha, 'audio_sha256': audio_sha,
           'clip_sha256': hashlib.sha256(body).hexdigest(), 'cooldown_s': cooled_s, 'start_temps': temps,
           'render_s': round(td - ts, 1), 'wall_s': round(time.time() - t0, 1), 'peak_gpu_mib': peak, 'prompt': prompt,
           'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with (clips / 'records.jsonl').open('a') as f:
        f.write(json.dumps(rec) + '\n')
    print(json.dumps({k: v for k, v in rec.items() if k != 'prompt'}))


if __name__ == '__main__':
    main()
