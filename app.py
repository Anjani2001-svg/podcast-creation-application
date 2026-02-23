#!/usr/bin/env python3
"""
app.py – Podcast Video Creator (Streamlit)
Run locally:  streamlit run app.py

Only requires: Audio file + Course Name + Unit Name
Thumbnail template is generated automatically in code.
"""

import tempfile
import shutil
from pathlib import Path

import streamlit as st

from podcast_creator import create_thumbnail, create_video

# ── Auto-create output folders next to the app ──
APP_DIR      = Path(__file__).parent
THUMB_FOLDER = APP_DIR / "thumbnails"
VIDEO_FOLDER = APP_DIR / "videos"
THUMB_FOLDER.mkdir(exist_ok=True)
VIDEO_FOLDER.mkdir(exist_ok=True)

# ── Page config ──
st.set_page_config(
    page_title="Podcast Video Creator",
    layout="centered",
)

# ── Custom CSS (teal dark theme) ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Space+Grotesk:wght@500;700&display=swap');

    .stApp {
        background: #071e22;
        color: #d4eff1;
    }

    .app-header {
        text-align: center;
        padding: 1.5rem 0 1rem;
    }
    .app-header h1 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2rem;
        font-weight: 700;
        background: linear-gradient(135deg, #00939a, #00c2cb);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem;
    }
    .app-header p {
        color: #FFFFFF;
        font-size: 0.9rem;
    }

    .sec-label {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.7rem;
        font-weight: 500;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #FFFFFF;
        margin: 1.2rem 0 0.5rem;
        padding-bottom: 0.4rem;
        border-bottom: 1px solid rgba(0,147,154,0.25);
    }

    .stTextInput > div > div > input {
        background:  #008080 !important;
        border: 1px solid rgba(0,147,154,0.25) !important;
        color: #fff !important;
        border-radius: 8px !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #00939a !important;
        box-shadow: 0 0 0 3px rgba(0,147,154,0.15) !important;
    }

    .stFileUploader > div {
        border: 2px dashed rgba(0,147,154,0.25) !important;
        border-radius: 14px !important;
        background: transparent !important;
    }
    .stFileUploader > div:hover {
        border-color: #00939a !important;
    }

    .stButton > button {
        width: 100%;
        padding: 0.8rem;
        background: linear-gradient(135deg, #00939a, #00b0b8) !important;
        color: #fff !important;
        font-family: 'Space Grotesk', sans-serif !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 10px !important;
        box-shadow: 0 4px 18px rgba(0,147,154,0.35);
    }
    .stButton > button:hover {
        opacity: 0.9;
    }

    .stDownloadButton > button {
        width: 100%;
        background: #0e3338 !important;
        border: 1px solid rgba(0,147,154,0.25) !important;
        color: #fff !important;
        border-radius: 10px !important;
    }
    .stDownloadButton > button:hover {
        border-color: #00939a !important;
        background: rgba(0,147,154,0.15) !important;
    }

    .success-box {
        background: #122a2e;
        border: 1px solid rgba(0,147,154,0.25);
        border-radius: 14px;
        padding: 1.5rem;
        margin-top: 1rem;
    }
    .success-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1rem;
        font-weight: 700;
        color: #4ee8c4;
        margin-bottom: 1rem;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ── Header ──
st.markdown("""
<div class="app-header">
    <h1>Podcast Video Creator</h1>
    <p>Upload audio · Enter course & unit · Get your video</p>
</div>
""", unsafe_allow_html=True)

# ── Audio upload ──
st.markdown('<div class="sec-label">Audio File</div>', unsafe_allow_html=True)

audio_file = st.file_uploader(
    "NotebookLM Audio File",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    help="MP3 · WAV · M4A · AAC",
)

# ── Episode details ──
st.markdown('<div class="sec-label">Course and Unit Details</div>', unsafe_allow_html=True)

course = st.text_input(
    "Course Name",
    placeholder="Level 7 Extended Diploma in Computing Technologies (Networking) - RQF",
)
unit_name = st.text_input(
    "Unit Number and Unit Name",
    placeholder="Unit 01 - Managing Innovation and Change in Computing",
)

# ── Create button ──
st.markdown("")
create_btn = st.button("▶ Create Video", use_container_width=True)

if create_btn:
    # ── Validation ──
    if not course or not unit_name:
        st.error("Please fill in both Course Name and Unit Name.")
    elif not audio_file:
        st.error("Please upload an audio file.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            audio_path = tmpdir / f"audio{Path(audio_file.name).suffix}"
            audio_path.write_bytes(audio_file.getvalue())

            thumb_path = tmpdir / "thumbnail.jpg"
            video_path = tmpdir / "output.mp4"

            progress_bar = st.progress(0, text="Generating thumbnail…")

            try:
                # Step 1: Thumbnail (auto-generated template)
                create_thumbnail(course, unit_name, str(thumb_path))
                progress_bar.progress(5, text="Thumbnail created. Rendering video…")

                # Step 2: Video with progress
                def on_progress(pct: int, msg: str):
                    mapped = 5 + int(pct * 0.95)
                    progress_bar.progress(min(mapped, 100), text=msg)

                create_video(str(thumb_path), str(audio_path), str(video_path), progress_cb=on_progress)

                progress_bar.progress(100, text="Done!")

                # ── Auto-save to folders ──
                safe_name = unit_name.replace(" ", "_").replace("/", "-")[:60]
                saved_thumb = THUMB_FOLDER / f"{safe_name}_thumbnail.jpg"
                saved_video = VIDEO_FOLDER / f"{safe_name}.mp4"
                shutil.copy2(thumb_path, saved_thumb)
                shutil.copy2(video_path, saved_video)

                # ── Show results ──
                st.markdown("""
                <div class="success-box">
                    <div class="success-title">Your video is ready!</div>
                </div>
                """, unsafe_allow_html=True)

                st.success(f"📁 Thumbnail saved to: `thumbnails/{saved_thumb.name}`")
                st.success(f"📁 Video saved to: `videos/{saved_video.name}`")

                st.image(str(thumb_path), caption="Generated Thumbnail", use_container_width=True)

                col_a, col_b = st.columns(2)
                with col_a:
                    with open(video_path, "rb") as f:
                        st.download_button(
                            "⬇ Download Video (.mp4)",
                            data=f,
                            file_name="podcast_episode.mp4",
                            mime="video/mp4",
                            use_container_width=True,
                        )
                with col_b:
                    with open(thumb_path, "rb") as f:
                        st.download_button(
                            "⬇ Download Thumbnail (.jpg)",
                            data=f,
                            file_name="podcast_thumbnail.jpg",
                            mime="image/jpeg",
                            use_container_width=True,
                        )

            except Exception as e:
                progress_bar.empty()
                st.error(f"Error: {e}")
