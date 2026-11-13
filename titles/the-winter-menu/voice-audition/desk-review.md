# Desk review: local TTS models with stock voices

Story [840](https://work.haynesnetwork.com/work_packages/840), part (e). This review lists local text-to-speech models that could replace or join Kokoro-82M v1.0 for the doll-short cast, using stock voices only (no cloning, no real person's voice). It ends with at most two models to try next and what a haynes-ops change for each would add. The Kokoro half of the audition is in [run-log.md](run-log.md).

2026-11-13, desk research only: nothing was deployed, downloaded or run. Researched by a subagent of the story 840 worker session (`haynes-studio-1113-190947`, Claude Code, `claude-opus-5-5`). The worker then re-read these primary pages for the two picks and the ranking, and they say what this page says: the Phonon 31m model card and voice catalogue, the `xn-ptts` README (server image, port, environment, no speed field), the Qwen3-TTS GitHub README (presets, VoiceDesign, the design-then-clone workflow), the vLLM-Omni speech API page (`instructions`, `speed`), and the Artificial Analysis open-weights leaderboard. Everything else is as the subagent read it. Figures are vendor claims unless a source says otherwise. "Not confirmed" means no primary source was found. Licence terms are recorded as facts for the [register](../../../docs/reference/model-licences.md), not as questions.

**Quality yardstick.** The Artificial Analysis TTS arena, filtered to open weights
(https://artificialanalysis.ai/text-to-speech/leaderboard?open_weights=true, read 2026-11-13; the page shows no as-of date),
gives Kokoro 82M v1.0 an Elo of **1061** (rank 66 of 105). Higher-ranked open models: Fish Audio Drama 3 1275, Breeze TTS 2 1229,
Ming-3.0-tts 1182, Phonon 31M (English) 1111, Fish Audio S2 Pro 1104, Step Audio EditX 1100, Voxtral TTS 1094. Lower-ranked open models: Maya1 1046, Higgs Audio V3 1038,
Chatterbox 1021, Zonos 1000, VibeVoice 1.5B 954, XTTS v2 914, StyleTTS 2 888. Orpheus, VoxCPM2, Pocket TTS, Kyutai TTS and Piper
are not in its open-weights list. The page lists a "Qwen3 TTS" at **928** (rank 94), below Kokoro, without an open-weights mark, so it may be the hosted model rather than the checkpoints below (not confirmed).

## Summary table (models that pass the stock-voice rule)

| Model | Size | Runs on | Stock voices (EN female) | Per-request controls | Licence code / weights | Commercial | Ready-made server |
|---|---|---|---|---|---|---|---|
| Phonon 31m EN (Gradium) | 31M (41.1M in metadata) | CPU | 37 EN (13: 6 US, 7 UK) | voice; rate via `duration_delta` (server field not confirmed) | MIT or Apache-2.0 / Apache-2.0 | allowed | HTTP OpenAI: `ghcr.io/gradium-ai/ptts-openai-server`; Wyoming: none |
| Qwen3-TTS 12Hz 1.7B CustomVoice + VoiceDesign | 1.7B (2B metadata) | GPU | 9 presets (0 native-EN female); VoiceDesign: any description | `instructions` (style, emotion), `speed`, language | Apache-2.0 / Apache-2.0 | allowed | HTTP OpenAI: `vllm/vllm-omni`; Wyoming: none |
| Orpheus 3B 0.1 ft (Canopy Labs) | 3B (Llama 3.2) | GPU (GGUF on llama.cpp) | 8 EN (5 by name) | inline tags; `speed` 0.5-1.5 via Orpheus-FastAPI | Apache-2.0 / Apache-2.0 tag, Llama 3.2 base | conditional | HTTP OpenAI: Orpheus-FastAPI (build from Dockerfile) |
| Voxtral 4B TTS 2603 (Mistral) | ~4B | GPU, 16-24 GB | 20 presets (3) | voice only | vLLM-Omni / CC BY-NC 4.0 | noncommercial | HTTP OpenAI: vLLM-Omni or SGLang-Omni |
| Breeze TTS 2 (BreezeBlue) | ~3B | GPU, 12 GB min | none; voice design by description | inline tags; speed fixed 1.0 in vLLM-Omni | Apache-2.0 / research and non-commercial | noncommercial | HTTP: own API; vLLM-Omni |
| Ming-3.0-tts 0.5B (inclusionAI) | 0.5B (1B metadata) | GPU (tested H800/H20) | ~5 EN (not confirmed; US_Emma named); voice design | emotion, speed, pitch, volume, free-form instruction | MIT / MIT | allowed | none (Dockerfile, CLI) |
| VoxCPM2 (OpenBMB) | 2B | GPU, ~8 GB | none; voice design by description | description text, cfg, timesteps, seed | Apache-2.0 / Apache-2.0 | allowed | HTTP OpenAI: vLLM-Omni |
| Maya1 (Maya Research) | 3.3B | GPU, 16 GB+ | none; voice design by description | description, 20 emotion tags | not stated / Apache-2.0 | allowed | none official |
| Kyutai TTS 1.6B en_fr | 1.8B | GPU | voice repo embeddings (not counted) | voice | MIT + Apache / CC-BY 4.0 (voices per folder) | conditional | websocket `moshi-server` |
| Pocket TTS (Kyutai) | 100M | CPU | 21 EN (~10 by name) | voice | MIT / CC-BY 4.0 | allowed | HTTP `pocket-tts serve`; community Wyoming and OpenAI wrappers |
| VibeVoice-Realtime 0.5B (Microsoft) | 0.5B | GPU (T4 real time) | 7 EN (2) | voice | MIT / MIT | allowed | websocket demo |
| Magpie TTS Multilingual 357M (NVIDIA) | 364M | NVIDIA GPU | 5 (not stated) | speaker index, cfg | NeMo / NVIDIA Open Model License | allowed | NeMo only |
| Kitten TTS 2 (Stellon Labs) | 1.7B | CPU or GPU | 47 or 115 (conflicting; not stated) | preset, expression tags (beta) | Apache-2.0 / Stellon Labs Community | conditional | HTTP OpenAI (Docker) |
| Kani-TTS-2 en (nineninesix) | 400M | GPU, 3 GB | 6 (not stated) | not documented | not stated / `lfm1.0` tag | unknown | HTTP OpenAI example server |
| Supertonic 3 (Supertone) | 99M | CPU | F/M styles (not counted) | inline tags | MIT / OpenRAIL-M | conditional | HTTP OpenAI `supertonic serve`; repo archived |
| Soprano 1.1 80M | 80M | CPU or GPU | not stated | temperature, top_p | Apache-2.0 | allowed | HTTP OpenAI (non-streaming) |
| Parler-TTS Mini v1 | 0.9B | GPU or CPU | 34 named (not counted) | description (rate, pitch) | Apache-2.0 | allowed | none official |
| XTTS-v2 (Coqui) | not stated | GPU | 58 studio speakers (not counted) | speaker, language | coqui-tts / CPML | noncommercial | none maintained (not confirmed) |
| MeloTTS (MyShell) | not stated | CPU | 5 EN accents (not stated) | speed (not confirmed) | MIT | allowed | none official |
| Piper (OHF-Voice) | small | CPU | many (not counted) | not confirmed | GPL-3.0 / per voice | conditional | Wyoming: `rhasspy/wyoming-piper` |
| Spark-TTS 0.5B | 0.5B | GPU | attribute-built voices | gender, pitch, rate | not checked / CC BY-NC-SA 4.0 | noncommercial | none official |

## Passing models

### Phonon 31m English (Gradium)
- **Needs:** CPU only. 64 MB of q8 weights. Vendor speed: 26x real time on one MacBook Air M5 core, 2.3x on one Raspberry Pi 5 core. No x86 server figures or RAM figure published.
- **Voices:** 37 built-in voices for the 31m English model (release post): the 25 English catalogue voices plus 12 character voices on the voices card. English female: US Zoey, Juniper, Everly, Harper, Hadley, Delia; UK Maeve, Freya, Pippa, Elodie-Rose, Imogen, Lottie, Bryony. The 12 character voices ("The Snow Queen", "Fairy Godmother", ...) were "made with Gradium Voice Design", without gender labels. The voices are `.safetensors` embeddings used "with no cloning". Where the catalogue voices come from is not stated. None is named after a real person. Cloning exists only through Gradium's cloud API and is not used here. No emotion or style control.
- **Licence:** weights, tokenizer and voices Apache-2.0. Runtime and server code MIT or Apache-2.0. The Phonon 40m models are gated and CC BY-NC 4.0.
- **Reached:** official image `ghcr.io/gradium-ai/ptts-openai-server:<version>` (CPU, amd64 and arm64), port 8880, `POST /v1/audio/speech`, `GET /v1/audio/voices`, env `PTTS_LANG`, `PTTS_QUANT`, `PTTS_MODEL`. No Wyoming server; the README lists a Home Assistant app that runs the OpenAI server image. A per-request speed field is not confirmed: the runtime sets the speaking rate with a `duration_delta` condition.
- **Evidence and maturity:** AA arena Elo 1111 against Kokoro's 1061 (independent). Gradium's own blind test: English Elo 2098 against Kokoro's 2043 (468 raters). Released 2026-10-20, so it is new.
- **Sources:** https://huggingface.co/gradium/phonon-31m-en/blob/92741c5b07d085ff840e26fea8ce43110b87852f/README.md ,
  https://huggingface.co/gradium/phonon-voices/blob/0ee17205f254b5abc43b266c8a0f215565c352f7/README.md ,
  https://github.com/gradium-ai/xn-ptts , https://gradium.ai/blog/release-phonon-open-weight

### Qwen3-TTS 12Hz 1.7B (Alibaba Qwen): CustomVoice and VoiceDesign
- **Needs:** GPU. 2B params in BF16 is roughly 4 GB of weights per checkpoint (an estimate, not a published VRAM figure). FlashAttention 2 is recommended. The vLLM-Omni scripts pass `--gpu-memory-utilization 0.9`, which must be lowered on a shared card. A 0.6B CustomVoice also exists; its instruction support is not confirmed.
- **Voices:** CustomVoice has 9 presets. Female: Vivian ("Bright, slightly edgy young female voice"), Serena, Ono_Anna and Sohee, all native in Chinese, Japanese or Korean. The two English natives, Ryan and Aiden, are male. The README says "each speaker can speak any language supported by the model" but recommends each speaker's native language. VoiceDesign builds a voice from a text description with no reference audio. Per-request `instructions` steer emotion and style on both models, for example "Speak in an incredulous tone, but with a hint of panic beginning to creep into your voice."
- **Stock-voice caveat:** a designed voice may change between calls. For "a consistent character voice across many lines", the README's workflow is to synthesise a clip with VoiceDesign and clone it with the Base model. That is cloning from a reference clip, so it is outside the rule as written. Use only CustomVoice and VoiceDesign, and never the Base model, `ref_audio` or `POST /v1/audio/voices` uploads.
- **Licence:** code Apache-2.0 (GitHub). Weights Apache-2.0 (metadata on both model cards).
- **Reached:** vLLM-Omni (`vllm/vllm-omni`; a v0.30.0 tag was seen in search, not confirmed live) serves one model per server, for example `vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --omni --port 8091`. It exposes the OpenAI-compatible `POST /v1/audio/speech` with `voice`, `task_type`, `instructions`, `language`, `speed` (0.25-4.0, not with streaming) and `response_format`, plus `GET /v1/audio/voices`. The Qwen README still says vLLM-Omni serves offline only; the vLLM-Omni docs (dated 2026-10-24) document online serving. No Wyoming server.
- **Evidence and maturity:** vendor InstructTTSEval-EN scores: VoiceDesign APS 82.9 / DSD 82.4 / RP 68.4; CustomVoice 77.3 / 77.1 / 63.7. Seed-TTS test-en WER 1.24 (Base model). No open-weights arena entry; the arena's "Qwen3 TTS" (928, below Kokoro's 1061) has no open-weights mark, and whether it is this checkpoint is not confirmed. Released 2026-01-22.
- **Sources:** https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/blob/0c0e3051f131929182e2c023b9537f8b1c68adfe/README.md ,
  https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/blob/5ecdb67327fd37bb2e042aab12ff7391903235d3/README.md ,
  https://github.com/QwenLM/Qwen3-TTS , https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/speech_api/ ,
  https://docs.vllm.ai/projects/vllm-omni/en/v0.18.0/user_guide/examples/online_serving/qwen3_tts/

### Orpheus 3B 0.1 ft (Canopy Labs)
- **Needs:** GPU. 3B Llama backbone (4B in metadata). Upstream inference uses vLLM, and one forum user reports about 20 GB with vLLM (secondary). Orpheus-FastAPI can instead use a llama.cpp or LM Studio backend with Q2_K, Q4_K_M or Q8_0 GGUF; VRAM for those is not published.
- **Voices:** 8 English presets "in order of conversational realism": tara, leah, jess, leo, dan, mia, zac, zoe. Five are female by name (tara, leah, jess, mia, zoe); the README does not state genders. All appear to be US English (not confirmed). Tags: `<laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>`. `repetition_penalty>=1.1` is "required for stable generations".
- **Licence:** code Apache-2.0. Weights tagged apache-2.0, with `base_model: meta-llama/Llama-3.2-3B-Instruct`, so the Llama 3.2 Community License applies to the base (its text was not fetched this session).
- **Reached:** Orpheus-FastAPI (Apache-2.0, v1.3.1, 2025-07-05) is an OpenAI-compatible `/v1/audio/speech` server with `voice`, per-request `speed` (0.5-1.5) and wav output. Temperature and top_p are server env settings. It ships Dockerfiles and compose files but no published image. No Wyoming server; the Wyoming-to-OpenAI bridge `ghcr.io/roryeckel/wyoming_openai` could front it.
- **Evidence and maturity:** no independent 2026 ranking found. The last upstream news is from 2025-05.
- **Sources:** https://huggingface.co/canopylabs/orpheus-3b-0.1-ft/blob/4206a56e5a68cf6cf96900a8a78acd3370c02eb6/README.md , https://github.com/canopyai/Orpheus-TTS , https://github.com/Lex-au/Orpheus-FastAPI

### Voxtral 4B TTS 2603 (Mistral)
- **Needs:** GPU with "at least 16 GB" (card). The vLLM recipe measured about a 20.5 GiB startup peak on one RTX 4090 and asks for 24 GB. It is a finetune of Ministral-3-3B.
- **Voices:** 20 preset embeddings. The English-labelled female ones are `casual_female`, `cheerful_female` and `neutral_female`. The other 17 are language-prefixed (fr, de, es, it, pt, nl, hi, ar). The voice references come from EARS, CML-TTS, IndicVoices-R and Arabic Natural Audio. There are no sampling controls: SGLang-Omni rejects temperature and seed because "decoding is deterministic". No speed field is documented. Reference cloning is not supported in SGLang-Omni.
- **Licence:** weights and voices CC BY-NC 4.0. The card says "These voices are licensed under CC BY-NC 4, which is the license that the model inherits."
- **Reached:** `vllm serve mistralai/Voxtral-4B-TTS-2603 --omni` or `sgl-omni serve ...`. Both give an OpenAI-compatible `/v1/audio/speech`. No Wyoming server.
- **Evidence and maturity:** AA Elo 1094. Released 2026-03-23. Mistral's docs mark the hosted model deprecated from 2026-10-31 in favour of Voxtral TTS 3 (whose open weights are not confirmed).
- **Sources:** https://huggingface.co/mistralai/Voxtral-4B-TTS-2603/tree/7ea59cdcd688efcb64f25eb969f5c620d28ec8b9/voice_embedding , https://recipes.vllm.ai/mistralai/Voxtral-4B-TTS-2603 , https://sgl-project.github.io/sglang-omni/cookbook/voxtral_tts.html , https://docs.mistral.ai/models/model-cards/voxtral-tts-26-03

### Breeze TTS 2 (BreezeBlue)
- **Needs:** GPU, about 3B params. Eager mode uses about 7.7 GiB (12 GB minimum); `--fast-all` uses about 14.4 GiB (24 GB recommended).
- **Voices:** no presets. Voice Design takes a text description with no reference audio. Voice Clone and Voice Direction use a reference clip and are outside the rule. Inline vocal events such as `(laugh)`, `(sigh)` and `(cough)`.
- **Licence:** code Apache-2.0. Weights "for research and non-commercial use only".
- **Reached:** its own single-concurrency streaming `/v1/audio/speech` (`python -m breeze_infer.api`; OpenAI compatibility is not claimed). Listed by vLLM-Omni, where `speed` must be 1.0.
- **Evidence and maturity:** AA Elo 1229, the second open-weights model on the list. Released 2026-08-25.
- **Source:** https://huggingface.co/BreezeBlue/Breeze-TTS-2

### Ming-3.0-tts (inclusionAI / Ant Group)
- **Needs:** GPU. 0.5B dense model on a Qwen2.5-0.5B backbone (1B in Hub metadata). A "tiny" MoE has 7.9B parameters with 1.3B active. Tested only on H800-80GB and H20-96G; no VRAM figure.
- **Voices:** built-in voices. The card names UK_George and US_Emma; secondary sources say there are five English voices in total, so the English female count is not confirmed. A `VOICE_DESIGN` task works from a description. Controls: an `EMOTION` task with 7 labels, slow/medium/fast speed, pitch and volume, a free-form instruction and 14 inline tags.
- **Licence:** MIT (Hub metadata "License: mit").
- **Reached:** no server. There is a Dockerfile (torch 2.6, CUDA 12.4), `infer.py` and a Python API. vLLM-Omni support is an unchecked roadmap item.
- **Evidence and maturity:** AA Elo 1182. Released 2026-10.
- **Sources:** https://github.com/inclusionAI/Ming-3.0-tts , https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5b

### VoxCPM2 (OpenBMB)
- **Needs:** GPU, about 8 GB, 2B params on MiniCPM-4. RTF 0.30 on an RTX 4090, or 0.13 with Nano-vLLM.
- **Voices:** no presets. Voice design from "a natural-language description — no reference audio needed". The README warns that "results can vary between runs"; `seed` is a Python argument. Style and pace are set in the text, with no separate speed field.
- **Licence:** "VoxCPM model weights and code are open-sourced under the Apache-2.0 license."
- **Reached:** `vllm serve openbmb/VoxCPM2 --omni` gives an OpenAI-compatible `/v1/audio/speech`. Nano-vLLM ships a FastAPI server.
- **Evidence and maturity:** vendor Seed-TTS test-EN WER 1.84, SIM 75.3. Not in the AA open list. Released 2026-04.
- **Source:** https://github.com/OpenBMB/VoxCPM

### Maya1 (Maya Research)
- **Needs:** GPU with 16 GB or more and BF16 support. 3.3B Llama-architecture model with a SNAC decoder.
- **Voices:** description only, for example `<description="Female, in her 30s with an American accent ...">`. 20 tags, including `<sarcastic> <laugh> <sigh> <whisper> <angry> <giggle>`. No reference cloning. Voice consistency between calls is not documented.
- **Licence:** "The model repository declares **Apache 2.0** in its metadata."
- **Reached:** vLLM streaming reference code. No official server; a third-party NVFP4 build has a wrapper on `/v1/audio/speech`.
- **Evidence and maturity:** AA Elo 1046, below Kokoro. Released 2025-10/11.
- **Source:** https://huggingface.co/maya-research/maya1

### Kyutai TTS 1.6B en_fr
- **Needs:** GPU, 1.8B params. Throughput "75x generated audio per compute unit of time". No VRAM figure.
- **Voices:** pre-computed embeddings from `kyutai/tts-voices`; cloning is "restrict[ed] ... to the use of pre-computed voice embeddings". Per-folder licences: vctk CC BY 4.0, expresso and ears CC BY-NC 4.0, voice-donations and voice-zero CC0. **Flag:** that repo also holds `unmute-prod-website/degaulle-2.wav`, a 1940 recording of General de Gaulle, a named public figure. Do not use it.
- **Licence:** weights "licensed under CC-BY 4.0". Server code is MIT (Python) and Apache (Rust).
- **Reached:** `moshi-server worker --config configs/config-tts.toml`, streaming over websockets. No OpenAI or Wyoming server.
- **Evidence and maturity:** no benchmark on the card. Paper dated 2025-09.
- **Sources:** https://huggingface.co/kyutai/tts-1.6b-en_fr , https://huggingface.co/kyutai/tts-voices , https://github.com/kyutai-labs/delayed-streams-modeling

### Pocket TTS (Kyutai)
- **Needs:** CPU, 100M params, about 6x real time on 2 cores of an Apple M4. The `serve` command and Docker files are CPU only. The weights are gated (accept the terms on Hugging Face).
- **Voices:** 21 English presets. About 10 are female by name: alba, anna, azelma, cosette, eponine, eve, fantine, jane, mary, vera; genders are not stated. Most come from VCTK, plus Expresso, EARS and donations. **Flags:** `alba` is voice actor Alba MacKenna (CC BY 4.0). `bill_boerst`, `caro_davy`, `peter_yearsley` and `stuart_bell` carry personal names (CC0 voice-zero donors; not confirmed). The model also clones from a wav, which is not used here.
- **Licence:** code MIT. Weights "License: cc-by-4.0", so attribution is required.
- **Reached:** `pocket-tts serve` on port 8000 (HTTP, not OpenAI). Community wrappers: `pocket-tts-wyoming` (Wyoming) and several OpenAI-compatible servers.
- **Evidence and maturity:** no formal benchmarks. Tech report dated 2026-01-13.
- **Sources:** https://huggingface.co/kyutai/pocket-tts , https://github.com/kyutai-labs/pocket-tts

### VibeVoice-Realtime 0.5B (Microsoft)
- **Needs:** GPU, real time on a T4. About 300 ms to first audio.
- **Voices:** embedded presets. English: Carter, Davis, Frank and Mike (male), Emma and Grace (female), and in-Samuel. Custom voices are withheld ("contact the team"). No documented controls.
- **Licence:** "License: mit". The card also says the model "is limited to research purposes".
- **Reached:** a websocket demo (`demo/vibevoice_realtime_demo.py`). No OpenAI or Wyoming server.
- **Evidence:** vendor LibriSpeech test-clean WER 2.00%. AA lists only VibeVoice 1.5B, at 954.
- **Sources:** https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B , https://github.com/microsoft/VibeVoice/tree/main/demo/voices/streaming_model

### Magpie TTS Multilingual 357M (NVIDIA)
- **Needs:** NVIDIA GPU (L4, A10 and up are listed). 364M params.
- **Voices:** 5 speakers chosen by index: Aria, Jason, Leo, Sofia and John. Genders are not stated. Zero-shot cloning was removed. **Flag:** "John" is John Van Stan, a public LibriVox voice, so that preset is built from one named person's recordings.
- **Licence:** NVIDIA Open Model License; "This model is ready for commercial use."
- **Reached:** NeMo Python or NeMo-Speech.cpp. No OpenAI or Wyoming server documented.
- **Evidence and maturity:** AA Elo 1060, level with Kokoro. Version v2607 (2026-07-21).
- **Source:** https://huggingface.co/nvidia/magpie_tts_multilingual_357m

### Smaller or weaker fits (brief)
- **Kitten TTS 2** (1.7B; small 2-series models from 7M to 82M; v0.8 ONNX models from 15M to 80M, CPU). 115 built-in voices per the README, 47 per a secondary source. Gender split not stated. Expression tags are in beta, and cloning exists (not used). Code Apache-2.0; weights under the Stellon Labs Community License (registration and "Powered by Stellon Labs" per a secondary source; not confirmed). An OpenAI-compatible Docker server exists. Release date not confirmed. https://github.com/KittenML/KittenTTS
- **Kani-TTS-2 en** (400M on LiquidAI LFM2-350M with NVIDIA NanoCodec; 3 GB VRAM; RTF ~0.2 on an RTX 5080). Six speakers, for example "Chelsea from New York" and "Rory from Glasgow"; genders not stated. Licence tag `lfm1.0`, text not fetched. OpenAI example server. https://huggingface.co/nineninesix/kani-tts-2-en
- **Supertonic 3** (99M, CPU, 2026-04-29). Voice styles F3-F5 and M3-M5 among others; count not confirmed. Weights "released under the OpenRAIL-M License". `supertonic serve` offers OpenAI `/v1/audio/speech`. The repository is archived: "Development and support have ended." https://github.com/supertone-inc/supertonic
- **Soprano 1.1 80M** (Apache-2.0, 2026-01-14). English only, no cloning; voice count not stated. OpenAI `/v1/audio/speech` without streaming. https://github.com/ekwek1/soprano
- **Parler-TTS Mini v1** (0.9B, Apache-2.0, 2024). 34 named speakers selected in a description, for example "Jon's voice is monotone...". https://huggingface.co/parler-tts/parler-tts-mini-v1
- **XTTS-v2** (Coqui). 58 built-in speakers, for example `speaker="Ana Florence"`. CPML: "This license allows only non-commercial use of a machine learning model and its outputs." AA Elo 914. https://coqui-tts.readthedocs.io/en/latest/models/xtts.html , https://tts-hub.github.io/cpml
- **MeloTTS** (MIT, CPU). Speaker ids EN-US, EN-BR, EN-INDIA, EN-AU and EN-Default; genders not stated. https://github.com/myshell-ai/MeloTTS
- **Piper** (code GPL-3.0 in `OHF-Voice/piper1-gpl`). Each voice has its own licence in its `MODEL_CARD`. Official Wyoming server `rhasspy/wyoming-piper` (MIT, port 10200). Usually rated below Kokoro; no arena entry. https://github.com/OHF-Voice/piper1-gpl , https://github.com/rhasspy/wyoming-piper
- **Spark-TTS 0.5B** (Qwen2.5 base). "Creating virtual speakers by adjusting parameters such as gender, pitch, and speaking rate"; whether that needs no reference audio is not stated explicitly. Weights cc-by-nc-sa-4.0. https://huggingface.co/SparkAudio/Spark-TTS-0.5B

## Excluded

- **Chatterbox, Chatterbox-Turbo, Multilingual, Nano (Resemble AI):** one implied default voice; any other voice comes from `audio_prompt_path`. The project is retired as of August 2026 (MIT archive). https://github.com/resemble-ai/chatterbox
- **Dia / Dia2 (Nari Labs):** no preset voices. "Use with prefix or fine-tune in order to obtain stable output." https://github.com/nari-labs/dia2
- **Sesame CSM-1B:** "has not been fine-tuned on any specific voice"; a stable voice needs context audio. https://huggingface.co/sesame/csm-1b
- **Zonos v0.1:** the voice comes from a speaker embedding made from a reference recording, or from an audio prefix. https://huggingface.co/Zyphra/Zonos-v0.1-transformer
- **F5-TTS:** inference takes `--ref_audio`; weights CC-BY-NC. https://github.com/SWivid/F5-TTS
- **IndexTTS2:** every documented call passes `spk_audio_prompt`; bilibili Model Use License. https://github.com/index-tts/index-tts
- **NeuTTS Air:** speaks "in the style of the reference audio". https://huggingface.co/neuphonic/neutts-air
- **Fish Audio Drama 3:** cloning from `audio_path`. 35B MoE (3B active), which also does not fit one 24 GB card unquantized. https://huggingface.co/fishaudio/Drama-3
- **Fish Speech / OpenAudio S1-mini / Fish S2 Pro:** no preset or description route on the S2 Pro card (S1-mini not re-checked); Fish Audio Research License. https://huggingface.co/fishaudio/s2-pro
- **CosyVoice 2 / Fun-CosyVoice3:** zero-shot from prompt audio. Only the older CosyVoice-300M-SFT has built-in speakers; their names are not on the README (not confirmed). https://github.com/FunAudioLLM/CosyVoice
- **StyleTTS2:** multi-speaker use needs a reference clip; the single-speaker LJSpeech model has one voice (not re-checked this session). AA Elo 888.
- **Higgs Audio v3 (Boson AI):** the open release documents zero-shot cloning; presets are confirmed only for the hosted API. Weights research and non-commercial. AA Elo 1038. https://github.com/boson-ai/higgs-audio
- **Not reviewed in depth:** Step-Audio-EditX (AA 1100), Gepard-1.0 (Apache-2.0, in vLLM-Omni), OmniVoice (k2-fsa; voice design and cloning; a mirror claims CC-BY-NC), MOSS-TTS-Nano.

## Recommendation (the worker's, for the coordinator and Tom)

Try two, in this order. Both meet the stock-voice rule without a reference clip, both have an official OpenAI-compatible
server, and neither needs the household ComfyUI GPU.

**1. Phonon 31m English: a cheap direct upgrade.** It is the only candidate ranked above Kokoro in an independent arena (1111
against 1061) that needs no GPU. Its 13 English female presets include 7 UK voices (a fit for the British-ish captain), and each
preset is a fixed embedding, so a character sounds the same on every line. Weights and voices are Apache-2.0. Gaps: no emotion or
style control, so deadpan or cheerful delivery has to come from the voice choice and the punctuation. It is new (2026-10-20), and
per-request speed is not confirmed on the server.

What the haynes-ops change adds:
- Image `ghcr.io/gradium-ai/ptts-openai-server:<pinned version + digest>`; the current tag is not confirmed.
- A Deployment with no GPU, on any node or next to Kokoro. Requests of about 1 CPU, limit 2, and a small memory limit to tune after measuring; no RAM figure is published.
- Env `PTTS_LANG=en`, `PTTS_QUANT=q8`, and optionally `PTTS_MODEL=hf://gradium/phonon-31m-en`.
- A model cache PVC of about 1 GiB for the HF download (64 MB weights plus voice files). The pod needs HTTPS egress to huggingface.co on first start, or a pre-seeded cache.
- A ClusterIP Service on TCP 8880 (HTTP).
- Optional Wyoming shape: a `ghcr.io/roryeckel/wyoming_openai` sidecar with `TTS_OPENAI_URL=http://localhost:8880/v1`. Its speed setting `TTS_SPEED` is server-wide, like `KOKORO_SPEED`.
- Studio call: `kubectl exec` into the pod and `POST localhost:8880/v1/audio/speech` with `{"input","voice","response_format":"wav"}`. Whether the image has curl or Python is not confirmed; the wyoming_openai sidecar is a Python app and could make the call.
- Per-request speed: not confirmed. The runtime has a `duration_delta` rate condition, but the server field is undocumented.

**2. Qwen3-TTS 12Hz 1.7B (VoiceDesign, then CustomVoice): the expressive option.** It is the only candidate with a ready
OpenAI-compatible server (vLLM-Omni) that takes a per-line natural-language delivery instruction ("flat, bored, deadpan";
"clipped and suspicious") and a per-request `speed`. Its instruction following has published English scores. Code and weights are
Apache-2.0. Gaps: it has no native-English female preset, so the four women would come from VoiceDesign descriptions, and the
README itself says a designed voice is not guaranteed to stay the same across lines. Its lock-in fix (clone a designed clip with
the Base model) is cloning from a reference clip, outside the rule as written, so the audition must measure identity drift
across about five lines per character. There is no independent open-weights arena score, and the arena's "Qwen3 TTS" entry (928, not marked open-weights) sits below Kokoro, so its case is expressive control, not proven preference; the audition has to show it.

What the haynes-ops change adds:
- Image `vllm/vllm-omni:<pinned stable tag + digest>`.
- One Deployment per model (one model per server). Start with `vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --omni --port 8091 --gpu-memory-utilization <low fraction>`. Add the CustomVoice model later only if the presets are wanted.
- GPU: `nvidia.com/gpu: 1` on a talosw01 RTX 3090. That card is under the studio's Wan compute lease, so the pod must run inside that lease and its unknown-work checks: for example `replicas: 0` outside audition windows, scaled up through git. vLLM preallocates its memory fraction; about 0.3 of 24 GB (≈7 GB) is a starting guess against ≈4 GB of BF16 weights, to measure. A GPU memory figure is not published.
- PVC `HF_HOME` of about 20 GiB, for two 1.7B checkpoints, the tokenizer and the vLLM compile cache (estimate).
- A ClusterIP Service on TCP 8091 (HTTP).
- Studio call: `kubectl exec` into the pod and post JSON to `localhost:8091/v1/audio/speech` with Python, which the vLLM image includes. Send `task_type: "VoiceDesign"`, `instructions` with the character description plus the line's delivery note, `speed`, and `response_format: "wav"`.
- Do not enable or call `ref_audio`, the Base model or the voice-upload endpoint.
- Wyoming is possible through wyoming_openai, but its `TTS_INSTRUCTIONS` is server-wide, so HTTP direct suits per-line direction better.
- Per-request speed: yes, the `speed` field (0.25-4.0, not with streaming). Whether Qwen3 renders it natively or by time-stretch is not confirmed.

**Next if these fall short (not recommended now):**
- Orpheus 3B, if Qwen3's designed voices drift. It has five consistent preset female voices (US by name), laugh, sigh and groan tags, and per-request speed through Orpheus-FastAPI. It has no independent 2026 ranking, and its last release is from 2025.
- Ming-3.0-tts (AA 1182) has presets with emotion and speed controls, but no server. It is tested only on 80-96 GB cards and has few English voices.
- Breeze TTS 2 (AA 1229) has the same drift issue as Qwen3 VoiceDesign, and its weights are research-only.
- Voxtral (AA 1094) has only three English female presets and no style control.

## Licence facts for the register

```json
[
  {
    "key": "phonon-31m-en",
    "name": "Phonon 31m English (Gradium), with the gradium/phonon-voices catalogue",
    "source": "https://huggingface.co/gradium/phonon-31m-en",
    "source_revision": "92741c5b07d085ff840e26fea8ce43110b87852f",
    "licence": {
      "name": "Apache-2.0",
      "url": "https://huggingface.co/gradium/phonon-31m-en/blob/92741c5b07d085ff840e26fea8ce43110b87852f/README.md",
      "commercial_use": "allowed",
      "attribution_required": false,
      "note": "Weights, tokenizer and voices Apache-2.0. The voice catalogue repo gradium/phonon-voices at 0ee17205f254b5abc43b266c8a0f215565c352f7 is also apache-2.0. Runtime and ptts-openai-server code (github.com/gradium-ai/xn-ptts) is MIT OR Apache-2.0. Apache-2.0 asks redistributors to keep the licence and notices; it puts no attribution duty on generated audio. Phonon 40m models are CC BY-NC 4.0 and not covered here. Voice sources and consent are not stated."
    },
    "evidence": [
      {"url": "https://huggingface.co/gradium/phonon-31m-en", "quote": "The weights, tokenizer and voices in this repository are released under Apache 2.0, which allows commercial use."},
      {"url": "https://huggingface.co/gradium/phonon-voices", "quote": "License: apache-2.0"}
    ]
  },
  {
    "key": "qwen3-tts-12hz-1.7b",
    "name": "Qwen3-TTS 12Hz 1.7B CustomVoice and VoiceDesign (Alibaba Qwen)",
    "source": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "source_revision": "0c0e3051f131929182e2c023b9537f8b1c68adfe",
    "licence": {
      "name": "Apache-2.0",
      "url": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/blob/0c0e3051f131929182e2c023b9537f8b1c68adfe/README.md",
      "commercial_use": "allowed",
      "attribution_required": false,
      "note": "The VoiceDesign card at 5ecdb67327fd37bb2e042aab12ff7391903235d3 also carries apache-2.0. Code github.com/QwenLM/Qwen3-TTS is Apache-2.0 (repo sidebar). Served by vLLM-Omni, whose licence was not checked. Apache-2.0 asks redistributors to keep the licence and notices. The tokenizer checkpoint Qwen3-TTS-Tokenizer-12Hz was not checked separately."
    },
    "evidence": [
      {"url": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "quote": "License: apache-2.0"},
      {"url": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "quote": "License: apache-2.0"}
    ]
  }
]
```

## Not confirmed

- Phonon: x86 CPU speed and RAM use, a per-request speed field on the server, the current image tag, and where the catalogue voices come from (sources and consent).
- Qwen3-TTS: a published VRAM figure, how stable a VoiceDesign voice stays across calls, whether vLLM-Omni accepts a seed, whether `speed` is rendered natively, and the live `vllm/vllm-omni` stable tag.
- Others: Ming English voice list, Orpheus VRAM under llama.cpp and voice genders, the Kani and Kitten 2 licence terms and voice genders, XTTS-v2 server status, Spark-TTS reference-free status, and the StyleTTS2 and CosyVoice-SFT details.
