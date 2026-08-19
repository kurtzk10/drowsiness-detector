import cv2
import numpy as np
from config import IR_CONTRAST, IR_GAMMA, IR_VIGNETTE, IR_NOISE


# ── Precomputed, reused across frames (keeps the filter real-time) ──────

# Gamma LUT: near-IR reflects strongly off skin, so faces look pale and
# skin tone flattens. A midtone lift approximates that luminous look.
_GAMMA_LUT = None
if IR_GAMMA and IR_GAMMA != 1.0:
    _GAMMA_LUT = np.array(
        [((i / 255.0) ** (1.0 / IR_GAMMA)) * 255 for i in range(256)],
        dtype=np.uint8,
    )

# ISP-style local contrast (what many IR camera modules apply internally).
_CLAHE = (cv2.createCLAHE(clipLimit=IR_CONTRAST, tileGridSize=(8, 8))
          if IR_CONTRAST > 0 else None)

# Vignette masks depend on frame size, so build lazily and cache per shape.
_vignette_cache = {}


def _vignette_mask(h, w):
    mask = _vignette_cache.get((h, w))
    if mask is None:
        kx = cv2.getGaussianKernel(w, w * 0.5)
        ky = cv2.getGaussianKernel(h, h * 0.5)
        g = ky @ kx.T
        g /= g.max()                       # 1.0 at center → ~0 at corners
        mask = (1.0 - IR_VIGNETTE * (1.0 - g)).astype(np.float32)
        _vignette_cache[(h, w)] = mask
    return mask


def apply_ir_filter(frame):
    """
    Simulate a monochrome active-IR / night-vision camera feed.

    Reproduces the traits that actually challenge detection in the dark —
    grayscale, pale-skin midtones, an IR-illuminator hotspot, and low-light
    sensor noise — so the pipeline is validated against realistic IR input
    before a real IR camera is swapped in. Returns a 3-channel BGR image so
    the rest of the pipeline is unchanged. Applied BEFORE detection.

    Each stage is independently tunable in config.py (set any to 0 to skip).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Pale, flat skin under near-IR
    if _GAMMA_LUT is not None:
        gray = cv2.LUT(gray, _GAMMA_LUT)

    # ISP-style local contrast
    if _CLAHE is not None:
        gray = _CLAHE.apply(gray)

    # IR-illuminator hotspot (bright center, dark edges)
    if IR_VIGNETTE > 0:
        gray = (gray * _vignette_mask(*gray.shape)).astype(np.uint8)

    # Low-light sensor noise — the realistic robustness test
    if IR_NOISE > 0:
        noise = np.random.normal(0.0, IR_NOISE, gray.shape).astype(np.float32)
        gray = np.clip(gray.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
