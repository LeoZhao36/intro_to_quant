"""
plot_setup.py

Matplotlib configuration helper for rendering Chinese characters.
"""

import warnings
import matplotlib
import matplotlib.font_manager as fm


def setup_chinese_font():
    """
    Configure matplotlib to render Chinese characters in plot labels.

    Call once near the top of a notebook before plotting. Mutates
    matplotlib rcParams as a side effect.

    Returns
    -------
    str or None
        Name of the font that was set, or None if no suitable font was
        found on the system. When None, Chinese characters will render
        as empty boxes and a RuntimeWarning is emitted.
    """
    candidates = [
        "Heiti SC", "Songti SC", "PingFang SC",              # macOS
        "Microsoft YaHei", "SimHei", "SimSun",                # Windows
        "Noto Sans CJK SC", "WenQuanYi Zen Hei",              # Linux
    ]

    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams["font.sans-serif"] = [font]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return font

    warnings.warn(
        f"No Chinese font found on this system. Tried: {candidates}. "
        "Chinese characters will render as boxes.",
        RuntimeWarning,
    )
    return None