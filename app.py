#!/usr/bin/env python3
"""
app.py – Podcast Video Creator (Streamlit)
Run locally:  streamlit run app.py
"""

import tempfile
import time
from pathlib import Path

import streamlit as st

from podcast_creator import create_thumbnail, create_video

# ── Page config ──
st.set_page_config(
    page_title="Podcast Video Creator",
    page_icon="🎙️",
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

    /* Header */
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

    /* Section labels */
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

    /* Inputs */
    .stTextInput > div > div > input {
        background: #0e3338 !important;
        border: 1px solid rgba(0,147,154,0.25) !important;
        color: #fff !important;
        border-radius: 8px !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #00939a !important;
        box-shadow: 0 0 0 3px rgba(0,147,154,0.15) !important;
    }

    /* File uploader */
    .stFileUploader > div {
        border: 2px dashed rgba(0,147,154,0.25) !important;
        border-radius: 14px !important;
        background: transparent !important;
    }
    .stFileUploader > div:hover {
        border-color: #00939a !important;
    }

    /* Button */
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

    /* Download button */
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

    /* Success box */
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

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ── Header ──
st.markdown("""
<div class="app-header">
    <h1>🎙️ Podcast Video Creator</h1>
    <p>Upload thumbnail + audio → branded MP4</p>
</div>
""", unsafe_allow_html=True)

# ── Media files ──
st.markdown('<div class="sec-label">Media Files</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    template_file = st.file_uploader(
        "Thumbnail Template",
        type=["jpg", "jpeg", "png"],
        help="JPG or PNG — no text baked in",
    )
with col2:
    audio_file = st.file_uploader(
        "Notebooklm Audio File",
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
st.markdown("")  # spacing
create_btn = st.button("▶ Create Video", use_container_width=True)

if create_btn:
    # ── Validation ──
    if not course or not unit_name:
        st.error("Please fill in both Course Name and Unit Name.")
    elif not template_file:
        st.error("Please upload a thumbnail template.")
    elif not audio_file:
        st.error("Please upload an audio file.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Save uploads to temp files
            tmpl_path = tmpdir / f"template{Path(template_file.name).suffix}"
            tmpl_path.write_bytes(template_file.getvalue())

            audio_path = tmpdir / f"audio{Path(audio_file.name).suffix}"
            audio_path.write_bytes(audio_file.getvalue())

            thumb_path = tmpdir / "thumbnail.jpg"
            video_path = tmpdir / "output.mp4"

            progress_bar = st.progress(0, text="Generating thumbnail…")

            try:
                # Step 1: Thumbnail
                create_thumbnail(str(tmpl_path), course, unit_name, str(thumb_path))
                progress_bar.progress(5, text="Thumbnail created. Rendering video…")

                # Step 2: Video with progress
                def on_progress(pct: int, msg: str):
                    # Map ffmpeg 0-100 → our 5-100
                    mapped = 5 + int(pct * 0.95)
                    progress_bar.progress(min(mapped, 100), text=msg)

                create_video(str(thumb_path), str(audio_path), str(video_path), progress_cb=on_progress)

                progress_bar.progress(100, text="Done!")

                # ── Show results ──
                st.markdown("""
                <div class="success-box">
                    <div class="success-title">Your video is ready!</div>
                </div>
                """, unsafe_allow_html=True)

                # Thumbnail preview
                st.image(str(thumb_path), caption="Generated Thumbnail", use_container_width=True)

                # Download buttons
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
