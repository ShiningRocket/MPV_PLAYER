## Python + PyQt Media Player using MPV (Debian 11)

This project is a fullscreen media player for Debian 11 that embeds MPV inside a PyQt window and will be controlled via a REST API (in later milestones). It is designed for TV-style playback where MPV handles playlist creation and resume-on-quit natively.

### Milestone 1: MPV + PyQt Integration
- PyQt fullscreen window
- MPV embedded via `--wid`
- Launch with a folder path; MPV auto-generates playlist
- MPV flags: `--save-position-on-quit` and `--input-ipc-server=/tmp/mpvsocket`

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
python3 player.py --media-dir /path/to/your/videos
```

Notes:
- Provide a directory containing videos. MPV will scan and build its playlist automatically.
- Resume on quit is handled by MPV; no custom logic here.
- An IPC server is exposed at `/tmp/mpvsocket` for future REST control.

### Project Layout (current)
```
MVP/
  player.py                 # PyQt app, embeds MPV via --wid
  requirements.txt
  README.md
  tests/media/              # Put a couple of small sample videos here
```

### Troubleshooting
- If you see a black screen, ensure MPV is installed and X11 is used (not Wayland), and that your GPU drivers are OK. Try `--vo=gpu` or `--vo=xv` in `player.py` if needed.
- On ARM SBCs (RK3566/3588), ensure MPV build supports your GPU and drivers.


