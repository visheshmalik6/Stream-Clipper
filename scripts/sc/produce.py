"""Build one finished clip: fetch its video, sync it to the stream audio, caption it,
frame it 9:16, put the title bar on, encode, and save a check image."""

import subprocess
from functools import lru_cache

import numpy as np

from . import frame, hook, listen, media, sfx, subs, titlecard
from .common import Problem, decode, probe, run, say, slug

PAD = 5.0          # extra seconds fetched on each side; trimmed after syncing
ENV_RATE = 100     # envelope samples per second used for syncing


def _envelope(samples, rate=8000):
    hop = rate // ENV_RATE
    n = len(samples) // hop
    if not n:
        return np.zeros(0, np.float32)
    e = np.log(np.sqrt(np.mean(samples[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-4)
    k = ENV_RATE                                   # remove the slow trend (1 s mean)
    trend = np.convolve(np.pad(e, k // 2, mode="edge"), np.ones(k) / k, mode="valid")[: len(e)]
    return (e - trend).astype(np.float32)


def sync(part, audio, guess, reach=25.0):
    """Stream time of the part's first frame, by matching its sound to the stream audio.
    Returns (seconds, confidence 0-1)."""
    probe_len = 20.0
    a = _envelope(decode(part, 8000, 0.5, probe_len))
    lo = max(0.0, guess + 0.5 - reach)
    b = _envelope(decode(audio, 8000, lo, probe_len + 2 * reach))
    if len(a) < ENV_RATE * 5 or len(b) <= len(a):
        return guess, 0.0
    a = (a - a.mean()) / (a.std() + 1e-6)
    win = np.lib.stride_tricks.sliding_window_view(b, len(a))
    mu, sd = win.mean(axis=1), win.std(axis=1) + 1e-6
    score = (win @ a - mu * a.sum()) / (len(a) * sd)
    k = int(np.argmax(score))
    return lo + k / ENV_RATE - 0.5, float(score[k])


@lru_cache(maxsize=1)
def video_encoder(fast):
    """libx264, or a hardware encoder that actually works on this machine when fast=True."""
    if not fast:
        return "libx264"
    for enc in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"):
        test = ["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                "color=c=black:s=256x256:d=0.2", "-c:v", enc, "-f", "null", "-"]
        if subprocess.run(test, capture_output=True).returncode == 0:
            return enc
    return "libx264"


def _encode_args(enc, cfg):
    if enc == "libx264":
        return ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["x264_preset"],
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", enc, "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M", "-pix_fmt", "yuv420p"]


def check_image(clip, length, dest):
    """Three frames side by side, so a person (or an agent that can see images) can check
    the framing, the title and the captions without playing the video."""
    from PIL import Image
    shots = []
    for i, f in enumerate((0.2, 0.5, 0.8)):
        tmp = dest.with_name(dest.stem + f"_{i}.jpg")
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{length * f:.2f}", "-i", str(clip),
             "-frames:v", "1", "-vf", "scale=360:-2", str(tmp)])
        with Image.open(tmp) as im:
            shots.append(im.convert("RGB"))
        tmp.unlink(missing_ok=True)
    sheet = Image.new("RGB", (sum(s.width for s in shots) + 20, shots[0].height), (20, 20, 20))
    x = 0
    for s in shots:
        sheet.paste(s, (x, 0))
        x += s.width + 10
    sheet.save(dest, quality=85)
    return dest


def make(index, pick, ctx, cfg, memory):
    """ctx: url, args, audio, work, outdir, language, fast, cam. Returns the clip record."""
    start, end = pick["start"], pick["end"]
    length = end - start
    name = f"{index:02d}_{slug(pick.get('title') or pick.get('type'), 48)}"
    say(f"clip {index}: {pick.get('title') or pick.get('type')}  ({length:.0f}s at "
        f"{int(start // 3600)}:{int(start // 60 % 60):02d}:{int(start % 60):02d})", "step")
    clips_dir = ctx["work"] / "clips"
    clips_dir.mkdir(exist_ok=True)
    part = media.video_slice(ctx["url"], ctx["args"], start - PAD, end + PAD,
                             clips_dir / f"{name}.src.mp4", cfg["video_height"])
    info = probe(part)
    if not info["width"]:
        raise Problem("the downloaded video has no picture")

    at, conf = sync(part, ctx["audio"], start - PAD)
    offset = start - at if conf >= 0.45 else min(PAD, max(0.0, start))
    offset = min(max(0.0, offset), max(0.0, info["duration"] - length))
    if conf < 0.45:
        say(f"  weak sound match ({conf:.2f}); using the requested times, may be off by ~1 s", "warn")

    cfg = hook.sanitize(cfg)
    samples = decode(part, 16000, offset, length)
    words, _ = listen.transcribe(cfg["caption_model"], samples, ctx["language"])

    # opening + sound effects (each step is optional and falls back to the plain render)
    trim, accents = 0.0, []
    try:
        if cfg["sfx"] and cfg["sfx_accents"] and pick.get("type") in cfg["sfx_accent_types"]:
            accents = sfx.find_accents(samples, 16000, words, length, cfg["sfx_accents"])
        if cfg["hook"]:
            offset, length, words, trim = hook.trim_lead(words, offset, length, cfg)
            if trim:
                say(f"  opening: trimmed {trim:.1f}s of dead air before the first word")
        accents = [a - trim for a in accents if a - trim >= 2.0]
    except Exception as exc:  # noqa: BLE001 - never lose a clip to an optional extra
        say(f"  opening/sfx analysis skipped ({str(exc)[:120]})", "warn")
        trim, accents = 0.0, []
    samples = None

    ass = subs.write(words, length, clips_dir / f"{name}.ass", cfg)
    graph, look, seam = frame.plan(part, offset, length, info, cfg, memory, ctx.get("cam"))
    title = pick.get("title")
    title_png = None
    if title:
        try:
            title_png = titlecard.render(title, cfg, clips_dir / f"{name}.title.png")
        except (OSError, ValueError) as exc:
            say(f"  title bar skipped ({exc})", "warn")

    def assemble(extras):
        """(ffmpeg inputs, filter chain, video label). extras=False is the plain render."""
        inputs = ["-ss", f"{offset:.3f}", "-t", f"{length:.3f}", "-i", str(part)]
        n_in = 1
        chain = graph
        label = "framed"
        zoom_on = extras and (cfg["hook"] or (accents and cfg["hook_accent_zoom"] > 0))
        if zoom_on:
            zcfg = dict(cfg, hook_zoom=cfg["hook_zoom"] if cfg["hook"] else 0.0)
            chain += ";" + hook.zoom_filter(zcfg, accents if cfg["hook_accent_zoom"] > 0 else ())
            label = "zoomed"
        chain += f";[{label}]ass={ass.name}[subbed]"
        out_label = "subbed"
        if title_png:
            png, _, th = title_png
            y = max(0, int(seam - th / 2) if seam else int(cfg["height"] * cfg["title_top"]))
            inputs += ["-i", str(png)]
            n_in += 1
            ypos = (f"'{hook.title_y_expression(y, th, cfg)}'"
                    if extras and cfg["hook"] and cfg["hook_title_anim"] else str(y))
            chain += f";[subbed][{n_in - 1}:v]overlay=(W-w)/2:{ypos}[titled]"
            out_label = "titled"
        base = (f"loudnorm=I={cfg['loudness']}:TP=-1.5:LRA=11,aresample=48000"
                if cfg["loudness"] is not None else "aresample=48000")
        items = sfx.plan(pick, cfg, length, accents) if extras and cfg["sfx"] else []
        if extras and cfg["hook"]:
            base += ",afade=t=in:st=0:d=0.03"           # no click if the cut lands mid-sound
        if items:
            files = sfx.library()
            names = sorted({n for n, _, _ in items})
            index = {}
            for nme in names:
                inputs += ["-i", str(files[nme])]
                index[nme] = n_in
                n_in += 1
            chain += f";[0:a]{base}[aud0];" + sfx.mix_graph(items, index, cfg)
        else:
            chain += f";[0:a]{base}[aud]"
        used["sfx"] = [{"sound": n, "at": round(t, 2)} for n, t, _ in items]
        used["zoom"] = bool(zoom_on)
        used["title_anim"] = bool(extras and cfg["hook"] and cfg["hook_title_anim"] and title_png)
        return inputs, chain, out_label

    ctx["outdir"].mkdir(parents=True, exist_ok=True)
    dest = ctx["outdir"] / f"{name}.mp4"
    enc = video_encoder(ctx.get("fast", False))
    used = {}

    def render(extras):
        inputs, chain, out_label = assemble(extras)
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", *inputs, "-filter_complex", chain,
             "-map", f"[{out_label}]", "-map", "[aud]", *_encode_args(enc, cfg),
             "-r", f"{min(60.0, info['fps']):.3f}", "-c:a", "aac", "-b:a", f"{cfg['audio_kbps']}k",
             "-movflags", "+faststart", dest.name], timeout=3600, cwd=str(clips_dir))

    wants_extras = cfg["hook"] or cfg["sfx"]
    try:
        render(wants_extras)
    except Problem as exc:
        if not wants_extras:
            raise
        say(f"  opening/sfx render failed ({str(exc)[:160]}); making the plain clip instead", "warn")
        render(False)
    # ffmpeg ran inside clips_dir (so the .ass path needs no escaping); move the result out
    produced = clips_dir / dest.name
    produced.replace(dest)
    checks = ctx["outdir"] / "checks"
    checks.mkdir(exist_ok=True)
    try:
        check_image(dest, length, checks / f"{name}.jpg")
    except Problem:
        pass
    part.unlink(missing_ok=True)
    say(f"  saved {dest.name} ({look})", "good")
    return {"file": dest.name, "type": pick.get("type"), "title": title,
            "caption": pick.get("caption"), "hashtags": pick.get("hashtags", []),
            "score": pick.get("score"), "why": pick.get("why"), "look": look,
            "start": round(start + trim, 1), "end": round(end, 1), "seconds": round(length, 1),
            "sync": round(conf, 2),
            "opening": {"trimmed_s": round(trim, 2), "punch_in": used.get("zoom", False),
                        "title_slide": used.get("title_anim", False)},
            "sfx": used.get("sfx", [])}
