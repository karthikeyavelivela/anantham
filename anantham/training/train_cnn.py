"""Train the CNN verifier / heatmap network on simulator data and export ONNX.

Requires PyTorch (training only — inference uses ONNX Runtime). Writes
``verifier.onnx`` and ``verifier_card.json`` (dataset size, seed, validation metrics
measured on a held-out split) into the output directory.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np


def build_model():
    """Small fully convolutional net: stride-4 heatmap + offsets, and a global score head."""
    import torch
    from torch import nn

    class VerifierNet(nn.Module):
        def __init__(self):
            super().__init__()

            def cbr(i, o, s=1, d=1):
                return nn.Sequential(nn.Conv2d(i, o, 3, s, d, dilation=d), nn.ReLU(inplace=True))

            self.body = nn.Sequential(cbr(1, 8), cbr(8, 16, 2), cbr(16, 16), cbr(16, 32, 2),
                                      cbr(32, 32, 1, 2), cbr(32, 32))
            self.heat = nn.Conv2d(32, 1, 1)
            self.off = nn.Conv2d(32, 2, 1)
            self.fc = nn.Sequential(nn.Linear(64 + 1, 32), nn.ReLU(inplace=True), nn.Linear(32, 1))

        def forward(self, x):
            f = self.body(x)
            heat = self.heat(f)
            off = torch.sigmoid(self.off(f))
            h, w = f.shape[2], f.shape[3]
            c = f[:, :, h // 2 - 2:h // 2 + 2, w // 2 - 2:w // 2 + 2]
            hc = heat[:, :, h // 2 - 2:h // 2 + 2, w // 2 - 2:w // 2 + 2]
            g = torch.cat([c.mean((2, 3)), f.amax((2, 3)), hc.amax((2, 3))], 1)
            return self.fc(g), heat, off

    return VerifierNet()


def _losses(model, xb, sb, hb, ob, mb):
    import torch
    import torch.nn.functional as F

    score, heat, off = model(xb)
    l_s = F.binary_cross_entropy_with_logits(score[:, 0], sb)
    # focal-style weighting of the heatmap (positives are rare)
    p = torch.sigmoid(heat[:, 0])
    w = torch.where(hb > 0.5, 4.0, 1.0) * (1 - hb + 0.25)
    l_h = (F.binary_cross_entropy_with_logits(heat[:, 0], hb, reduction="none") * w).mean()
    l_o = (torch.abs(off - ob).sum(1) * mb).sum() / mb.sum().clamp(min=1)
    _ = p
    return l_s + 2.0 * l_h + 1.0 * l_o, (score, heat, off)


def evaluate(model, data: dict, idx: np.ndarray) -> dict:
    """Validation metrics on the held-out indices."""
    import torch

    from ..perception.cnn import decode_heatmap

    model.eval()
    probs, errs = [], []
    with torch.no_grad():
        for i in range(0, len(idx), 1024):
            j = idx[i:i + 1024]
            xb = torch.from_numpy(data["x"][j].astype(np.float32))[:, None]
            s, h, o = model(xb)
            probs.append(torch.sigmoid(s[:, 0]).numpy())
            h, o = h[:, 0].numpy(), o.numpy()
            for k, jj in enumerate(j):
                if data["score"][jj] > 0.5:
                    hy, hx = np.unravel_index(np.argmax(data["heat"][jj]), data["heat"][jj].shape)
                    tx = (hx + data["offset"][jj][0, hy, hx]) * 4
                    ty = (hy + data["offset"][jj][1, hy, hx]) * 4
                    px, py, _ = decode_heatmap(h[k], o[k])
                    errs.append(math.hypot(px - tx, py - ty))
    p = np.concatenate(probs)
    y = data["score"][idx] > 0.5
    pred = p >= 0.5
    tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
    fn, tn = int((~pred & y).sum()), int((~pred & ~y).sum())
    e = np.array(errs)
    return {"n_val": int(len(idx)), "accuracy": (tp + tn) / len(idx),
            "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
            "false_positive_rate": fp / max(fp + tn, 1), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "heatmap_loc_err_px_median": float(np.median(e)) if e.size else None,
            "heatmap_loc_err_px_p95": float(np.percentile(e, 95)) if e.size else None}


def train(n_samples: int = 60000, epochs: int = 12, seed: int = 0, out_dir: str | Path = ".",
          log=print) -> dict:
    """Generate data, train, validate, export ONNX; returns the model card."""
    import torch

    from .export_onnx import export
    from .make_dataset import make_dataset

    torch.manual_seed(seed)
    torch.set_num_threads(2)
    t0 = time.time()
    data = make_dataset(n_samples, seed)
    log(f"dataset: {n_samples} samples in {time.time() - t0:.1f}s, "
        f"positives {data['score'].mean():.3f}")
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n_samples)
    n_val = max(n_samples // 10, 500)
    val, tr = perm[:n_val], perm[n_val:]
    model = build_model()
    opt = torch.optim.AdamW(model.parameters(), 2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 3e-3, total_steps=epochs * (len(tr) // 256 + 1))
    tens = {k: torch.from_numpy(v.astype(np.float32)) for k, v in data.items()}
    hist = []
    for ep in range(epochs):
        model.train()
        rng.shuffle(tr)
        tot, nb = 0.0, 0
        for i in range(0, len(tr), 256):
            j = torch.from_numpy(tr[i:i + 256])
            loss, _ = _losses(model, tens["x"][j][:, None], tens["score"][j], tens["heat"][j],
                              tens["offset"][j], tens["mask"][j][:, None].squeeze(1))
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot, nb = tot + float(loss), nb + 1
        m = evaluate(model, data, val)
        hist.append({"epoch": ep + 1, "train_loss": tot / nb, **m})
        log(f"epoch {ep + 1}/{epochs} loss {tot / nb:.4f} val acc {m['accuracy']:.4f} "
            f"prec {m['precision']:.4f} rec {m['recall']:.4f} loc {m['heatmap_loc_err_px_median']:.3f}px")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / "verifier.onnx"
    export(model, onnx_path)
    card = {"model": "verifier.onnx", "n_samples": n_samples, "val_fraction": n_val / n_samples,
            "epochs": epochs, "seed": seed, "train_time_s": time.time() - t0,
            "final": hist[-1], "history": hist,
            "params": int(sum(p.numel() for p in model.parameters())),
            "dataset": "anantham.training.make_dataset (domain-randomised simulator ROIs)"}
    (out / "verifier_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def main_train(args) -> None:
    """CLI entry (``anantham train``)."""
    card = train(args.samples, args.epochs, args.seed, args.out)
    print(json.dumps(card["final"], indent=2))
