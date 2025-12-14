# TubeKit
Unofficial YouTube web client that uses:

- YouTube embeds (`youtube-nocookie.com`) for playback
- YouTube’s public RSS/Atom feeds for channel/playlist listings

It does **not** use the YouTube Data API (no API key).

## Run

```bash
python3 server.py --port 8000
```

Open `http://127.0.0.1:8000`.

## Notes

- For feeds, you currently need a `channel_id` (starts with `UC...`) or `playlist_id` (starts with `PL...`).
- This project does not download video files; it plays videos via the embedded player.
