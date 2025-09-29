import os
import sys
import time
import socket
import shutil
import subprocess
import json
import threading
from typing import Optional

import click
from flask import Flask, request, jsonify

from PyQt5 import QtCore, QtWidgets, QtGui


IPC_SOCKET_PATH = "/tmp/mpvsocket"


class MpvProcessManager(QtCore.QObject):
    """
    Manages the lifecycle of the mpv process embedded into a given window id.
    """

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._ipc_path: str = IPC_SOCKET_PATH

    def _cleanup_ipc_socket(self) -> None:
        try:
            if os.path.exists(self._ipc_path):
                os.remove(self._ipc_path)
        except Exception:
            pass

    def start(self, wid: int, media_dir: str) -> None:
        if not shutil.which("mpv"):
            raise RuntimeError("mpv is not installed or not in PATH")
        if not os.path.isdir(media_dir):
            raise RuntimeError(f"Media directory does not exist: {media_dir}")

        self._cleanup_ipc_socket()

        args = [
            "mpv",
            media_dir,
            f"--wid={wid}",
            "--fullscreen=yes",
            "--save-position-on-quit=yes",
            f"--input-ipc-server={self._ipc_path}",
            "--keep-open=no",
            "--idle=no",
            "--no-osd-bar",  # Hide OSD bar
            "--no-input-default-bindings",  # Disable default key bindings
            "--no-input-vo-keyboard",  # Disable keyboard input
            "--no-input-cursor",  # Disable cursor input
            "--cursor-autohide=no",  # Keep cursor hidden
            # You may tweak the video output driver if needed for target hardware:
            # "--vo=gpu",
        ]

        # Launch mpv detached but tracked by this process
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )

    def _send_ipc_command(self, command: list, timeout_s: float = 1.5) -> bool:
        """Send a command to MPV via IPC socket"""
        if not os.path.exists(self._ipc_path):
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout_s)
                s.connect(self._ipc_path)
                payload = json.dumps({"command": command}).encode("utf-8") + b'\n'
                s.sendall(payload)
                return True
        except Exception:
            return False

    def _send_ipc_quit(self, timeout_s: float = 1.5) -> bool:
        return self._send_ipc_command(["quit"], timeout_s)

    def play_pause(self) -> bool:
        """Toggle play/pause"""
        return self._send_ipc_command(["cycle", "pause"])

    def next_video(self) -> bool:
        """Go to next video in playlist"""
        return self._send_ipc_command(["playlist_next"])

    def previous_video(self) -> bool:
        """Go to previous video in playlist"""
        return self._send_ipc_command(["playlist_prev"])

    def seek_forward(self, seconds: int = 30) -> bool:
        """Seek forward by specified seconds"""
        return self._send_ipc_command(["seek", seconds])

    def seek_backward(self, seconds: int = 30) -> bool:
        """Seek backward by specified seconds"""
        return self._send_ipc_command(["seek", -seconds])

    def set_volume(self, volume: int) -> bool:
        """Set volume (0-100)"""
        return self._send_ipc_command(["set", "volume", volume])

    def stop(self) -> None:
        if self._process is None:
            return
        # Try clean quit via IPC so mpv saves position
        sent_quit = self._send_ipc_quit()

        try:
            if sent_quit:
                # give mpv a moment to exit cleanly
                for _ in range(15):
                    ret = self._process.poll()
                    if ret is not None:
                        break
                    time.sleep(0.1)
            # if still running, terminate
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        finally:
            self._process = None
            # Best-effort cleanup
            self._cleanup_ipc_socket()


