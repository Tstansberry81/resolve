#!/usr/bin/env python3
"""Train a custom 'hey resolve' openWakeWord keyword head, fully locally.

Pipeline mirrors openwakeword-wasm-browser EXACTLY (same melspectrogram +
embedding ONNX models, same framing: 1280-sample frames -> mel*? /10+2 -> 76-frame
windows slid by 8 -> 96-d embeddings -> 16-embedding head window), so the trained
head drops straight into the browser engine.

Phases:
  validate  gen 'hey jarvis' via macOS `say`, score through the REAL hey_jarvis
            head using our pipeline -> proves feature extraction matches inference
  gen       synthesize + augment positives/negatives, extract features, cache npy
  train     train the head, report metrics, export hey_resolve.onnx (verified)
"""
import hashlib
import os
import subprocess
import sys
import numpy as np
import onnxruntime as ort
import soundfile as sf

SB = "/private/tmp/claude-501/-Users-travelerstansberry-claude/35a6422f-c3e7-4392-a7ae-a40d70bc24d9/scratchpad"
WORK = os.path.join(SB, "oww-work")
CACHE = os.path.join(WORK, "wavcache")
MODELS = "/Users/travelerstansberry/claude/resolve/apps/dashboard/public/openwakeword/models"
os.makedirs(CACHE, exist_ok=True)

SR = 16000
FRAME = 1280
MEL_WIN = 76
MEL_HOP = 8
WIN = 16          # embedding window (head input timesteps)
EMB = 96

VOICES = ["Daniel", "Karen", "Kathy", "Moira", "Samantha", "Tessa", "Rishi",
          "Flo", "Eddy", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy",
          "Shelley", "Tara", "Albert", "Fred"]
RATES = [160, 180, 200, 220]

_mel = ort.InferenceSession(os.path.join(MODELS, "melspectrogram.onnx"))
_emb = ort.InferenceSession(os.path.join(MODELS, "embedding_model.onnx"))
_mel_in = _mel.get_inputs()[0].name
_emb_in = _emb.get_inputs()[0].name


