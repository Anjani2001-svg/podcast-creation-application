#!/usr/bin/env python3
"""
Podcast Video Creator  –  podcast_creator.py

Creates:
1) Thumbnail image with overlaid text (Course + Unit only)
2) MP4 video combining static image + audio using ffmpeg

Adds:
- Faster rendering settings
- Progress percentage callback during ffmpeg run
"""

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont
import numpy as np


# ─────────────────────────────────────────────────────────────────
# FONT DISCOVERY
# ─────────────────────────────────────────────────────────────────

_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
_USERPROFILE  = os.environ.get("USERPROFILE", str(Path.home()))

_FONT_DIRS = [
    # Repo-local fonts folder (for Streamlit Cloud / Docker)
    Path(__file__).parent / "fonts",
    # Windows
    Path("C:/Windows/Fonts"),
    Path(_LOCALAPPDATA) / "Microsoft/Windows/Fonts" if _LOCALAPPDATA else None,
    Path(_USERPROFILE)  / "AppData/Local/Microsoft/Windows/Fonts",
    # macOS
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
    # Linux
    Path.home() / ".local/share/fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
]
_FONT_DIRS = [d for d in _FONT_DIRS if d is not None]

_WEIGHT_STEMS = {
    "extrabold": [
        "Montserrat-ExtraBold",
        "Montserrat-Heavy",
        "montserrat-extrabold",
        "Montserrat ExtraBold",
        "MontserratExtraBold",
    ],
    "medium": [
        "Montserrat-Medium",
        "montserrat-medium",
        "Montserrat Medium",
        "MontserratMedium",
        "Montserrat-Regular",
    ],
}

