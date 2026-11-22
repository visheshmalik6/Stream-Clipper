"""Every knob in one place. Override any of them in ~/StreamClips/settings.json."""

from .common import DATA, Problem, read_json

DEFAULTS = {
    # finding streams
    "search_suffix": "stream",       # YouTube search = "<topic> <suffix>"; "" for any long video
    "search_when": "today",          # hour | today | week | month
    "max_age_hours": 48,             # watchlist videos older than this are skipped

    # listening
    "scan_model": "tiny",            # Whisper model for the whole stream (fast)
    "caption_model": "base",         # Whisper model for each clip's captions (accurate)
    "language": None,                # None = detect once per stream, or e.g. "en", "hi", "es"
    "block_minutes": 10,             # audio is processed and cached in blocks of this size
    "volume_jump_db": 7.0,           # this much louder than the surrounding minutes = a spike
    "chat_jump": 3.0,                # chat this many times its usual speed = a spike
    "chat_replay": True,             # read YouTube live-chat replays when there is one
    "chat_timeout": 360,

    # picking
    "clips": 3,                      # clips per stream
    "min_len": 15,
    "max_len": 59,                   # stays under the 60 s Shorts limit
    "part_minutes": 10,              # transcript window sent to the AI per call
    "part_overlap": 20,              # seconds shared by neighbouring windows
    "picks_per_part": 3,
    "brain_parallel": 3,             # AI calls at the same time
    "min_score": 40,                 # picks below this score are dropped

    # framing
    "width": 1080,
    "height": 1920,
    "layout": "auto",                # auto | stack | crop | blur
    "cam_share": 0.40,               # stack layout: share of the height given to the facecam
    "big_face": 0.13,                # face wider than this share of the frame = talking head

    # title bar
    "title_font_file": None,         # None = a bold system font
    "title_size": 56,
    "title_bg": "FFFFFF",
    "title_fg": "111111",
    "title_top": 0.07,               # used when there is no facecam seam to sit on

    # captions
    "cap_font": "Arial Black",
    "cap_size": 86,
    "cap_words": 3,
    "cap_color": "FFFFFF",
    "cap_active": "FFD400",
    "cap_outline": 7,
    "cap_upper": True,
    "cap_y": 0.70,                   # vertical position of the caption line (0 top, 1 bottom)

    # opening hook (the first seconds). "hook": false = exactly the old look
    "hook": True,                    # master switch for the opening upgrades below
    "hook_zoom": 0.10,               # punch-in strength: starts 10% zoomed in, eases to normal
    "hook_zoom_secs": 0.7,           # how long the punch-in takes to settle
    "hook_trim_lead": True,          # cut dead air before the first spoken word
    "hook_lead_keep": 0.20,          # seconds of breath kept before the first word
    "hook_max_trim": 1.5,            # never trim more than this many seconds
    "hook_title_anim": True,         # title bar slides in instead of being there from frame one
    "hook_title_delay": 0.10,        # seconds before the title starts moving
    "hook_title_secs": 0.30,         # seconds the slide takes

    # sound effects, layered UNDER the original audio. "sfx": false = no effects
    "sfx": True,
    "sfx_volume": 0.60,              # 0-1 effect loudness (0.6 = audible but ~11 dB under the dialogue)
    "sfx_duck": True,                # lower the effects automatically while someone is talking
    "sfx_accents": 1,                # soft hits on real volume jumps inside the clip (0 = none)
    "hook_accent_zoom": 0.05,        # tiny push that goes with an accent hit (0 = none)
    "sfx_accent_types": ["reaction", "funny", "reveal", "skill"],   # clip types that get accents

    # output
    "video_height": 1080,
    "crf": 21,
    "x264_preset": "fast",
    "loudness": -14,                 # LUFS; None to leave the audio as it is
    "audio_kbps": 192,
}


def load(cli=None):
    cfg = dict(DEFAULTS)
    user = DATA / "settings.json"
    if user.exists():
        data = read_json(user)
        if not isinstance(data, dict):
            raise Problem(f"{user} is not valid JSON")
        unknown = set(data) - set(DEFAULTS)
        if unknown:
            raise Problem(f"{user}: unknown setting(s) {', '.join(sorted(unknown))}")
        cfg.update(data)
    for key, value in (cli or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg
