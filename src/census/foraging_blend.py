"""Validated, non-programmer-facing controls for colour-basemap reveals."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BlendSettings:
    radius_meters: float = 1400
    opacity: float = 0.45
    fade_steepness: float = 2
    solid_core: float = 0
    saturation: float = 0.75
    brightness: float = 1.03
    contrast: float = 0.92
    radius_scaling: str = "linear"
    radius_at_3_5: float | None = None
    radius_at_7: float | None = None


def load_blend_settings(
    config: object, alpha: float, radius_meters: float,
) -> BlendSettings:
    """Use legacy reveal settings as fallbacks; reject typos and unsafe values."""
    if not isinstance(config, dict):
        raise ValueError("blend must be a YAML mapping")
    defaults = BlendSettings(opacity=alpha, radius_meters=radius_meters)
    ranges = {
        "radius_meters": (1, 10000), "opacity": (0, 1),
        "fade_steepness": (0.1, 20), "solid_core": (0, 0.99),
        "saturation": (0, 3), "brightness": (0, 3), "contrast": (0, 3),
    }
    unknown = config.keys() - ranges.keys() - {
        "radius_scaling", "radius_at_3.5", "radius_at_7",
    }
    if unknown:
        raise ValueError(f"Unknown blend settings: {list(unknown)}")
    values = {}
    for key, (lower, upper) in ranges.items():
        value = config.get(key, getattr(defaults, key))
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError(f"blend.{key} must be a number from {lower} to {upper}")
        values[key] = float(value)
    scaling = config.get("radius_scaling", "linear")
    if scaling not in ("linear", "exponential"):
        raise ValueError("blend.radius_scaling must be linear or exponential")
    anchors = {}
    for key, default in (("radius_at_3.5", values["radius_meters"] * 5 / 12),
                         ("radius_at_7", values["radius_meters"])):
        value = config.get(key, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 1 <= value <= 10000):
            raise ValueError(f"blend.{key} must be a number from 1 to 10000")
        anchors[key] = float(value)
    if anchors["radius_at_7"] < anchors["radius_at_3.5"]:
        raise ValueError("blend.radius_at_7 must be >= blend.radius_at_3.5")
    if scaling == "exponential" and anchors["radius_at_7"] == anchors["radius_at_3.5"]:
        raise ValueError("Exponential scaling requires radius_at_7 > radius_at_3.5")
    return BlendSettings(
        **values, radius_scaling=scaling,
        radius_at_3_5=anchors["radius_at_3.5"], radius_at_7=anchors["radius_at_7"],
    )


BLEND_RADIUS_SCRIPT = """
            const anchorScore = (3.5 - 1) / 6;
            const midpoint = blendStyle.radius_at_3_5 == null
                ? blendStyle.radius_meters * anchorScore : blendStyle.radius_at_3_5;
            const maximum = blendStyle.radius_at_7 == null
                ? blendStyle.radius_meters : blendStyle.radius_at_7;
            let radiusMeters = midpoint
                + (score - anchorScore) / (1 - anchorScore) * (maximum - midpoint);
            if (blendStyle.radius_scaling === 'exponential') {
                // r(s) = maximum * expm1(k*s) / expm1(k).
                // Fit k numerically at raw 3.5 (normalized 5/12).
                const fraction = (k, s) => Math.abs(k) < 1e-10 ? s
                    : k > 0
                        ? Math.exp(k * (s - 1)) * Math.expm1(-k * s) / Math.expm1(-k)
                        : Math.expm1(k * s) / Math.expm1(k);
                let lower = -1024, upper = 1024;
                for (let iteration = 0; iteration < 64; iteration++) {
                    const k = (lower + upper) / 2;
                    if (fraction(k, anchorScore) > midpoint / maximum) lower = k;
                    else upper = k;
                }
                radiusMeters = maximum * fraction((lower + upper) / 2, score);
            }
            const radius = (score <= 0 ? 0 : Math.max(0, radiusMeters)) / metresPerPixel;
"""


BLEND_GRADIENT_SCRIPT = """
            const gradient = mask.createRadialGradient(x, y, 0, x, y, radius);
            gradient.addColorStop(0, 'rgba(255,255,255,' + opacity + ')');
            for (let step = 0; step <= 64; step++) {
                const fraction = step / 64;
                const position = blendStyle.solid_core
                    + fraction * (1 - blendStyle.solid_core);
                const fadedOpacity = opacity * Math.pow(1 - fraction, blendStyle.fade_steepness);
                gradient.addColorStop(position, 'rgba(255,255,255,' + fadedOpacity + ')');
            }
"""
