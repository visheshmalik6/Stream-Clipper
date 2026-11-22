"""The first seconds of a clip: what makes a viewer stay.

Three things, all built from the clip's own footage (nothing is invented, nothing outside the
picked section is used):

  1. Tighter start    Dead air before the first spoken word is trimmed, leaving a short
                      breath, so the clip opens on speech instead of a pause. Only time inside
                      the picked section is removed, and never more than `hook_max_trim` s.
  2. Punch-in         The frame starts slightly zoomed in and eases out to normal in about
                      0.7 s, landing together with the impact sound. A second, smaller pop can
                      be added on a real loud moment (see sfx.find_accents).
  3. Title slide-in   The title bar drops in from the top and settles, instead of being
                      there from frame one. Its text is the clip's title, as before.

Each part can be switched off in settings.json (`hook`, `hook_trim_lead`, `hook_title_anim`).
With `"hook": false` the render is exactly what earlier versions produced.
"""


def trim_lead(words, offset, length, cfg):
    """Cut dead air before the first word. `words` are in clip time (0 = first frame of the
    clip). Returns (offset, length, words, trimmed_seconds); everything unchanged if there is
    nothing worth trimming."""
    if not cfg.get("hook_trim_lead") or not words:
        return offset, length, words, 0.0
    first = float(words[0]["s"])
    trim = min(first - float(cfg["hook_lead_keep"]), float(cfg["hook_max_trim"]))
    shortest = float(cfg.get("min_len") or 0)
    trim = min(trim, length - max(shortest, 5.0))        # never drop below the minimum length
    if trim < 0.35:                                      # not worth a visible jump
        return offset, length, words, 0.0
    moved = [{**w, "s": round(w["s"] - trim, 2), "e": round(w["e"] - trim, 2)} for w in words]
    return offset + trim, length - trim, moved, trim


def zoom_expression(cfg, accents=()):
    """Zoom factor as an ffmpeg expression of time `t` (1.0 = no zoom)."""
    amp = float(cfg["hook_zoom"])
    secs = max(0.2, float(cfg["hook_zoom_secs"]))
    terms = [f"{amp:.4f}*pow(max(0,1-t/{secs:.3f}),2)"]
    pop = float(cfg["hook_accent_zoom"])
    for when in accents:
        # a quick push that eases back; the gte() keeps it silent before its moment
        terms.append(f"{pop:.4f}*pow(max(0,1-(t-{when:.3f})/0.350),2)*gte(t,{when:.3f})")
    return "1+" + "+".join(terms)


def zoom_filter(cfg, accents=(), src="framed", dst="zoomed"):
    """Filter text turning [src] into [dst]: the frame scaled up by the zoom expression and
    cropped back to its own size, centred. Dimensions stay even for yuv420p."""
    z = zoom_expression(cfg, accents)
    return (f"[{src}]scale=w='trunc(iw*({z})/2)*2':h='trunc(ih*({z})/2)*2':eval=frame:"
            f"flags=bicubic,crop=w={cfg['width']}:h={cfg['height']},setsar=1[{dst}]")


def title_y_expression(final_y, box_h, cfg):
    """y of the title bar over time: starts above the frame, glides down with an ease-out
    curve and stops at `final_y`."""
    start = float(cfg["hook_title_delay"])
    secs = max(0.1, float(cfg["hook_title_secs"]))
    p = f"clip((t-{start:.3f})/{secs:.3f},0,1)"
    return f"{-box_h - 8}+({final_y + box_h + 8})*(1-pow(1-{p},3))"


def sanitize(cfg):
    """A copy of cfg with the hook/sfx numbers kept in a safe range, so a typo in
    settings.json cannot produce a wild zoom or a deafening effect."""
    out = dict(cfg)

    from .settings import DEFAULTS
    from .common import say

    def clamp(key, lo, hi):
        try:
            out[key] = min(hi, max(lo, float(out[key])))
        except (TypeError, ValueError):
            say(f"setting '{key}' must be a number; using {DEFAULTS[key]}", "warn")
            out[key] = DEFAULTS[key]

    clamp("hook_zoom", 0.0, 0.30)
    clamp("hook_zoom_secs", 0.2, 2.0)
    clamp("hook_lead_keep", 0.0, 1.0)
    clamp("hook_max_trim", 0.0, 4.0)
    clamp("hook_title_delay", 0.0, 1.5)
    clamp("hook_title_secs", 0.1, 1.0)
    clamp("hook_accent_zoom", 0.0, 0.15)
    clamp("sfx_volume", 0.0, 1.0)
    try:
        out["sfx_accents"] = max(0, min(3, int(out.get("sfx_accents") or 0)))
    except (TypeError, ValueError):
        out["sfx_accents"] = DEFAULTS["sfx_accents"]
    if not isinstance(out.get("sfx_accent_types"), (list, tuple)):
        out["sfx_accent_types"] = DEFAULTS["sfx_accent_types"]
    return out
