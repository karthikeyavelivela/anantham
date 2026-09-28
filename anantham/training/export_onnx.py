"""Export the trained verifier to ONNX and check it against PyTorch with ONNX Runtime."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def export(model, path: str | Path, check: bool = True) -> None:
    """Export with dynamic batch/height/width (full-frame tiling and ROI batches)."""
    import torch

    model.eval()
    dummy = torch.zeros(2, 1, 64, 64)
    torch.onnx.export(
        model, dummy, str(path), input_names=["input"], output_names=["score", "heatmap", "offset"],
        dynamic_axes={"input": {0: "n"}, "score": {0: "n"}, "heatmap": {0: "n"},
                      "offset": {0: "n"}},
        opset_version=17, dynamo=False)
    if check:
        import onnxruntime as ort

        x = np.random.default_rng(0).normal(size=(3, 1, 64, 64)).astype(np.float32)
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        got = sess.run(None, {"input": x})
        with torch.no_grad():
            ref = [t.numpy() for t in model(torch.from_numpy(x))]
        for a, b in zip(got, ref):
            if not np.allclose(a, b, atol=1e-4):
                raise RuntimeError("ONNX export mismatch")
