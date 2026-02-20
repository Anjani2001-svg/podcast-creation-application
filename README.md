# 🎙️ Podcast Video Creator

Upload a thumbnail template + audio file → get a branded MP4 video with text overlay.

## Deploy on Streamlit Cloud

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Deploy!

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

> **Note:** ffmpeg must be installed on your system.

## Optional: Montserrat Fonts

For best results, download [Montserrat](https://fonts.google.com/specimen/Montserrat) and place the `.ttf` files in a `fonts/` folder:

```
fonts/
  Montserrat-ExtraBold.ttf
  Montserrat-Medium.ttf
```

If not found, Liberation Sans (installed via `packages.txt`) is used as fallback.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI |
| `podcast_creator.py` | Thumbnail + video rendering logic |
| `requirements.txt` | Python dependencies |
| `packages.txt` | System packages (ffmpeg, fonts) for Streamlit Cloud |
| `.streamlit/config.toml` | Theme + upload size config |
| `fonts/` | *(optional)* Montserrat font files |
