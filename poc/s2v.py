"""Wan 2.2 speech-to-video for one talking shot (E0.4): keyframe + the line's voice WAV in,
a clip whose motion follows the speech out. Same sanctioned path as poc/wan.py (the Wan
API's own generate() under the compute lease, cool-idle gate, ledger).

Settings follow ComfyUI's own video_wan2_2_14B_s2v template in the Wan pod: 20 steps,
cfg 6, uni_pc/simple, shift 8, 16 fps, plus our two-GPU CFG split (MultiGPU_WorkUnits):
on one 3090 a 53-frame 576x1024 job ran 61 s/step and missed the API's 20-minute limit.
--lightning is the template's fast path (its 4-step LoRA at cfg 1, one GPU). Length is sized
to the audio (4k+1 frames); beyond one 77-frame chunk the template's Extend chunks follow.

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


CHUNK = 77  # frames per S2V chunk, as in ComfyUI's template; longer clips chain Extend chunks
LORA = 'wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors'


def graph(prompt, negative, image, audio, width, height, length, seed, prefix, lightning=False):
    """`length` frames: one WanSoundImageToVideo chunk, plus Extend chunks when longer than
    CHUNK (the template's structure). `lightning` uses the template's fast path: the 4-step
    LoRA at cfg 1 on one GPU; otherwise 20 steps at cfg 6 with the CFG split over both GPUs."""
    chunks = max(1, math.ceil(length / CHUNK)); first = min(length, CHUNK)
    steps, cfg = (4, 1.0) if lightning else (20, 6.0)
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'wan2.2_s2v_14B_fp8_scaled.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': negative}},
        '7': {'class_type': 'AudioEncoderLoader', 'inputs': {'audio_encoder_name': 'wav2vec2_large_english_fp16.safetensors'}},
        '8': {'class_type': 'LoadAudio', 'inputs': {'audio': audio}},
        '9': {'class_type': 'AudioEncoderEncode', 'inputs': {'audio_encoder': ['7', 0], 'audio': ['8', 0]}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        '11': {'class_type': 'WanSoundImageToVideo', 'inputs': {'positive': ['4', 0], 'negative': ['5', 0], 'vae': ['3', 0],
               'width': width, 'height': height, 'length': first, 'batch_size': 1,
               'audio_encoder_output': ['9', 0], 'ref_image': ['10', 0]}},
    }
    if lightning:
        g['17'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': LORA, 'strength_model': 1.0}}
        g['6'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['17', 0], 'shift': 8.0}}
        model = ['6', 0]
    else:
        g['6'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}}
        # Both 3090s: the CFG passes split across two model copies, as in the Wan workflow.json.
        g['16'] = {'class_type': 'MultiGPU_WorkUnits', 'inputs': {'model': ['6', 0], 'max_gpus': 2}}
        model = ['16', 0]
    sampler = {'steps': steps, 'cfg': cfg, 'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1.0}
    g['12'] = {'class_type': 'KSampler', 'inputs': {'model': model, 'positive': ['11', 0], 'negative': ['11', 1],
               'latent_image': ['11', 2], 'seed': seed, **sampler}}
    latent = ['12', 0]
    for k in range(1, chunks):
        n = 100 + 10 * k
        g[str(n)] = {'class_type': 'WanSoundImageToVideoExtend', 'inputs': {'positive': ['4', 0], 'negative': ['5', 0],
                     'vae': ['3', 0], 'length': CHUNK, 'video_latent': latent, 'audio_encoder_output': ['9', 0], 'ref_image': ['10', 0]}}
        g[str(n + 1)] = {'class_type': 'KSampler', 'inputs': {'model': model, 'positive': [str(n), 0], 'negative': [str(n), 1],
                         'latent_image': [str(n), 2], 'seed': seed + k, **sampler}}
        g[str(n + 2)] = {'class_type': 'LatentConcat', 'inputs': {'samples1': latent, 'samples2': [str(n + 1), 0], 'dim': 't'}}
        latent = [str(n + 2), 0]
    # The template's fix for an overbaked first frame: double the first latent frame, decode,
    # then drop the frames it produced.
    g['18'] = {'class_type': 'LatentCut', 'inputs': {'samples': latent, 'dim': 't', 'index': 0, 'amount': 1}}
    g['19'] = {'class_type': 'LatentConcat', 'inputs': {'samples1': ['18', 0], 'samples2': latent, 'dim': 't'}}
    g['13'] = {'class_type': 'VAEDecode', 'inputs': {'samples': ['19', 0], 'vae': ['3', 0]}}
    g['20'] = {'class_type': 'ImageFromBatch', 'inputs': {'image': ['13', 0], 'batch_index': 3, 'length': 4096}}
    g['14'] = {'class_type': 'CreateVideo', 'inputs': {'images': ['20', 0], 'fps': float(FPS), 'audio': ['8', 0]}}
    g['15'] = {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': prefix, 'format': 'mp4', 'codec': 'h264'}}
    return g


def main():
    import av
    ap = argparse.ArgumentParser()
    for n in ('--job', '--name', '--image', '--audio'):
        ap.add_argument(n, required=True)
    ap.add_argument('--prompt'); ap.add_argument('--prompt-file'); ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--width', type=int, default=576); ap.add_argument('--height', type=int, default=1024)
    ap.add_argument('--pad-s', type=float, default=0.4)
    ap.add_argument('--lightning', action='store_true', help='4-step LoRA at cfg 1 on one GPU (the template fast path)')
    a = ap.parse_args(); prompt = a.prompt or Path(a.prompt_file).read_text().strip()
    job_dir = Path(a.job); clips = job_dir / 'clips'; clip = clips / f'{a.name}.mp4'
    clips.mkdir(parents=True, exist_ok=True)  # before the long render, so its output always has a home
    if clip.exists():
        raise FileExistsError(clip)
    with wave.open(a.audio) as w:
        dur = w.getnframes() / w.getframerate()
    length = 4 * math.ceil((dur + a.pad_s) * FPS / 4) + 1
    if length > CHUNK:  # Extend chunks are whole CHUNKs
        length = CHUNK * math.ceil(length / CHUNK)
    t0 = time.time(); cooled_s, temps = wait_cool()
    image, image_sha = upload(a.image, '.png'); audio, audio_sha = upload(a.audio, '.wav')
    jid = uuid.uuid4().hex
    g = graph(prompt, NEGATIVE, image, audio, a.width, a.height, length, a.seed, 'video/' + jid, a.lightning)
    job = {'id': jid, 'state': 'queued', 'preset': f"studio-e0-s2v{'-lightning' if a.lightning else ''}-{a.width}x{a.height}-{length}f", 'seed': a.seed,
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
    peak = max(((g2.get('memory_mib') or 0) for t in result.get('telemetry', []) for g2 in t.get('gpus', [])), default=None)
    rec = {'name': a.name, 'job_id': jid, 'method': 's2v-lightning' if a.lightning else 's2v', 'chunks': max(1, math.ceil(length / CHUNK)), 'seed': a.seed, 'width': a.width, 'height': a.height, 'length': length,
           'fps': FPS, 'frames': n, 'audio_s': round(dur, 3), 'image_sha256': image_sha, 'audio_sha256': audio_sha,
           'clip_sha256': hashlib.sha256(body).hexdigest(), 'cooldown_s': cooled_s, 'start_temps': temps,
           'render_s': round(td - ts, 1), 'wall_s': round(time.time() - t0, 1), 'peak_gpu_mib': peak, 'prompt': prompt,
           'unexpected_work_seen': result.get('unexpected_work_seen'),
           'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with (clips / 'records.jsonl').open('a') as f:
        f.write(json.dumps(rec) + '\n')
    print(json.dumps({k: v for k, v in rec.items() if k != 'prompt'}))
    if result.get('unexpected_work_seen'):
        raise RuntimeError('Competing work observed; output kept, stopping further submissions')


if __name__ == '__main__':
    main()
