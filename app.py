#!/usr/bin/env python3
"""
app.py – Podcast Video Creator (Streamlit) with Google Drive Upload
Run locally:  streamlit run app.py

Only requires: Audio file + Course Name + Unit Name
Thumbnail template is generated automatically in code.
Google Drive upload uses an OAuth refresh token stored in st.secrets.
"""

import re
import tempfile
import shutil
from io import BytesIO
from pathlib import Path

import streamlit as st

from podcast_creator import create_thumbnail, create_video

# ── Google Drive libraries (optional – graceful fallback if missing) ──────
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from googleapiclient.errors import HttpError
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

# ── Auto-create output folders next to the app ────────────────────────────
APP_DIR      = Path(__file__).parent
THUMB_FOLDER = APP_DIR / "thumbnails"
VIDEO_FOLDER = APP_DIR / "videos"
THUMB_FOLDER.mkdir(exist_ok=True)
VIDEO_FOLDER.mkdir(exist_ok=True)

# ── Google Drive config ───────────────────────────────────────────────────
GDRIVE_FOLDER_URL = st.secrets.get("GDRIVE_FOLDER_URL", "")
GDRIVE_SCOPES     = ["https://www.googleapis.com/auth/drive"]
FOLDER_MAX_ITEMS  = 50   # create a new Batch subfolder after this many files

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Podcast Video Creator",
    layout="centered",
)

