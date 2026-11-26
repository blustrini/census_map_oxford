"""Canvas renderer and legend for category-coloured foraging circles."""

from collections.abc import Mapping
from html import escape
from dataclasses import dataclass, field
import math
import re


@dataclass(frozen=True)
class CircleSettings:
    min_radius_meters: float = 280
    max_radius_meters: float = 840
    opacity: float = 0.45
    fade_steepness: float = 3
    solid_core: float = 0
    category_colors: Mapping[str, str] = field(default_factory=dict)


def load_circle_settings(config: object, default_colors: Mapping[str, str]) -> CircleSettings:
    """Validate optional styling, allowing partial palette overrides."""
    if not isinstance(config, dict):
        raise ValueError("circles must be a YAML mapping")
    defaults = CircleSettings()
    numeric_ranges = {
        "min_radius_meters": (0, 10000),
        "max_radius_meters": (0, 10000),
        "opacity": (0, 1),
        "fade_steepness": (0.1, 20),
        "solid_core": (0, 0.99),
    }
    if config.keys() - (numeric_ranges.keys() | {"category_colors"}):
        raise ValueError("Unknown circles settings: " + str(list(
            config.keys() - (numeric_ranges.keys() | {"category_colors"})
        )))
    values = {}
    for key, (lower, upper) in numeric_ranges.items():
        value = config.get(key, getattr(defaults, key))
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError(f"circles.{key} must be a number from {lower} to {upper}")
        values[key] = float(value)
    if values["max_radius_meters"] <= 0:
        raise ValueError("circles.max_radius_meters must be greater than zero")
    if values["min_radius_meters"] > values["max_radius_meters"]:
        raise ValueError("circles.min_radius_meters must not exceed max_radius_meters")
    colors = config.get("category_colors", {})
    if not isinstance(colors, dict):
        raise ValueError("circles.category_colors must map categories to quoted hex colours")
    for category, color in colors.items():
        if category not in default_colors:
            raise ValueError(
                f"Unknown circles.category_colors category: {category!r}. "
                "Colour names must match categories defined in knowledge_scores. "
                f"Configured categories: {sorted(default_colors)}. "
                "Rename/remove this colour entry, or add the category to every "
                "knowledge_scores age bracket and use the same name in the CSV layer column. "
                "Colour entries may be omitted to use default colours."
            )
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError(f"Colour for {category!r} must be a quoted hex colour like '#80718c'")
    return CircleSettings(**values, category_colors={**default_colors, **colors})


def circle_legend(colors: Mapping[str, str], settings: CircleSettings) -> str:
    """Describe the radius encoding and show the shared category palette."""
    entries = "".join(
        f"<div><span style='display:inline-block;width:10px;height:10px;"
        f"border-radius:50%;background:{color};margin-right:6px;'></span>"
        f"{escape(category)}</div>"
        for category, color in colors.items()
    )
    return (
        "<strong>Foraging knowledge</strong>"
        + entries
        + f"<div style='color:#555;margin-top:4px;'>Circle radius: {settings.min_radius_meters:g}–"
        f"{settings.max_radius_meters:g} metres, scaled by age/category knowledge score. "
        "Zero scores are hidden. Colour fades to transparent at the edge.</div>"
    )


# Uses the canvas, selected categories and geographic projection supplied by the
# shared foraging renderer. Knowledge controls radius, not alpha, in both modes.
CIRCLE_DRAW_SCRIPT = """
        for (const layer of selectedCategories) {
            const score = knowledgeScores[age][layer];
            if (score <= 0) continue;
            const color = categoryColors[layer];
            for (const [latitude, longitude] of locationsByCategory[layer]) {
                const point = foragingMap.latLngToContainerPoint([latitude, longitude]);
                const metresPerPixel = Math.cos(latitude * Math.PI / 180)
                    * 2 * Math.PI * 6378137 / (256 * Math.pow(2, foragingMap.getZoom()));
                const radius = (circleStyle.min_radius_meters
                    + score * (circleStyle.max_radius_meters - circleStyle.min_radius_meters))
                    / metresPerPixel;
                if (radius <= 0 || !Number.isFinite(radius)) continue;
                const gradient = ctx.createRadialGradient(
                    point.x, point.y, 0, point.x, point.y, radius
                );
                gradient.addColorStop(0, color);
                for (let step = 0; step <= 64; step++) {
                    const fraction = step / 64;
                    const position = circleStyle.solid_core
                        + fraction * (1 - circleStyle.solid_core);
                    const alpha = Math.round(255 * Math.pow(1 - fraction, circleStyle.fade_steepness));
                    gradient.addColorStop(position, color + alpha.toString(16).padStart(2, '0'));
                }
                ctx.globalAlpha = circleStyle.opacity;
                ctx.fillStyle = gradient;
                ctx.fillRect(point.x - radius, point.y - radius, radius * 2, radius * 2);
            }
        }
        ctx.globalAlpha = 1;
"""
