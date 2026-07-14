# Custom wake-word training ("hey resolve")

Trains a custom openWakeWord keyword head that drops straight into the browser
wake engine (`openwakeword-wasm-browser`) used by the dashboard. Produced
`hey_resolve.onnx`, now living in `apps/dashboard/public/openwakeword/models/`.

## How it works
`build_wake.py` mirrors the browser engine's feature pipeline EXACTLY (same
bundled `melspectrogram.onnx` + `embedding_model.onnx`; 1280-sample frames →
`mel/10+2` → 76-frame windows slid by 8 → 96-d embeddings → 16-embedding head
window), so a head trained on these features behaves identically at inference.

- **Data**: synthesized locally with macOS `say` (18 voices × rates) for the
  positive phrase, plus hard negatives ("resolve", "resolved", "revolve",
  "hey jarvis", …), diverse negative speech, and noise. Augmented (speed/pitch
  via resample, gain, background noise, offset).
- **Validation**: before training it scores `say`-generated "hey jarvis" through
  the REAL `hey_jarvis_v0.1.onnx` and asserts the pipeline separates pos/neg —
  proof the feature extraction matches the browser runtime.
- **Head**: small MLP over the flattened `[16,96]` window → sigmoid score.
- **Export**: single self-contained ONNX, input `[batch,16,96]` → `[batch,1]`.

## Reproduce / retrain
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install numpy onnxruntime soundfile torch onnx onnxscript
python build_wake.py all           # validate → gen → train → export
# result: <workdir>/hey_resolve.onnx  → copy to public/openwakeword/models/
```
Last run: val acc 0.96, precision 0.98; on held-out synthetic voices, "hey
resolve" scored 0.96–1.0 and all negatives < 0.33.

## Limitations / future
Trained on TTS voices only (like openWakeWord itself, but with fewer voices than
Piper). Real-voice performance is good but tune `NEXT_PUBLIC_WAKE_THRESHOLD` by
ear. For a more robust model, use the official openWakeWord Colab pipeline
(Piper voices + real negative audio) and drop the resulting `.onnx` in.