_FALLBACKS = {
    "extrabold": [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "medium": [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}


def _find_montserrat(weight: str):
    stems = _WEIGHT_STEMS.get(weight, [])
    for d in _FONT_DIRS:
        if not d.exists():
            continue

        # Direct match
        for stem in stems:
            for ext in (".ttf", ".otf", ".TTF", ".OTF"):
                p = d / (stem + ext)
                if p.exists():
                    return p

        # Recursive search
        try:
            for p in d.rglob("*"):
                if p.stem in stems and p.suffix.lower() in (".ttf", ".otf"):
                    return p
        except PermissionError:
            continue

    return None


def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    p = _find_montserrat(weight)
    if p:
        return ImageFont.truetype(str(p), size)

    print(
        f"WARNING: Montserrat-{weight} not found – using fallback font.\n"
        f"Download: https://fonts.google.com/specimen/Montserrat\n"
        f"Install: right-click each .ttf -> Install"
    )
    for fb in _FALLBACKS.get(weight, []):
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size)

    return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────
# GEOMETRY – find the light-blue circle text zone
# ─────────────────────────────────────────────────────────────────

def find_light_circle_zone(img: Image.Image):
    """
    Return (safe_top, safe_bottom, center_x, safe_width).
    Scans for rows where G > 120 (light teal), wide + centred.
    """
    arr  = np.array(img)
    G    = arr[:, :, 1].astype(int)
    W, H = img.size

    light     = G > 120
    rows_info = []

    for row in range(H):
        lc = np.where(light[row, :])[0]
        if len(lc) < W * 0.3:
            rows_info.append(None)
            continue
        cx  = float(lc.mean())
        wid = int(lc.max() - lc.min())
        rows_info.append((cx, wid, int(lc.min()), int(lc.max())))

    img_cx    = W / 2
    safe_rows = []
    for row, info in enumerate(rows_info):
        if info and abs(info[0] - img_cx) < W * 0.15 and info[1] > W * 0.55:
            safe_rows.append(row)

    if not safe_rows:
        # Fallback: upper 45 % of image
        return int(H * 0.06), int(H * 0.46), W // 2, int(W * 0.72)

    safe_top    = safe_rows[0]  + int(H * 0.04)
    safe_bottom = safe_rows[-1] - int(H * 0.02)

    widths     = [rows_info[r][1] for r in safe_rows if rows_info[r]]
    safe_width = int(min(widths) * 0.82)

    return safe_top, safe_bottom, W // 2, safe_width


# ─────────────────────────────────────────────────────────────────
# TEXT LAYOUT HELPERS
# ─────────────────────────────────────────────────────────────────

def wrap_to_fit(text: str, font, max_px: int):
    """Word-wrap text so no line exceeds max_px."""
    text = text.strip()
    if not text:
        bb = font.getbbox(" ")
        return [""], [0], [bb[3] - bb[1]]

    for chars in range(len(text), 3, -1):
        lines = textwrap.wrap(text, width=chars) or [text]
        ws, hs = [], []
        for line in lines:
            bb = font.getbbox(line)
            ws.append(bb[2] - bb[0])
            hs.append(bb[3] - bb[1])
        if max(ws) <= max_px:
            return lines, ws, hs

    bb = font.getbbox(text)
    return [text], [bb[2] - bb[0]], [bb[3] - bb[1]]


def block_height(heights: list, line_gap: int = 6) -> int:
    return sum(heights) + line_gap * (len(heights) - 1)


def draw_block_centred(draw, lines, widths, heights, font,
                       cx: int, top_y: int, fill, line_gap: int = 6):
    y = top_y
    for i, line in enumerate(lines):
        x = cx - widths[i] // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += heights[i] + line_gap
    return y


WHITE = (255, 255, 255)


# ─────────────────────────────────────────────────────────────────
# THUMBNAIL (Course + Unit only)
# ─────────────────────────────────────────────────────────────────

def create_thumbnail(
    template_path: str,
    course_name:   str,
    unit_name:     str,
    output_path:   str = "thumbnail_out.jpg",
) -> str:
    img  = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size

    scale = W / 800.0

    safe_top, safe_bottom, cx, safe_width = find_light_circle_zone(img)
    zone_h    = safe_bottom - safe_top
    inter_gap = max(28, int(H * 0.06))          # bigger gap between blocks

    # ── Course name: extrabold, capped size ──
    max_course_size = int(28 * scale)            # moderate max (~28pt at 800px)
    for eb_size in range(max_course_size, 14, -1):
        eb_font = load_font("extrabold", eb_size)
        cl, cw, ch = wrap_to_fit(course_name, eb_font, safe_width)
        if block_height(ch, line_gap=8) <= zone_h * 0.45:
            break

    # ── Unit name: medium weight, ~55% of course size ──
    med_size = max(14, int(eb_size * 0.55))
    med_font = load_font("medium", med_size)
    unl, unw, unh = wrap_to_fit(unit_name, med_font, int(safe_width * 0.85))

    total_h = block_height(ch, 8) + inter_gap + block_height(unh, 6)
    y = safe_top + (zone_h - total_h) // 2

    y = draw_block_centred(draw, cl,  cw,  ch,  eb_font, cx, y, WHITE, line_gap=8)
    y += inter_gap
    _ = draw_block_centred(draw, unl, unw, unh, med_font, cx, y, WHITE, line_gap=6)

    img.save(output_path, quality=95)
    return output_path


# ─────────────────────────────────────────────────────────────────
# VIDEO CREATION (ffmpeg) + PROGRESS
# ─────────────────────────────────────────────────────────────────

def _ffprobe_duration_seconds(audio_path: str) -> float:
    """Return audio duration in seconds using ffprobe (bundled with ffmpeg)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe error:\n{r.stderr}")
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not parse duration from ffprobe:\n{r.stdout}")


def create_video(
    image_path: str,
    audio_path: str,
    output_path: str,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> str:
    """
    Combine static image + audio into MP4 using ffmpeg.
    Sends progress updates via progress_cb(percent, message).
    """
    import shutil
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found.\n"
            "Install on Windows (PowerShell): winget install --id Gyan.FFmpeg -e\n"
            "Then close and reopen PowerShell."
        )
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found (should come with ffmpeg).")

    duration = _ffprobe_duration_seconds(audio_path)
    if duration <= 0:
        duration = 1.0

    # ── Speed-optimised settings ──
    # -framerate 1  → only 1 input frame/sec instead of 25 (huge speedup)
    # -r 15         → 15 output fps (plenty for a still image)
    # -tune zerolatency → skips slow analysis passes
    # -crf 28       → slightly lower quality, much faster encode
    # -c:a copy     → skip audio re-encode when input is already AAC/M4A

    audio_ext = Path(audio_path).suffix.lower()
    if audio_ext in (".aac", ".m4a"):
        audio_codec = ["-c:a", "copy"]
    else:
        audio_codec = ["-c:a", "aac", "-b:a", "192k"]

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", "1",
        "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-crf", "28",
        "-r", "15",
        *audio_codec,
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    last_percent = -1
    if progress_cb:
        progress_cb(0, "Rendering: 0%")

    try:
        # ffmpeg progress lines look like key=value
        while True:
            line = p.stdout.readline()
            if not line:
                if p.poll() is not None:
                    break
                continue

            line = line.strip()
            if "=" not in line:
                continue

            key, val = line.split("=", 1)

            if key in ("out_time_ms", "out_time_us"):
                # out_time_ms is microseconds in many builds; out_time_us is microseconds.
                # We'll handle both safely.
                try:
                    t = int(val)
                except ValueError:
                    continue

                # Heuristic: treat as microseconds for both
                seconds = t / 1_000_000.0
                percent = int(min(99, (seconds / duration) * 100))
                if percent != last_percent:
                    last_percent = percent
                    if progress_cb:
                        progress_cb(percent, f"Rendering: {percent}%")

            elif key == "progress" and val == "end":
                if progress_cb:
                    progress_cb(100, "Rendering: 100%")
                break

        rc = p.wait()
        if rc != 0:
            err = (p.stderr.read() or "").strip()
            raise RuntimeError(f"ffmpeg error:\n{err}")

    finally:
        try:
            if p.stdout:
                p.stdout.close()
            if p.stderr:
                p.stderr.close()
        except Exception:
            pass

    return output_path


# ─────────────────────────────────────────────────────────────────
# CLI (optional)
# ─────────────────────────────────────────────────────────────────

def cli():
    p = argparse.ArgumentParser(description="Overlay text on a podcast thumbnail and render a video.")
    p.add_argument("--audio",    required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--course",   required=True)
    p.add_argument("--unit-name", required=True)
    p.add_argument("--output",   default="podcast_episode.mp4")
    a = p.parse_args()

    thumb = a.output.replace(".mp4", "_thumb.jpg")
    print("Generating thumbnail…")
    create_thumbnail(a.template, a.course, a.unit_name, thumb)
    print("Rendering video…")
    create_video(thumb, a.audio, a.output, progress_cb=lambda pct, msg: print(msg))
    print("Done!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli()
    else:
        print("Run with args for CLI mode, e.g. --audio ... --template ...")