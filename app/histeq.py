"""
Histogram equalization of the luminance channel (same algorithm as lab 1,
https://github.com/ukurere/parcs-histogram-equalization, here vectorised with numpy).

RGB -> YCbCr, equalize Y with lut[v] = round((cdf[v]-cdf_min)/(N-cdf_min)*255),
keep Cb/Cr, convert back to RGB.
"""
import numpy as np
from PIL import Image


def build_lut(hist: np.ndarray) -> np.ndarray:
    cdf = hist.cumsum()
    nonzero = cdf[cdf > 0]
    cdf_min = int(nonzero[0]) if nonzero.size else 0
    total = int(cdf[-1])
    if total == cdf_min:
        return np.arange(256, dtype=np.uint8)
    lut = np.round((cdf - cdf_min) / (total - cdf_min) * 255)
    return np.clip(lut, 0, 255).astype(np.uint8)


def equalize(img: Image.Image) -> tuple[Image.Image, dict]:
    """Return (equalized RGB image, stats with before/after histograms of Y)."""
    ycc = np.asarray(img.convert("RGB").convert("YCbCr")).copy()
    y = ycc[..., 0].copy()  # copy: ycc[..., 0] is overwritten below
    hist_before = np.bincount(y.ravel(), minlength=256)
    lut = build_lut(hist_before)
    ycc[..., 0] = lut[y]
    hist_after = np.bincount(ycc[..., 0].ravel(), minlength=256)
    out = Image.fromarray(ycc, "YCbCr").convert("RGB")
    # 1st..99th percentile: robust "contrast range", ignores single JPEG-artifact pixels
    stats = {
        "y_range_before": [int(v) for v in np.percentile(y, [1, 99])],
        "y_range_after": [int(v) for v in np.percentile(ycc[..., 0], [1, 99])],
        "hist_before": hist_before.tolist(),
        "hist_after": hist_after.tolist(),
    }
    return out, stats
