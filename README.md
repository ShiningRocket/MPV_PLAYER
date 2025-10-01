## Python + PyQt Media Player using MPV (Debian 11)

This project is a fullscreen media player for Debian 11 that embeds MPV inside a PyQt window and is controlled via a REST API. It is designed for TV-style playback where MPV handles playlist creation and resume-on-quit natively.

### Milestone 1: MPV + PyQt Integration ✅
- PyQt fullscreen window
- MPV embedded via `--wid`
- Launch with a folder path; MPV auto-generates playlist
- MPV flags: `--save-position-on-quit` and `--input-ipc-server=/tmp/mpvsocket`
- **No default MPV controls** - clean fullscreen experience

### Milestone 2: REST API Server Setup ✅
- Flask REST API server running on configurable port (default: 5000)
- Full playback control via HTTP endpoints
- IPC communication with MPV process

### Milestone 3: Overlay Ads System ✅
- Bottom and side overlay banners added to the PyQt layout (both can be shown simultaneously)
- Supports text (static or scrolling) and image/GIF overlays
- Overlays auto-hide after configurable duration
- REST API endpoints:
  - `POST /show-overlay`
    ```json
    {"position":"bottom|side","type":"image|text","content":"/path/or/text","duration":10,"scroll":false}
    ```
  - `POST /hide-overlay`
    ```json
    {"position":"bottom|side"} // omit to hide all
    ```

### Requirements
- Python 3.9+ recommended
- Debian 11 with MPV installed
- X11 display (wid embedding)

Install system dependencies on Debian:
```bash
sudo apt update
sudo apt install -y mpv python3-pip
```

Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

### Run
```bash
# Development server (default)
python3 player.py --media-dir /path/to/your/videos --api-port 5000

# Production server (no warnings)
python3 player.py --media-dir /path/to/your/videos --api-port 5000 --production-server
```

Notes:
- Provide a directory containing videos. MPV will scan and build its playlist automatically.
- Resume on quit is handled by MPV; no custom logic here.
- REST API server starts automatically on the specified port (default: 5000).

### REST API Endpoints

The player exposes a REST API for remote control:

#### Playback Control
- `POST /api/play` - Start or resume playback
- `POST /api/pause` - Pause playback  
- `POST /api/next` - Go to next video in playlist
- `POST /api/previous` - Go to previous video in playlist

#### Seeking
- `POST /api/seek-forward` - Seek forward (default: 30 seconds)
  ```json
  {"seconds": 30}
  ```
- `POST /api/seek-backward` - Seek backward (default: 30 seconds)
  ```json
  {"seconds": 30}
  ```

#### Volume Control
- `POST /api/volume` - Set volume (0-100)
  ```json
  {"volume": 75}
  ```

#### Status
- `GET /api/status` - Get player status and IPC socket info

#### Overlay Ads
- `POST /show-overlay` - Show an overlay banner
  ```json
  {"position":"bottom","type":"text","content":"Tonight 9PM: New Episode!","duration":15,"scroll":true}
  ```
- `POST /hide-overlay` - Hide an overlay banner (or all)
  ```json
  {"position":"side"}
  ```

### Example API Usage
```bash
# Check status
curl http://localhost:5000/api/status

# Play/pause
curl -X POST http://localhost:5000/api/play

# Next video
curl -X POST http://localhost:5000/api/next

# Seek forward 60 seconds
curl -X POST http://localhost:5000/api/seek-forward -H "Content-Type: application/json" -d '{"seconds": 60}'

# Set volume to 80%
curl -X POST http://localhost:5000/api/volume -H "Content-Type: application/json" -d '{"volume": 80}'
```

### Project Layout (current)
```
MVP/
  player.py                 # PyQt app with embedded MPV and REST API + overlays
  requirements.txt          # Python dependencies
  README.md                 # This documentation
  tests/media/             # Sample videos for testing
    test.mp4
```

### Troubleshooting
- If you see a black screen, ensure MPV is installed and X11 is used (not Wayland), and that your GPU drivers are OK. Try `--vo=gpu` or `--vo=xv` in `player.py` if needed.
- On ARM SBCs (RK3566/3588), ensure MPV build supports your GPU and drivers.