class MediaPlayerAPI:
    """REST API server for controlling the media player"""
    
    def __init__(self, mpv_manager: MpvProcessManager, port: int = 5000):
        self.mpv_manager = mpv_manager
        self.app = Flask(__name__)
        self.port = port
        self._setup_routes()
    
    def _setup_routes(self):
        """Set up all API routes"""
        
        @self.app.route('/api/play', methods=['POST'])
        def play():
            """Start or resume playback"""
            success = self.mpv_manager.play_pause()
            return jsonify({"success": success, "action": "play"})
        
        @self.app.route('/api/pause', methods=['POST'])
        def pause():
            """Pause playback"""
            success = self.mpv_manager.play_pause()
            return jsonify({"success": success, "action": "pause"})
        
        @self.app.route('/api/next', methods=['POST'])
        def next_video():
            """Go to next video in playlist"""
            success = self.mpv_manager.next_video()
            return jsonify({"success": success, "action": "next"})
        
        @self.app.route('/api/previous', methods=['POST'])
        def previous_video():
            """Go to previous video in playlist"""
            success = self.mpv_manager.previous_video()
            return jsonify({"success": success, "action": "previous"})
        
        @self.app.route('/api/seek-forward', methods=['POST'])
        def seek_forward():
            """Seek forward by specified seconds"""
            data = request.get_json() or {}
            seconds = data.get('seconds', 30)
            success = self.mpv_manager.seek_forward(seconds)
            return jsonify({"success": success, "action": "seek_forward", "seconds": seconds})
        
        @self.app.route('/api/seek-backward', methods=['POST'])
        def seek_backward():
            """Seek backward by specified seconds"""
            data = request.get_json() or {}
            seconds = data.get('seconds', 30)
            success = self.mpv_manager.seek_backward(seconds)
            return jsonify({"success": success, "action": "seek_backward", "seconds": seconds})
        
        @self.app.route('/api/volume', methods=['POST'])
        def set_volume():
            """Set volume (0-100)"""
            data = request.get_json() or {}
            volume = data.get('volume', 50)
            if not isinstance(volume, int) or volume < 0 or volume > 100:
                return jsonify({"success": False, "error": "Volume must be between 0 and 100"}), 400
            success = self.mpv_manager.set_volume(volume)
            return jsonify({"success": success, "action": "set_volume", "volume": volume})
        
        @self.app.route('/api/status', methods=['GET'])
        def status():
            """Get player status"""
            return jsonify({
                "success": True,
                "status": "running",
                "ipc_socket": IPC_SOCKET_PATH,
                "socket_exists": os.path.exists(IPC_SOCKET_PATH)
            })
    
    def start(self, use_production_server=False):
        """Start the API server in a separate thread"""
        def run_server():
            if use_production_server:
                # Use Gunicorn for production
                try:
                    import gunicorn.app.wsgiapp as wsgi
                    sys.argv = ['gunicorn', '--bind', f'0.0.0.0:{self.port}', 
                               '--workers', '1', '--threads', '2', 
                               '--access-logfile', '-', '--error-logfile', '-',
                               '--log-level', 'info', 'player:app']
                    wsgi.run()
                except ImportError:
                    print("Gunicorn not available, falling back to Flask development server")
                    self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
            else:
                # Suppress Flask development server warning
                import logging
                log = logging.getLogger('werkzeug')
                log.setLevel(logging.ERROR)
                
                self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
        
        api_thread = threading.Thread(target=run_server, daemon=True)
        api_thread.start()
        server_type = "production (Gunicorn)" if use_production_server else "development (Flask)"
        print(f"API server started on http://0.0.0.0:{self.port} ({server_type})")
        return api_thread


class PlayerWindow(QtWidgets.QMainWindow):
    def __init__(self, media_dir: str, api_port: int = 5000, use_production_server: bool = False) -> None:
        super().__init__()
        self.media_dir = media_dir
        self.mpv_manager = MpvProcessManager(self)
        self.api_port = api_port
        self.use_production_server = use_production_server
        self.api_server = None

        self.setWindowTitle("MPV Player")
        self.setCursor(QtCore.Qt.BlankCursor)  # kiosk-like
        self.setContentsMargins(0, 0, 0, 0)

        # Central widget that will host mpv
        self.video_host = QtWidgets.QWidget(self)
        self.video_host.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(self.video_host)

        # Go fullscreen and start mpv once window has a native id
        self.showFullScreen()
        QtCore.QTimer.singleShot(0, self._start_mpv_once_visible)

    def _start_mpv_once_visible(self) -> None:
        # Ensure native window is created
        self.video_host.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.video_host.winId()  # force native handle creation

        # Determine the correct wid to embed into: use the video_host's id
        wid = int(self.video_host.winId())
        self.mpv_manager.start(wid=wid, media_dir=self.media_dir)
        
        # Start the API server after MPV is running
        QtCore.QTimer.singleShot(2000, self._start_api_server)  # Wait 2 seconds for MPV to start
    
    def _start_api_server(self) -> None:
        """Start the REST API server"""
        self.api_server = MediaPlayerAPI(self.mpv_manager, self.api_port)
        self.api_server.start(self.use_production_server)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[name-defined]
        # ensure mpv stops cleanly so resume position is saved
        self.mpv_manager.stop()
        return super().closeEvent(event)


@click.command()
@click.option(
    "--media-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True),
    help="Directory containing videos for mpv to playlist and autoplay.",
)
@click.option(
    "--api-port",
    default=5000,
    type=int,
    help="Port for the REST API server (default: 5000).",
)
@click.option(
    "--production-server",
    is_flag=True,
    help="Use production WSGI server (Gunicorn) instead of Flask development server.",
)
def main(media_dir: str, api_port: int, production_server: bool) -> None:
    # Qt Application
    app = QtWidgets.QApplication(sys.argv)
    # Make sure our central widget uses native windowing for --wid embedding
    app.setQuitOnLastWindowClosed(True)

    window = PlayerWindow(media_dir=media_dir, api_port=api_port, use_production_server=production_server)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


