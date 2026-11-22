"""Sound effects, synthesized locally (numpy + the stdlib `wave` module).

Nothing is downloaded and nothing is licensed: every sound is generated from noise and
sine sweeps with a fixed random seed, so the same settings always give the same files.
The library is written once to `<cache>/sfx/` and reused by every clip.

    whoosh   a filtered-noise sweep that rises and falls (text slide-in, opening)
    impact   a low sine drop with a soft click on top (the title landing, accents)
    hit      a shorter, lighter impact (emphasis on a loud moment)
    tick     a tiny pop (small emphasis)

All sounds are mono, 48 kHz, peak-normalised to between -4 and -2 dBFS. Their loudness
in the clip is set later by `sfx_volume`, and they are mixed *under* the original audio.
"""

import wave

import numpy as np

from .common import CACHE

RATE = 48000
VERSION = 3          # bump when a sound changes, so cached files are rebuilt


def _t(seconds):
    return np.arange(int(seconds * RATE)) / RATE


def _norm(x, peak=0.7):
    top = float(np.max(np.abs(x))) or 1.0
    return (x / top * peak).astype(np.float32)


def _fade(x, fade_in=0.004, fade_out=0.02):
    n = len(x)
    a, b = min(n, int(fade_in * RATE)), min(n, int(fade_out * RATE))
    if a:
        x[:a] *= np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)
    return x


def _lowpass(x, cutoff):
    """One-pole low-pass with a per-sample cutoff (Hz, array or scalar)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, np.float64), x.shape)
    k = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += k[i] * (x[i] - acc)
        y[i] = acc
    return y


def _bandpass_sweep(x, centre, damping=0.28):
    """State-variable band-pass whose centre frequency (Hz, per sample) can move."""
    f = 2 * np.sin(np.pi * np.minimum(np.asarray(centre, np.float64), RATE / 6) / RATE)
    low = band = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        high = x[i] - low - damping * band
        band += f[i] * high
        low += f[i] * band
        y[i] = band
    return y


def whoosh(seconds=0.55, rng=None):
    """A rising air sweep: a resonant band of noise climbs from ~350 Hz to ~4 kHz and
    peaks at 65% of its length, so it arrives together with the impact that follows."""
    rng = rng or np.random.default_rng(7)
    t = _t(seconds)
    p = t / seconds
    peak = 0.65
    noise = rng.standard_normal(len(t))
    centre = 350 * (4000 / 350) ** np.clip(p / peak, 0, 1.3)
    band = _bandpass_sweep(noise, centre)
    air = noise - _lowpass(noise, 2500)                      # a little un-pitched top end
    env = np.where(p < peak, (p / peak) ** 2.0,
                   np.cos(0.5 * np.pi * np.clip((p - peak) / (1 - peak), 0, 1)) ** 2)
    body = (band / (np.std(band) + 1e-9) + 0.06 * air / (np.std(air) + 1e-9)) * env
    body = _lowpass(body, 6500)                              # no harsh hiss
    body = body - _lowpass(body, 140)                        # nothing below speech's range
    return _norm(_fade(body), 0.65)


def impact(seconds=0.9, rng=None):
    """A sub-bass drop plus a short low-passed click: weight without harshness."""
    rng = rng or np.random.default_rng(11)
    t = _t(seconds)
    freq = 38 + 95 * np.exp(-t * 14)                        # 133 Hz falling to ~38 Hz
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    thump = np.sin(phase) * np.exp(-t * 5.2)
    click = _lowpass(rng.standard_normal(len(t)), 2400) * np.exp(-t * 55) * 0.55
    mid = np.sin(2 * np.pi * 70 * t) * np.exp(-t * 9) * 0.35
    return _norm(_fade(thump + click + mid, 0.002, 0.08), 0.8)


def hit(seconds=0.42, rng=None):
    """A light accent: a shorter, higher thump with a faint air tail."""
    rng = rng or np.random.default_rng(23)
    t = _t(seconds)
    freq = 55 + 150 * np.exp(-t * 22)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    thump = np.sin(phase) * np.exp(-t * 9)
    air = _lowpass(rng.standard_normal(len(t)), 3200) * np.exp(-t * 26) * 0.35
    return _norm(_fade(thump + air, 0.002, 0.05), 0.7)


def tick(seconds=0.12):
    t = _t(seconds)
    pop = np.sin(2 * np.pi * (900 + 500 * np.exp(-t * 60)) * t) * np.exp(-t * 55)
    return _norm(_fade(pop, 0.001, 0.02), 0.5)


BUILDERS = {"whoosh": whoosh, "impact": impact, "hit": hit, "tick": tick}


def _write(path, samples):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm.tobytes())


def library(folder=None):
    """Make (once) and return {name: path} for every sound. Safe to call from many threads."""
    folder = folder or (CACHE / "sfx")
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, build in BUILDERS.items():
        path = folder / f"{name}.v{VERSION}.wav"
        if not path.exists() or path.stat().st_size < 1000:
            tmp = path.with_name(f"{path.stem}.{id(path)}.tmp")
            _write(tmp, build())
            tmp.replace(path)
        out[name] = path
    return out


# ---------------------------------------------------------------- what goes where

def find_accents(samples, rate, words, length, count, lead=4.0, tail=2.0):
    """Moments in the clip where the audio itself jumps in volume (a shout, a laugh, an
    explosion). Returns up to `count` times in seconds. Uses only the clip's real audio, so
    an accent is never placed on something that did not happen.

    `samples` is the clip's mono audio at `rate` Hz, starting at clip time 0."""
    if count <= 0 or len(samples) < rate * 8:
        return []
    hop = rate // 10                                         # 100 ms frames
    n = len(samples) // hop
    frames = samples[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-5)
    # compare each 0.3 s with the 3 s before it: a real jump, not just a loud passage
    short = np.convolve(db, np.ones(3) / 3, mode="same")
    base = np.array([np.median(db[max(0, i - 30):max(1, i - 2)]) if i > 3 else np.median(db[:10])
                     for i in range(n)])
    jump = short - base
    floor = np.percentile(db, 60)                            # must also be in the loud part
    picks = []
    for i in np.argsort(-jump):
        when = i / 10.0
        if jump[i] < 8.0 or db[i] < floor:                   # needs a clear +8 dB jump
            break
        # the loudest frame is mid-shout: walk back to where the sound actually starts, so the
        # hit lands with the onset instead of a beat late
        j = i
        while j > 0 and i - j < 8 and db[j - 1] >= base[i] + 0.4 * jump[i]:
            j -= 1
        when = j / 10.0
        if when < lead or when > length - tail:
            continue
        if any(abs(when - p) < 5.0 for p in picks):          # keep accents well apart
            continue
        picks.append(when)
        if len(picks) >= count:
            break
    return sorted(float(p) for p in picks)


