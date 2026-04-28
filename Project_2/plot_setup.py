def setup_chinese_font():
    """
    Configure matplotlib to render Chinese characters in plot labels.
    Call once at the top of a notebook before plotting.
    """
    import matplotlib
    import matplotlib.font_manager as fm

    # Candidate fonts, in order of preference. Mac first, Windows second, Linux third.
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

    print(f"Warning: no Chinese font found. Tried: {candidates}")
    return None