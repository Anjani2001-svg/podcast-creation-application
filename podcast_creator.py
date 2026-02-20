#!/usr/bin/env python3
"""
Podcast Video Creator  –  podcast_creator.py
=============================================
Overlays course / unit text onto a clean thumbnail (text-free design)
using Montserrat fonts, then merges with audio to produce an MP4.

Font specification
------------------
  Course name   Montserrat ExtraBold   50 pt  (auto-scales to fit)
  Unit name     Montserrat ExtraBold   50 pt  (auto-scales to fit)
  Unit number   Montserrat Medium      36 pt  (fixed, scales with image)

Text is placed ONLY inside the light-blue circular region, centred.

Install Montserrat free: https://fonts.google.com/specimen/Montserrat
  -> Download -> Extract -> Right-click each .ttf -> Install

CLI
---
  python podcast_creator.py ^
    --audio       episode.mp3 ^
    --template    clean_thumb.jpg ^
    --course      "Level 7 Extended Diploma in Computing Technologies" ^
    --unit-name   "Managing Innovation and Change in Computing" ^
    --unit-number "D/618/7843" ^
    --output      episode_01.mp4
"""

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np

# ─────────────────────────────────────────────────────────────────
# FONT DISCOVERY
# ─────────────────────────────────────────────────────────────────

_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
_USERPROFILE  = os.environ.get("USERPROFILE", str(Path.home()))

_FONT_DIRS = [
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
# Remove None entries
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
        # Recursive search inside subfolders
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
        f"  WARNING: Montserrat-{weight} not found – using fallback font.\n"
        f"  Download free: https://fonts.google.com/specimen/Montserrat\n"
        f"  Install: right-click each .ttf file -> Install"
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
    """Word-wrap text so no line exceeds max_px. Returns (lines, widths, heights)."""
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


# ─────────────────────────────────────────────────────────────────
# MAIN THUMBNAIL FUNCTION
# ─────────────────────────────────────────────────────────────────

WHITE = (255, 255, 255)


def create_thumbnail(
    template_path: str,
    course_name:   str,
    unit_name:     str,
    unit_number:   str,
    output_path:   str = "thumbnail_out.jpg",
) -> str:
    """
    Open template_path (clean, text-free thumbnail) and overlay
    the course / unit information using Montserrat fonts.
    Saves result to output_path and returns output_path.
    """
    img  = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size

    scale = W / 800.0   # scale relative to 800 px reference width

    # Find the light-blue circle region
    safe_top, safe_bottom, cx, safe_width = find_light_circle_zone(img)
    zone_h    = safe_bottom - safe_top
    inter_gap = max(16, int(H * 0.022))

    # Unit number – fixed 36 pt (scaled)
    unum_size = max(20, int(36 * scale))
    unum_font = load_font("medium", unum_size)
    unum_l, unum_w, unum_h = wrap_to_fit(unit_number, unum_font, safe_width)
    unum_bh = block_height(unum_h)

    # Remaining space for course name + unit name
    remaining = zone_h - unum_bh - inter_gap * 2

    # Find largest ExtraBold size where BOTH texts fit
    for eb_size in range(int(50 * scale), 14, -1):
        eb_font = load_font("extrabold", eb_size)
        cl,  cw,  ch  = wrap_to_fit(course_name, eb_font, safe_width)
        unl, unw, unh = wrap_to_fit(unit_name,   eb_font, safe_width)
        if block_height(ch) + block_height(unh) + inter_gap <= remaining:
            break

    cl,  cw,  ch  = wrap_to_fit(course_name, eb_font, safe_width)
    unl, unw, unh = wrap_to_fit(unit_name,   eb_font, safe_width)

    # Centre all text vertically within the circle zone
    total_h = (block_height(ch) + block_height(unh) + unum_bh + inter_gap * 2)
    y = safe_top + (zone_h - total_h) // 2

    # Draw
    y = draw_block_centred(draw, cl,     cw,     ch,     eb_font,   cx, y, WHITE, line_gap=8)
    y += inter_gap
    y = draw_block_centred(draw, unl,    unw,    unh,    eb_font,   cx, y, WHITE, line_gap=6)
    y += inter_gap
    y = draw_block_centred(draw, unum_l, unum_w, unum_h, unum_font, cx, y, WHITE, line_gap=6)

    img.save(output_path, quality=95)
    return output_path


# ─────────────────────────────────────────────────────────────────
# VIDEO CREATION  (local ffmpeg)
# ─────────────────────────────────────────────────────────────────

def create_video(image_path: str, audio_path: str, output_path: str) -> str:
    """Combine static image + audio into MP4 using ffmpeg."""
    import shutil
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found.\n"
            "Install on Windows: winget install --id Gyan.FFmpeg -e --source winget\n"
            "Then close and reopen PowerShell."
        )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i",    image_path,
        "-i",    audio_path,
        "-c:v",  "libx264",
        "-tune", "stillimage",
        "-c:a",  "aac",
        "-b:a",  "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr}")
    return output_path


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