# ── Custom CSS (teal dark theme) ──────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════════
# GOOGLE DRIVE HELPERS
# ══════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _get_drive_service():
    """Build an authenticated Drive v3 client from an OAuth refresh token
    stored in st.secrets. Cached for the app's lifetime."""
    if not GDRIVE_AVAILABLE:
        return None
    try:
        cfg = st.secrets["gdrive_oauth"]
        creds = Credentials(
            token=None,
            refresh_token=cfg["refresh_token"],
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GDRIVE_SCOPES,
        )
        creds.refresh(GoogleAuthRequest())
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def _extract_folder_id(url: str) -> str:
    """Pull the folder ID out of a Google Drive folder URL."""
    if not url:
        return ""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _count_folder_items(service, folder_id: str) -> int:
    """Count non-folder children of a Drive folder."""
    total = 0
    page_token = None
    q = (f"'{folder_id}' in parents and trashed=false "
         f"and mimeType!='application/vnd.google-apps.folder'")
    while True:
        try:
            resp = service.files().list(
                q=q, fields="nextPageToken, files(id)",
                pageSize=1000, pageToken=page_token,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
                corpora="allDrives",
            ).execute()
        except HttpError:
            return total
        total += len(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return total


def _list_batch_subfolders(service, parent_id: str):
    """Return sorted [(batch_number, folder_id, name), ...] for 'Batch N' subfolders."""
    batches = []
    page_token = None
    q = (f"'{parent_id}' in parents and trashed=false "
         f"and mimeType='application/vnd.google-apps.folder' "
         f"and name contains 'Batch '")
    while True:
        try:
            resp = service.files().list(
                q=q, fields="nextPageToken, files(id,name)",
                pageSize=200, pageToken=page_token,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
                corpora="allDrives",
            ).execute()
        except HttpError:
            break
        for f in resp.get("files", []):
            name = f.get("name", "")
            if name.startswith("Batch "):
                try:
                    num = int(name.split("Batch ", 1)[1])
                    batches.append((num, f["id"], name))
                except (ValueError, IndexError):
                    pass
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    batches.sort(key=lambda x: x[0])
    return batches


def _create_subfolder(service, parent_id: str, folder_name: str):
    """Create a subfolder inside parent_id. Returns the new folder's ID or None."""
    try:
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        f = service.files().create(
            body=meta, fields="id", supportsAllDrives=True,
        ).execute()
        return f.get("id")
    except HttpError:
        return None


def _resolve_upload_folder(service, root_folder_id: str, status_cb=None):
    """Pick the right target folder, rotating into 'Batch N' subfolders
    once FOLDER_MAX_ITEMS is exceeded. Returns (folder_id, display_name)."""
    def _cb(s):
        if status_cb:
            status_cb(s)

    _cb("📂 Checking folder capacity…")
    batches = _list_batch_subfolders(service, root_folder_id)
    file_count_in_root = _count_folder_items(service, root_folder_id)
    _cb(f"   Root folder: {file_count_in_root} file(s), {len(batches)} batch subfolder(s)")

    if file_count_in_root < FOLDER_MAX_ITEMS and len(batches) == 0:
        remaining = FOLDER_MAX_ITEMS - file_count_in_root
        _cb(f"   ✅ Using root folder ({remaining} slot(s) remaining)")
        return root_folder_id, "root"

    if batches:
        latest_num, latest_id, latest_name = batches[-1]
        latest_count = _count_folder_items(service, latest_id)
        _cb(f"   Latest batch: '{latest_name}' with {latest_count} file(s)")
        if latest_count < FOLDER_MAX_ITEMS:
            remaining = FOLDER_MAX_ITEMS - latest_count
            _cb(f"   ✅ Using '{latest_name}' ({remaining} slot(s) remaining)")
            return latest_id, latest_name
        next_num = latest_num + 1
    else:
        next_num = 1

    new_name = f"Batch {next_num}"
    _cb(f"   📁 Creating '{new_name}'…")
    new_id = _create_subfolder(service, root_folder_id, new_name)
    if new_id:
        _cb(f"   ✅ Created '{new_name}' — uploading there")
        return new_id, new_name
    _cb(f"   ⚠️ Could not create '{new_name}' — falling back to root folder")
    return root_folder_id, "root (fallback)"


def _gdrive_upload(data: bytes, filename: str, service, folder_url: str,
                   status_cb=None):
    """Resumable upload to Google Drive. Returns (ok, webViewLink_or_error)."""
    def _cb(s):
        if status_cb:
            status_cb(s)

    if service is None:
        return False, "❌ Google Drive service not available. Check credentials."

    root_id = _extract_folder_id(folder_url)
    if not root_id:
        return False, "❌ Could not parse folder ID from GDRIVE_FOLDER_URL."

    try:
        service.files().get(
            fileId=root_id, fields="id,name",
            supportsAllDrives=True,
        ).execute()
    except HttpError as e:
        return False, (f"❌ Cannot access folder (HTTP {e.resp.status}). "
                       f"Make sure the folder belongs to the Google account "
                       f"you authorised when generating the refresh token.")

    target_id, folder_label = _resolve_upload_folder(
        service, root_id, status_cb=status_cb)

    _cb("⬆️ Starting resumable upload…")
    media = MediaIoBaseUpload(
        BytesIO(data), mimetype="video/mp4",
        chunksize=5 * 1024 * 1024, resumable=True,
    )
    meta = {"name": filename, "parents": [target_id]}

    try:
        request = service.files().create(
            body=meta, media_body=media,
            fields="id,webViewLink,name",
            supportsAllDrives=True,
        )
        response = None
        total_mb = max(1, len(data) // 1048576)
        last_pct = -1
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct // 10 != last_pct // 10:
                    uploaded_mb = int(status.progress() * total_mb)
                    _cb(f"⬆️ Uploading to {folder_label}… {pct}% "
                        f"({uploaded_mb} / {total_mb} MB)")
                    last_pct = pct
        web_url = response.get("webViewLink", "https://drive.google.com")
        _cb(f"✅ Upload complete to '{folder_label}'! ({total_mb} MB)")
        return True, web_url
    except HttpError as e:
        return False, f"❌ Upload failed: HTTP {e.resp.status} — {e}"
    except Exception as e:
        return False, f"❌ Upload failed: {e}"


# ══════════════════════════════════════════════════════════════════════════
# INITIALISE DRIVE SERVICE
# ══════════════════════════════════════════════════════════════════════════

if GDRIVE_AVAILABLE:
    _drive_service = _get_drive_service()
else:
    _drive_service = None


# ══════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════

# ── Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <h1>Podcast Video Creator</h1>
    <p>Upload audio · Enter course & unit · Get your video</p>
</div>
""", unsafe_allow_html=True)

# ── Google Drive connection status ────────────────────────────────────────
if GDRIVE_AVAILABLE:
    with st.expander("☁  Google Drive Connection",
                     expanded=not bool(_drive_service and GDRIVE_FOLDER_URL)):
        if _drive_service and GDRIVE_FOLDER_URL:
            st.success("✅ Connected — videos will auto-upload to your Google Drive folder.")
            st.caption(f"📂 Auto-rotation enabled: new subfolder every {FOLDER_MAX_ITEMS} videos")
            folder_id_preview = _extract_folder_id(GDRIVE_FOLDER_URL)
            if folder_id_preview:
                st.caption(f"🔗 Target folder ID: `{folder_id_preview[:24]}…`")
            try:
                meta = _drive_service.files().get(
                    fileId=folder_id_preview, fields="id,name",
                    supportsAllDrives=True,
                ).execute()
                st.caption(f"📁 Folder name: **{meta.get('name', '?')}**")
            except Exception as ex:
                st.warning(
                    f"⚠️ Cannot reach folder yet: {ex}\n\n"
                    "Make sure `GDRIVE_FOLDER_URL` points to a folder owned by "
                    "the Google account you used when generating the refresh token."
                )
        elif not GDRIVE_FOLDER_URL:
            st.error("❌ `GDRIVE_FOLDER_URL` is not set in `.streamlit/secrets.toml`.")
            st.markdown("""
**Add this to your `secrets.toml`:**
```toml
GDRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"

[gdrive_oauth]
client_id     = "123456789-abc.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxxxxxxxxxxxxxxxxxx"
refresh_token = "1//0gXXXXXXXXXXXXXXXXXXXXXXXXX"
```
Run `Get_refresh_token.py` once locally to obtain the `refresh_token` value.
            """)
        else:
            st.error(
                "❌ Could not load OAuth credentials. "
                "Check the `[gdrive_oauth]` block in `.streamlit/secrets.toml`. "
                "The `refresh_token` may be expired — re-run `Get_refresh_token.py`."
            )
else:
    st.warning(
        "⚠️ Google Drive libraries not installed.\n\n"
        "Run: `pip install google-api-python-client google-auth`"
    )

# ── Audio upload ──────────────────────────────────────────────────────────
st.markdown('<div class="sec-label">Audio File</div>', unsafe_allow_html=True)

audio_file = st.file_uploader(
    "NotebookLM Audio File",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    help="MP3 · WAV · M4A · AAC",
)

# ── Episode details ───────────────────────────────────────────────────────
st.markdown('<div class="sec-label">Course and Unit Details</div>', unsafe_allow_html=True)

course = st.text_input(
    "Course Name",
    placeholder="Level 7 Extended Diploma in Computing Technologies (Networking) - RQF",
)
unit_name = st.text_input(
    "Unit Number and Unit Name",
    placeholder="Unit 01 - Managing Innovation and Change in Computing",
)

# ── Create button ─────────────────────────────────────────────────────────
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
                # Step 1: Thumbnail
                create_thumbnail(course, unit_name, str(thumb_path))
                progress_bar.progress(5, text="Thumbnail created. Rendering video…")

                # Step 2: Video with progress
                def on_progress(pct: int, msg: str):
                    mapped = 5 + int(pct * 0.95)
                    progress_bar.progress(min(mapped, 100), text=msg)

                create_video(str(thumb_path), str(audio_path), str(video_path), progress_cb=on_progress)

                progress_bar.progress(100, text="Done!")

                # ── Auto-save to local folders ──
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
                            file_name=f"{safe_name}.mp4",
                            mime="video/mp4",
                            use_container_width=True,
                        )
                with col_b:
                    with open(thumb_path, "rb") as f:
                        st.download_button(
                            "⬇ Download Thumbnail (.jpg)",
                            data=f,
                            file_name=f"{safe_name}_thumbnail.jpg",
                            mime="image/jpeg",
                            use_container_width=True,
                        )

                # ── Google Drive auto-upload ──────────────────────────────
                if _drive_service and GDRIVE_FOLDER_URL:
                    st.markdown("---")
                    st.markdown('<div class="sec-label">☁ Google Drive Upload</div>',
                                unsafe_allow_html=True)
                    upload_log = st.empty()
                    log_lines  = []

                    def _status_cb(msg: str):
                        log_lines.append(msg)
                        upload_log.info("\n\n".join(log_lines))

                    video_bytes    = video_path.read_bytes()
                    drive_filename = f"{safe_name}.mp4"

                    ok, result = _gdrive_upload(
                        video_bytes, drive_filename,
                        _drive_service, GDRIVE_FOLDER_URL,
                        status_cb=_status_cb,
                    )

                    if ok:
                        upload_log.empty()
                        st.success(
                            f"☁️ **Uploaded to Google Drive!** "
                            f"[Open file in Drive]({result})"
                        )
                    else:
                        upload_log.empty()
                        st.error(result)

                elif GDRIVE_AVAILABLE and not _drive_service:
                    st.warning("⚠️ Google Drive not connected — check your secrets.toml credentials.")

            except Exception as e:
                progress_bar.empty()
                st.error(f"Error: {e}")