def say_wav(text, voice, rate):
    """macOS `say` -> 16k mono float32, cached."""
    key = hashlib.md5(f"{text}|{voice}|{rate}".encode()).hexdigest()[:16]
    wav = os.path.join(CACHE, key + ".wav")
    if not os.path.exists(wav):
        aiff = os.path.join(CACHE, key + ".aiff")
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", aiff, text],
                       check=True, capture_output=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        aiff, wav], check=True, capture_output=True)
        os.remove(aiff)
    a, _ = sf.read(wav, dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    return a


def embeddings(audio):
    """Exact oWW feature stream: audio(float32 [-1,1]) -> [T,96]."""
    buf = []
    out = []
    n = len(audio) // FRAME
    for i in range(n):
        chunk = audio[i * FRAME:(i + 1) * FRAME].astype(np.float32)
        mel = _mel.run(None, {_mel_in: chunk[None, :]})[0].flatten()[:160]
        mel = mel / 10.0 + 2.0
        for j in range(5):
            buf.append(mel[j * 32:(j + 1) * 32])
        while len(buf) >= MEL_WIN:
            w = np.stack(buf[:MEL_WIN]).reshape(1, MEL_WIN, 32, 1).astype(np.float32)
            e = _emb.run(None, {_emb_in: w})[0].flatten()
            out.append(e.astype(np.float32))
            del buf[:MEL_HOP]
    return np.array(out, dtype=np.float32) if out else np.zeros((0, EMB), np.float32)


def windows(emb):
    """All length-16 windows [N,16,96] (stride 1)."""
    if len(emb) < WIN:
        return np.zeros((0, WIN, EMB), np.float32)
    return np.stack([emb[i:i + WIN] for i in range(len(emb) - WIN + 1)])


def rms_norm(a, target=0.08):
    r = np.sqrt(np.mean(a ** 2)) + 1e-9
    return (a * (target / r)).astype(np.float32)


def resample(a, factor):
    """Cheap speed/pitch shift by linear resample."""
    n = int(len(a) / factor)
    if n < 8:
        return a
    xp = np.linspace(0, len(a) - 1, n)
    return np.interp(xp, np.arange(len(a)), a).astype(np.float32)


def score_seq(sess, name, emb):
    """Max keyword score over all length-16 windows, scored ONE at a time
    (these heads have a fixed batch dim of 1, like the browser runtime)."""
    best = 0.0
    for k in range(len(emb) - WIN + 1):
        w = emb[k:k + WIN][None, :, :].astype(np.float32)
        best = max(best, float(sess.run(None, {name: w})[0].flatten()[0]))
    return best


def pad_to_context(utter, secs=4.0, tail=0.45, noise=0.0, rng=None):
    """Place an utterance inside a `secs` context ending ~`tail`s from the end,
    padded with low noise so the head sees ~3s of streaming context."""
    total = int(secs * SR)
    u = utter[:total]
    tail_n = int(tail * SR)
    start = max(0, total - tail_n - len(u))
    out = (rng.standard_normal(total).astype(np.float32) * noise) if rng is not None else np.zeros(total, np.float32)
    end = min(total, start + len(u))
    out[start:end] += u[:end - start]
    return np.clip(out, -1.0, 1.0)


# ── phases ──────────────────────────────────────────────────────────────────
def phase_validate():
    print("== VALIDATE pipeline vs real hey_jarvis head ==", flush=True)
    hj = ort.InferenceSession(os.path.join(MODELS, "hey_jarvis_v0.1.onnx"))
    hj_in = hj.get_inputs()[0].name

    def peak_score(audio):
        return score_seq(hj, hj_in, embeddings(audio))

    rng = np.random.default_rng(0)
    pos, neg = [], []
    for v in VOICES[:8]:
        a = pad_to_context(rms_norm(say_wav("hey jarvis", v, 180)), noise=0.002, rng=rng)
        pos.append(peak_score(a))
    for txt in ["hey resolve", "good morning", "what's the weather", "hey there buddy",
                "the quick brown fox", "resolve the issue", "hey jasmine"]:
        a = pad_to_context(rms_norm(say_wav(txt, "Samantha", 180)), noise=0.002, rng=rng)
        neg.append(peak_score(a))
    print(f"hey_jarvis positives  peak scores: {[round(x,3) for x in pos]}", flush=True)
    print(f"non-jarvis  negatives peak scores: {[round(x,3) for x in neg]}", flush=True)
    print(f"pos mean={np.mean(pos):.3f}  neg mean={np.mean(neg):.3f}", flush=True)
    ok = np.mean(pos) > 0.5 and np.mean(neg) < 0.3
    print("PIPELINE MATCH:", "PASS ✅" if ok else "CHECK ⚠️", flush=True)
    return ok


POS_PHRASES = ["hey resolve", "hey, resolve"]
NEG_PHRASES = ["resolve", "hey", "hey jarvis", "resolved", "resolution", "revolve",
               "reserve", "results", "hey there", "hey siri", "hey google", "solve it",
               "hey resolute", "the resolve", "hey results", "okay sure", "good morning",
               "what's the weather", "the quick brown fox jumps", "set a timer for ten",
               "how are you doing today", "play some music", "turn off the lights",
               "hey resolved it", "let's resolve this", "i will resolve", "hey res",
               "call mom", "send a message", "what time is it"]


def phase_gen():
    print("== GEN data + features ==", flush=True)
    rng = np.random.default_rng(42)
    Xp, Xn = [], []

    def aug_variants(base, k):
        outs = []
        for _ in range(k):
            a = base.copy()
            f = rng.uniform(0.85, 1.15)
            a = resample(a, f)
            a = rms_norm(a, target=rng.uniform(0.05, 0.12))
            a = pad_to_context(a, tail=rng.uniform(0.2, 0.5),
                               noise=rng.uniform(0.0, 0.01), rng=rng)
            outs.append(a)
        return outs

    # positives: last 4 windows (phrase just completed) labeled 1
    npos_clip = 0
    for v in VOICES:
        for ph in POS_PHRASES:
            for r in RATES:
                base = say_wav(ph, v, r)
                for a in aug_variants(base, 4):
                    w = windows(embeddings(a))
                    if len(w) >= 4:
                        Xp.append(w[-4:])
                        npos_clip += 1
    if Xp:
        Xp = np.concatenate(Xp)
    print(f"positive windows: {len(Xp)} from {npos_clip} clips", flush=True)

    # negatives: all windows from diverse negative speech (subsampled)
    for v in VOICES:
        for ph in NEG_PHRASES:
            base = say_wav(ph, v, rng.choice(RATES))
            a = pad_to_context(rms_norm(base, target=rng.uniform(0.05, 0.12)),
                               tail=rng.uniform(0.1, 0.6), noise=rng.uniform(0, 0.01), rng=rng)
            w = windows(embeddings(a))
            if len(w):
                Xn.append(w)
    # pure noise/silence negatives
    for _ in range(120):
        a = (rng.standard_normal(int(4 * SR)).astype(np.float32) * rng.uniform(0.0, 0.03))
        w = windows(embeddings(a))
        if len(w):
            Xn.append(w)
    Xn = np.concatenate(Xn)
    # subsample negatives to ~2x positives for balance
    cap = min(len(Xn), max(2 * len(Xp), 3000))
    idx = rng.choice(len(Xn), cap, replace=False)
    Xn = Xn[idx]
    print(f"negative windows: {len(Xn)} (capped)", flush=True)

    np.save(os.path.join(WORK, "Xp.npy"), Xp)
    np.save(os.path.join(WORK, "Xn.npy"), Xn)
    print("saved features", flush=True)


def phase_train():
    import torch
    import torch.nn as nn
    print("== TRAIN head ==", flush=True)
    Xp = np.load(os.path.join(WORK, "Xp.npy"))
    Xn = np.load(os.path.join(WORK, "Xn.npy"))
    X = np.concatenate([Xp, Xn]).astype(np.float32)
    y = np.concatenate([np.ones(len(Xp)), np.zeros(len(Xn))]).astype(np.float32)
    rng = np.random.default_rng(1)
    perm = rng.permutation(len(X))
    X, y = X[perm], y[perm]
    ntr = int(0.85 * len(X))
    Xtr, ytr, Xva, yva = X[:ntr], y[:ntr], X[ntr:], y[ntr:]

    dev = "mps" if torch.backends.mps.is_available() else "cpu"

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Flatten(), nn.Linear(WIN * EMB, 256), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(256, 128), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(128, 1), nn.Sigmoid(),
            )

        def forward(self, x):
            return self.net(x)

    model = Head().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.BCELoss()
    Xtr_t = torch.tensor(Xtr, device=dev)
    ytr_t = torch.tensor(ytr, device=dev).unsqueeze(1)
    Xva_t = torch.tensor(Xva, device=dev)
    bs = 256
    for ep in range(40):
        model.train()
        for i in range(0, len(Xtr_t), bs):
            opt.zero_grad()
            out = model(Xtr_t[i:i + bs])
            loss = lossf(out, ytr_t[i:i + bs])
            loss.backward()
            opt.step()
        if ep % 10 == 9 or ep == 0:
            model.eval()
            with torch.no_grad():
                p = model(Xva_t).cpu().numpy().flatten()
            acc = ((p > 0.5) == (yva > 0.5)).mean()
            tp = ((p > 0.5) & (yva > 0.5)).sum(); fp = ((p > 0.5) & (yva < 0.5)).sum()
            fn = ((p <= 0.5) & (yva > 0.5)).sum()
            prec = tp / (tp + fp + 1e-9); rec = tp / (tp + fn + 1e-9)
            print(f"ep{ep+1:02d} val acc={acc:.3f} prec={prec:.3f} rec={rec:.3f}", flush=True)

    # export ONNX [1,16,96] -> [1,1]
    model.eval()
    out_path = os.path.join(WORK, "hey_resolve.onnx")
    dummy = torch.zeros(1, WIN, EMB, device=dev)
    torch.onnx.export(model, dummy, out_path, input_names=["x"], output_names=["score"],
                      opset_version=17,
                      dynamic_axes={"x": {0: "batch"}, "score": {0: "batch"}})
    print("exported", out_path, flush=True)

    # verify ONNX parity + shape[1]==16
    sess = ort.InferenceSession(out_path)
    shp = sess.get_inputs()[0].shape
    print("onnx input shape:", shp, flush=True)
    with torch.no_grad():
        t = model(Xva_t[:200]).cpu().numpy().flatten()
    o = sess.run(None, {sess.get_inputs()[0].name: Xva[:200]})[0].flatten()
    print(f"torch/onnx max abs diff: {np.abs(t - o).max():.2e}", flush=True)
    # final metrics via ONNX on full val
    o_all = sess.run(None, {sess.get_inputs()[0].name: Xva})[0].flatten()
    for thr in (0.5, 0.7, 0.85):
        acc = ((o_all > thr) == (yva > 0.5)).mean()
        fp = ((o_all > thr) & (yva < 0.5)).sum(); fpr = fp / (yva < 0.5).sum()
        rec = ((o_all > thr) & (yva > 0.5)).sum() / (yva > 0.5).sum()
        print(f"[onnx] thr={thr}: acc={acc:.3f} recall={rec:.3f} FPR={fpr:.3f}", flush=True)


if __name__ == "__main__":
    ph = sys.argv[1] if len(sys.argv) > 1 else "all"
    if ph in ("validate", "all"):
        if not phase_validate() and ph == "all":
            print("Pipeline validation failed — stopping before training.", flush=True)
            sys.exit(1)
    if ph in ("gen", "all"):
        phase_gen()
    if ph in ("train", "all"):
        phase_train()
