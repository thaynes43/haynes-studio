# E0: layered speech-to-video (2026-11-04)

Tom asked for the full Winter Menu remade with speech-to-video. Delivered privately (ledger
`e6659b3f1c4242eb85485f3cc82c557a`); review copy sent to Tom.

**Tom's verdict (2026-11-04):** "Absolutely worth it the quality is much better I didn't notice
any of the flaws we had before." Layered speech-to-video becomes the default for doll
talking shots (D24 in proposal 0003).

## Method

- **Model:** Wan2.2 S2V-14B fp8 with wav2vec2. **Fast path:** the 4-step lightning LoRA
  (`wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise`) at cfg 1 on one 3090, as in ComfyUI's
  own S2V template (added in haynes-ops PR 4634).
- **Layered S2V:** one clip per (shot, speaking doll), on green, from her sleeves-fixed still.
  Each clip is driven by a voice track with the shot's length, her lines at their timeline
  positions and silence elsewhere. That gives 11 clips; every doll in the vote shot speaks. Dolls who
  are not speaking, and the shot-7 close-up, keep their layered clips. The editor's bounce,
  lunges, camera, decal and mix are unchanged. The compositor plays each S2V clip on the shot clock (16 fps), not
  ping-ponged, so the mouth stays on the words (`clipmap-s2v.json`, `shots` section).
- **Long clips:** the template's Extend chunks (77 frames, 4.8 s each), 1 to 3 per clip.

## Measurements (`clip-records-s2v.jsonl`)

- **Speed:** one chunk takes about 2.4 to 4 min on one GPU, against about 12 min per 3.3 s
  with the 20-step path on both GPUs. That is **about 5x faster**, with lip-sync intact.
  1 chunk: 143 to 203 s; 2 chunks: 463 to 467 s; 3 chunks: 714 to 716 s (one ran 270 s,
  reusing ComfyUI's cached nodes from its interrupted first attempt).
- **Batch:** 22 chunks, about 92 min of render and cooldown time in the records, and about 105 min from first start to last finish, including the lost attempt.
- **Decal tracking is better than the 5B clips:** 9 of 11 at min ECC 0.88 or more (S2V
  moves the torso less). s1-a (0.71) and s9-b (0.80) failed the gate. By eye the lettering
  stays on the jacket in both, so they were overridden with a recorded reason (the same
  proxy weakness as the layered v2).
- **Compositing on the render worker:** 393 s.

## Failure found: the API's poll timeout

The first 3-chunk job lost its prompt after 552 s. One `/history` read exceeded the API's
20 s HTTP timeout while ComfyUI was busy, and `generate()` interrupted its own prompt.
Fixed in the client (`poc/wan.py` retries read polls) and in the API (haynes-ops PR 4635,
merged: retries within a 90 s window). **Requirement (E3):** the scheduler treats a slow
engine read as a miss, never as a failed job.

## Cost picture for the backlog

| Version | Wan clips | GPU wall | Compositing |
|---|---|---|---|
| Layered (5B) | 8 | about 37 min | 7 min (worker) |
| Layered S2V (lightning) | 8 layered + 11 S2V | about 37 min + about 92 min | 6.5 min (worker) |
| S2V 20-step (estimate) | the same | about 37 min + about 7 h | the same |
