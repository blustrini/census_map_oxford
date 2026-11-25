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
    unknown = config.keys() - ranges.keys()
    if unknown:
        raise ValueError(f"Unknown blend settings: {list(unknown)}")
    values = {}
    for key, (lower, upper) in ranges.items():
        value = config.get(key, getattr(defaults, key))
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError(f"blend.{key} must be a number from {lower} to {upper}")
        values[key] = float(value)
    return BlendSettings(**values)


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
