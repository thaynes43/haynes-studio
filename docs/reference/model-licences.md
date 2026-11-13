# Model licences

The register of licence terms for every engine and model file that makes or checks
studio output today. The data is [`model-licences.json`](model-licences.json); this page
summarizes it. Story [809](https://work.haynesnetwork.com/work_packages/809), decision
D48 in the [studio plan](../proposals/0003-studio-plan.md).

- **Checked** 2026-11-13 by the dev-env agent session `haynes-studio-1113-141004`
  (Claude Code, `claude-opus-5-5`), on Tom's direction. Tom did not check these terms.
- **What it is:** what each publisher's licence text and model card say, with the URL
  read (pinned to the revision read) and the words quoted. Quotes are verbatim, with
  Markdown formatting (links, bold, bullets, list dashes) removed; card metadata lines
  are joined with semicolons. Every judgement is that session's
  reading of the text. **It is not legal advice**, and it clears nothing beyond what
  the quoted text says.
- **What it covers:** the studio running a model and using what it makes. The studio
  does not redistribute model weights, so redistribution terms are noted, not applied.
- **The studio's own rights** are a separate matter: the creative work is all rights
  reserved ([RIGHTS.md](../../RIGHTS.md)). The register records the models' terms, not
  the studio's.

## Engines

"Commercial use" is commercial use of what the engine makes. An engine's terms are the
most restrictive of its files.

| Engine | Makes | Licence | Commercial use | Conditions | What Tom would do or decide |
|---|---|---|---|---|---|
| Qwen-Image 2.1 on ComfyUI (text-to-image and edit) | cast stills, sets | Qwen Research License Agreement | **research or evaluation only** (narrower than non-commercial) | "FOR NON-COMMERCIAL PURPOSES ONLY", where Non-Commercial means "research or evaluation purposes only"; commercial use needs a separate licence from the licensor | Q-809-1 |
| Kokoro-82M v1.0 (stock voices) | voice takes | Apache-2.0 | allowed | none on outputs | nothing |
| Stable Audio 3 Small-SFX (audio-authoring, CPU) | sound effects, beds | Stability AI Community License Agreement; Gemma Terms of Use for its text encoder | **conditional** | hobby use is free; commercial use needs registration with Stability AI, and every licence ends above USD 1,000,000 annual revenue (Tom and his affiliates); Acceptable Use Policy; no training a foundational model on outputs; Gemma Prohibited Use Policy | Q-809-2 |
| Wan2.2 TI2V-5B | image-to-video clips | Apache-2.0 | allowed | the card's use restrictions (no content that breaks the law, harms people, spreads misinformation or targets vulnerable groups) | nothing |
| Wan2.2 S2V-14B with its wav2vec2 audio encoder and the lightx2v 4-step LoRA | speech-to-video clips | Apache-2.0 (every file) | allowed | as TI2V | nothing |
| Whisper service: Parakeet TDT 0.6B v2 (ONNX) | transcripts that check a video's words | CC-BY-4.0 | allowed | attribution when sharing the model; transcripts are never published | nothing |
| ControlFoley (Foley sidecar) | Foley sound from a clip; in no delivered video | CC-BY-NC-4.0 weights; Apple research-only CLIP encoder; MIT vocoder | **non-commercial**, and research only for the CLIP encoder | weights CC BY-NC 4.0; the CLIP encoder is licensed "exclusively for Research Purposes" (scientific research) | Q-809-3 |

A video carries the terms of its inputs as well as its own engine's, so check the
whole chain (session's reading). A Wan clip made from a Qwen-Image 2.1 still uses a
research-only input even though Wan itself is Apache-2.0.

## Held for Tom

The session's reading, not legal advice. Nothing here is decided.

- **Q-809-1 Qwen-Image 2.1 (every cast still and set so far).** The licence allows only
  "research or evaluation purposes", and the text does not say whether shorts made for
  fun count. (a) Keep using it as research and evaluation of the studio, and never use
  its images commercially. (b) Ask the licensor for a commercial licence (only Tom can).
  (c) Move the image lane to a Qwen-Image model whose card says Apache-2.0 (the 2512 and
  Edit 2509 models already on `comfyui-0` say so on their cards; not checked further
  here) in a later story, and re-make the cast. **Recommendation: (c)** before any
  release, (a) meanwhile.
- **Q-809-2 Stable Audio 3 (every sound so far).** Hobby use is free. (a) Do nothing until
  a release would be commercial, then register with Stability AI (Tom's account, Tom's
  action) and stay under the revenue limit. (b) Register now. **Recommendation: (a)**,
  as a step of the release story.
- **Q-809-3 ControlFoley (in no delivered video).** (a) Keep it to private experiments and
  out of any released video. (b) Replace it. **Recommendation: (a).**

## Files

| File | Engine | Licence | Commercial use | Pinned |
|---|---|---|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | Qwen-Image | Qwen Research | non-commercial | no |
| `qwen3vl_8b_int8_convrot.safetensors` | Qwen-Image | Qwen Research (its repository's licence) | non-commercial | no |
| `qwen_image_2.1_vae_bf16.safetensors` | Qwen-Image | Qwen Research | non-commercial | no |
| `kokoro-v1_0.pth` | Kokoro | Apache-2.0 | allowed | image digest only |
| Stable Audio 3 Small-SFX model and autoencoder | Stable Audio | Stability AI Community | conditional | revision only |
| T5Gemma text encoder | Stable Audio | Gemma Terms of Use | allowed | revision only |
| `wan2.2_ti2v_5B_fp16.safetensors` | TI2V | Apache-2.0 | allowed | sha256 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | TI2V | Apache-2.0 | allowed | sha256 |
| `wan2.2_vae.safetensors` | TI2V | Apache-2.0 | allowed | sha256 |
| `wan2.2_s2v_14B_fp8_scaled.safetensors` | S2V | Apache-2.0 | allowed | sha256 |
| `wav2vec2_large_english_fp16.safetensors` | S2V | Apache-2.0 | allowed | sha256 |
| `wan_2.1_vae.safetensors` | S2V | Apache-2.0 | allowed | sha256 |
| `wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors` | S2V | Apache-2.0 | allowed | sha256 |
| Parakeet TDT 0.6B v2 (ONNX) | Whisper service | CC-BY-4.0 | allowed | no |
| `weights/controlfoley.pth` | ControlFoley | CC-BY-NC-4.0 | non-commercial | sha256 |
| `ext_weights/` (`v1-44.pth`, `synchformer_state_dict.pth`, `cav_mae_st.pth`) | ControlFoley | CC-BY-NC-4.0 (its repository's licence) | non-commercial | sha256 |
| DFN5B CLIP ViT-H-14-384 | ControlFoley | Apple ML Research Model licence | non-commercial | sha256 |
| BigVGAN v2 44 kHz vocoder | ControlFoley | MIT | allowed | sha256 |

"Pinned" says whether haynes-ops pins the file by hash; the JSON gives each source,
revision and hash.

## Limits of this check

- **Qwen-Image 2.1:** haynes-ops pins no revision or hash for the ComfyUI image models.
  The source recorded is the one the stored workflow links (`Comfy-Org/Qwen-Image-2.1`).
  Its text encoder is recorded under that repository's licence; the card does not say
  whether it is the Apache-2.0 Qwen3-VL-8B unchanged.
- **Stable Audio 3:** the service uses the ungated `stabilityai/stable-audio-3-optimized`
  distribution, whose licence files were read. The gated
  `stabilityai/stable-audio-3-small-sfx` page needs a login and agreement to terms; it was
  not opened or accepted, and its own `LICENSE.md` was not read. The exact files the
  service loads are in its private manifest.
- **Kokoro:** the service image is pinned by digest, but which weight file it loads is not
  public; v1.0 is the version this repository records.
- **Parakeet:** onnx-asr maps the model name to its ONNX repository on onnx-asr's main
  branch; the version inside the service image was not checked.
- **ControlFoley:** its three `ext_weights` files are third-party models redistributed in
  its repository; their upstream terms were not checked. Its vocoder's card links a
  licence in `nvidia/BigVGAN` that needs a login; the MIT `LICENSE` in the vocoder's own
  repository was read instead.
- **Inferred "allowed":** for the Gemma text encoder and the MIT vocoder, "allowed" rests on
  the absence of any commercial restriction, not on a sentence that names commercial use.

## Using the register

- The Winter Menu library builder
  ([`winter_menu.py`](../../src/haynes_studio/library/winter_menu.py)) gives each version
  the licence object of the engine whose `recorded_as` name its model or service text
  contains as a whole name. No match, or more than one, leaves `commercial_use: unknown`
  with the reason.
- Each `licence` in the JSON is a contract licence object
  ([section 7](../contracts/studio-contracts-v1.md#7-provenance-licences-and-public-credits)).
  When the terms were checked the contract had no value for a conditional term, so the
  register records `conditional` in `outputs_commercial_use` and `unknown` in the licence
  object, with the conditions in its `note`. The contract has had `conditional` since
  2026-11-13 (P-23), and the schema accepts it since story
  [849](https://work.haynesnetwork.com/work_packages/849); the library's lookup now
  gives `conditional` for such an entry and keeps its note.
- `checked_by` in each licence object is
  `{kind: worker, worker_id: "dev-env agent session haynes-studio-1113-141004"}`, as
  recorded at the check, when the contract had no principal for an agent session
  without a studio key. It has one now, `{kind: agent_session, session, harness,
  model}` (P-24, in the schema since story 849); these entries are left as recorded.
- To add a model or change a term: read the publisher's page and licence, add or edit the
  file and engine entries with the URL, the quoted words, the date and the checker, and
  run `uv run pytest tests/library`. Never accept terms, log in or register to read a
  page; record that as a condition and leave the entry `unknown`.