def cli():
    p = argparse.ArgumentParser(
        description="Overlay text on a podcast thumbnail and render a video."
    )
    p.add_argument("--audio",       required=True,  help="Audio file (.mp3 / .wav / .m4a)")
    p.add_argument("--template",    required=True,  help="Clean thumbnail image (no text)")
    p.add_argument("--course",      required=True,  help="Course name  (ExtraBold 50pt)")
    p.add_argument("--unit-name",   required=True,  help="Unit name    (ExtraBold 50pt)")
    p.add_argument("--unit-number", required=True,  help="Unit number  (Medium 36pt)")
    p.add_argument("--output",      default="podcast_episode.mp4")
    a = p.parse_args()

    for path, lbl in [(a.audio, "audio"), (a.template, "template")]:
        if not os.path.exists(path):
            print(f"File not found: {path}")
            sys.exit(1)

    thumb = a.output.replace(".mp4", "_thumb.jpg")
    print("Generating thumbnail…")
    create_thumbnail(a.template, a.course, a.unit_name, a.unit_number, thumb)
    print(f"  saved -> {thumb}")

    print("Rendering video…")
    try:
        create_video(thumb, a.audio, a.output)
        print(f"  saved -> {a.output}")
        print("Done!")
    except RuntimeError as e:
        print(e)
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# GUI  (tkinter – double-click or run with no arguments)
# ─────────────────────────────────────────────────────────────────

def gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("tkinter not available – please use CLI mode.")
        return

    root = tk.Tk()
    root.title("Podcast Video Creator")
    root.geometry("700x560")
    root.configure(bg="#083a46")
    root.resizable(False, False)

    s = ttk.Style()
    s.theme_use("clam")
    s.configure("TLabel",     background="#083a46", foreground="white",    font=("Helvetica", 11))
    s.configure("H.TLabel",   background="#083a46", foreground="#5ee8f5",  font=("Helvetica", 15, "bold"))
    s.configure("TEntry",     font=("Helvetica", 11), padding=4)
    s.configure("TButton",    font=("Helvetica", 11), padding=5)
    s.configure("Go.TButton", background="#00939a", foreground="white",
                font=("Helvetica", 13, "bold"), padding=9)

    f = tk.Frame(root, bg="#083a46")
    f.pack(fill="both", expand=True, padx=26, pady=20)
    f.columnconfigure(1, weight=1)

    ttk.Label(f, text="Podcast Video Creator", style="H.TLabel").grid(
        row=0, column=0, columnspan=3, pady=(0, 20))

    v = {}

    def add_row(label, key, row, browse_fn=None, default=""):
        ttk.Label(f, text=label, width=16, anchor="e").grid(
            row=row, column=0, sticky="e", padx=(0, 8), pady=6)
        sv = tk.StringVar(value=default)
        v[key] = sv
        ent = ttk.Entry(f, textvariable=sv, width=48)
        ent.grid(row=row, column=1, sticky="ew", pady=6)
        if browse_fn:
            ttk.Button(
                f, text="...", width=3,
                command=lambda e=ent, b=browse_fn: (e.delete(0, "end"), e.insert(0, b() or ""))
            ).grid(row=row, column=2, padx=(6, 0))

    add_row("Audio file:",   "audio",    1, lambda: filedialog.askopenfilename(
        filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac"), ("All files", "*")]))
    add_row("Template:",     "template", 2, lambda: filedialog.askopenfilename(
        filetypes=[("Image", "*.jpg *.jpeg *.png"), ("All files", "*")]))
    add_row("Course name:",  "course",   3)
    add_row("Unit name:",    "uname",    4)
    add_row("Unit number:",  "unum",     5)
    add_row("Output file:",  "output",   6, lambda: filedialog.asksaveasfilename(
        defaultextension=".mp4", filetypes=[("MP4 Video", "*.mp4")]))

    status_var = tk.StringVar(value="Ready.")
    tk.Label(f, textvariable=status_var, bg="#083a46", fg="#5ee8f5",
             font=("Helvetica", 10), wraplength=600, justify="left").grid(
        row=7, column=0, columnspan=3, pady=(20, 4), sticky="w")

    def run():
        d = {k: sv.get().strip() for k, sv in v.items()}
        missing = [k for k in ("audio", "template", "course", "uname", "unum", "output") if not d[k]]
        if missing:
            messagebox.showerror("Missing fields", "Please fill in: " + ", ".join(missing))
            return
        for path, lbl in [(d["audio"], "Audio"), (d["template"], "Template")]:
            if not os.path.exists(path):
                messagebox.showerror("File not found", f"{lbl} file not found:\n{path}")
                return

        btn.configure(state="disabled")
        thumb = d["output"].replace(".mp4", "_thumb.jpg")

        try:
            status_var.set("Generating thumbnail...")
            root.update()
            create_thumbnail(d["template"], d["course"], d["uname"], d["unum"], thumb)

            status_var.set("Rendering video (this may take a while)...")
            root.update()
            create_video(thumb, d["audio"], d["output"])

            status_var.set(f"Done!  ->  {d['output']}")
            messagebox.showinfo("Success", f"Video saved:\n{d['output']}")

        except Exception as e:
            status_var.set(f"Error: {e}")
            messagebox.showerror("Error", str(e))
        finally:
            btn.configure(state="normal")

    btn = ttk.Button(f, text="Create Video", style="Go.TButton", command=run)
    btn.grid(row=8, column=0, columnspan=3, pady=16, ipadx=28, ipady=5)

    root.mainloop()


# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli()
    else:
        gui()
