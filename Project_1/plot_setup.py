"""
Matplotlib configuration for Chinese character rendering.
Import this once at the top of any notebook that plots Chinese text.

Usage:
    from plot_setup import setup_chinese_font
    setup_chinese_font()
"""
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


def setup_chinese_font():
    """Configure matplotlib to render Chinese characters on Windows/Mac/Linux."""
    # Candidate fonts in order of preference
    candidates = [
        'Microsoft YaHei',    # Windows, most readable
        'SimHei',             # Windows fallback
        'PingFang SC',        # Mac
        'Heiti SC',           # Mac fallback
        'Noto Sans CJK SC',   # Linux
        'WenQuanYi Zen Hei',  # Linux fallback
    ]
    
    # Find the first font that is actually installed
    available = {f.name for f in fm.fontManager.ttflist}
    chosen = next((c for c in candidates if c in available), None)
    
    if chosen is None:
        print("Warning: no CJK font found. Chinese characters will not render.")
        return None
    
    plt.rcParams['font.sans-serif'] = [chosen, 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False  # render minus signs correctly
    print(f"Chinese font set to: {chosen}")
    return chosen