def plan(pick, cfg, length, accents):
    """The list of sounds for one clip: [(name, clip_time, gain)]. Gains are relative; the
    overall level comes from cfg['sfx_volume'] when mixing.

    Restrained on purpose: a whoosh into the title and one impact as it lands, then at most
    `sfx_accents` soft hits on real volume jumps."""
    items = []
    if cfg.get("hook"):
        land = cfg["hook_title_delay"] + cfg["hook_title_secs"]
        items.append(("whoosh", max(0.0, cfg["hook_title_delay"] - 0.12), 0.8))
        items.append(("impact", land - 0.02, 1.0))
    for when in accents:
        items.append(("hit", when - 0.03, 0.8))
    return [(n, t, g) for n, t, g in items if 0 <= t < length - 0.2]


def mix_graph(items, sfx_inputs, cfg, loud_label="aud0", out_label="aud"):
    """ffmpeg filter pieces that lay the sounds *under* the dialogue.

    items       [(name, clip_time, gain)]
    sfx_inputs  {name: ffmpeg input index} of the wav files
    The dialogue passes through untouched (it is only summed with the quieter effects), the
    effects are ducked while someone is speaking, and a limiter catches any stray peak.
    Returns the filtergraph text that turns [loud_label] into [out_label]."""
    vol = float(cfg["sfx_volume"])
    parts, tags = [], []
    for k, (name, when, gain) in enumerate(items):
        ms = int(max(0.0, when) * 1000)
        parts.append(f"[{sfx_inputs[name]}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                     f"channel_layouts=stereo,volume={gain * vol:.4f},adelay={ms}:all=1[fx{k}]")
        tags.append(f"[fx{k}]")
    if len(tags) == 1:
        parts.append(f"{tags[0]}anull[fxsum]")
    else:
        parts.append(f"{''.join(tags)}amix=inputs={len(tags)}:normalize=0:duration=longest[fxsum]")
    parts.append("[fxsum]apad[fxpad]")
    if cfg.get("sfx_duck", True):
        # the dialogue is both heard and used as the 'sidechain' that lowers the effects
        parts.append(f"[{loud_label}]asplit=2[dlg][key]")
        parts.append("[fxpad][key]sidechaincompress=threshold=0.125:ratio=2:attack=10:release=300:"
                     "makeup=1[fxduck]")
    else:
        parts.append(f"[{loud_label}]acopy[dlg]")
        parts.append("[fxpad]acopy[fxduck]")
    parts.append("[dlg]aformat=channel_layouts=stereo[dlgm]")
    parts.append(f"[dlgm][fxduck]amix=inputs=2:normalize=0:duration=first,"
                 f"alimiter=limit=0.80:level=0:attack=0.5:release=50,aresample=48000[{out_label}]")
    return ";".join(parts)
