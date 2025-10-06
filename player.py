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
            "--save-position-on-quit=yes",
            f"--input-ipc-server={self._ipc_path}",
            "--keep-open=no",
            "--idle=no",
            "--no-osd-bar",  # Hide OSD bar
            "--no-input-default-bindings",  # Disable default key bindings
            "--no-input-vo-keyboard",  # Disable keyboard input
            "--no-input-cursor",  # Disable cursor input
            "--cursor-autohide=no",  # Keep cursor hidden
            # Force GPU VO and disable hwdec overlays so Qt overlays stay on top
            "--vo=x11",
            "--hwdec=no",
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

    def pause(self) -> bool:
        return self._send_ipc_command(["set", "pause", True])

    def resume(self) -> bool:
        return self._send_ipc_command(["set", "pause", False])

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


class OverlayBanner(QtWidgets.QFrame):
    """
    Banner widget to render text (static or scrolling) or image/GIF.
    Used for bottom and right overlays.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        palette = self.palette()
        # Opaque background to prevent underlying video from bleeding through
        palette.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 255))
        self.setPalette(palette)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        self._stack = QtWidgets.QStackedWidget(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # Text view
        self._text_container = QtWidgets.QWidget(self)
        text_layout = QtWidgets.QHBoxLayout(self._text_container)
        text_layout.setContentsMargins(12, 6, 12, 6)
        self._text_label = QtWidgets.QLabel(self._text_container)
        self._text_label.setStyleSheet("color: white; font-size: 20px;")
        self._text_label.setWordWrap(False)
        text_layout.addWidget(self._text_label)

        # Image view (supports GIF via QMovie)
        self._image_container = QtWidgets.QWidget(self)
        img_layout = QtWidgets.QHBoxLayout(self._image_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        self._image_label = QtWidgets.QLabel(self._image_container)
        self._image_label.setAlignment(QtCore.Qt.AlignCenter)
        img_layout.addWidget(self._image_label)

        self._stack.addWidget(self._text_container)
        self._stack.addWidget(self._image_container)

        # Marquee timer
        self._marquee_timer = QtCore.QTimer(self)
        self._marquee_timer.timeout.connect(self._tick_marquee)
        self._marquee_enabled = False
        self._marquee_pos = 0

        # Auto-hide timer
        self._autohide_timer = QtCore.QTimer(self)
        self._autohide_timer.setSingleShot(True)
        self._autohide_timer.timeout.connect(self.hide)

        self.hide()

    def show_text(self, text: str, scroll: bool = False, duration_s: Optional[int] = None) -> None:
        self._stack.setCurrentWidget(self._text_container)
        self._text_label.setText(text)
        self._marquee_enabled = scroll
        self._marquee_pos = 0
        if scroll:
            self._marquee_timer.start(30)
        else:
            self._marquee_timer.stop()
        self._set_autohide(duration_s)
        self.show()
        self.update()

    def show_image(self, path: str, duration_s: Optional[int] = 10) -> None:
        if path.lower().endswith((".gif",)):
            movie = QtGui.QMovie(path)
            self._image_label.setMovie(movie)
            movie.start()
        else:
            pix = QtGui.QPixmap(path)
            if not pix.isNull():
                self._image_label.setPixmap(
                    pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                )
        self._stack.setCurrentWidget(self._image_container)
        self._marquee_timer.stop()
        self._set_autohide(duration_s)
        self.show()
        self.update()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[name-defined]
        if self._stack.currentWidget() is self._image_container and self._image_label.pixmap() is not None:
            pix = self._image_label.pixmap()
            if pix is not None:
                self._image_label.setPixmap(
                    pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                )
        return super().resizeEvent(event)

    def _tick_marquee(self) -> None:
        if not self._marquee_enabled:
            return
        text = self._text_label.text()
        metrics = self._text_label.fontMetrics()
        text_width = metrics.horizontalAdvance(text) + 100
        self._marquee_pos = (self._marquee_pos + 2) % max(1, text_width)
        self._text_label.setStyleSheet(
            f"color: white; font-size: 20px; margin-left: {-self._marquee_pos}px;"
        )

    def _set_autohide(self, duration_s: Optional[int]) -> None:
        self._autohide_timer.stop()
        if duration_s is not None and duration_s > 0:
            self._autohide_timer.start(int(duration_s * 1000))


class UiBridge(QtCore.QObject):
    showOverlayRequested = QtCore.pyqtSignal(dict)
    hideOverlayRequested = QtCore.pyqtSignal(object)


class MediaPlayerAPI:
    """REST API server for controlling the media player"""
    
    def __init__(self, mpv_manager: MpvProcessManager, bridge: UiBridge, port: int = 5000):
        self.mpv_manager = mpv_manager
        self.bridge = bridge
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

        @self.app.route('/show-overlay', methods=['POST'])
        def show_overlay():
            data = request.get_json() or {}
            # Expected: position: bottom|side, type: image|text, content: path or text, optional duration, scroll
            self.bridge.showOverlayRequested.emit(data)
            return jsonify({"success": True})

        @self.app.route('/hide-overlay', methods=['POST'])
        def hide_overlay():
            data = request.get_json() or {}
            position = data.get('position')  # None, 'bottom', or 'side'
            self.bridge.hideOverlayRequested.emit(position)
            return jsonify({"success": True})

        @self.app.route('/play-interrupt-ad', methods=['POST'])
        def play_interrupt_ad():
            data = request.get_json() or {}
            ad_file = data.get('file')
            if not ad_file or not os.path.exists(ad_file):
                return jsonify({"success": False, "error": "Ad file not found"}), 400
            # Emit signal to UI/main thread to run interrupt ad flow
            QtCore.QMetaObject.invokeMethod(
                self.bridge,  # use bridge to hop to UI thread via PlayerWindow method
                "objectName",
                QtCore.Qt.QueuedConnection
            )
            # Store path globally in app context to be consumed by UI
            self.app.config['INTERRUPT_AD_FILE'] = ad_file
            QtCore.QTimer.singleShot(0, lambda: self.bridge.parent().play_interrupt_ad(ad_file) if self.bridge.parent() else None)
            return jsonify({"success": True})
    
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
    def __init__(self, media_dir: str, api_port: int = 5000, use_production_server: bool = False, demo_overlays: bool = False) -> None:
        super().__init__()
        self.media_dir = media_dir
        self.mpv_manager = MpvProcessManager(self)
        self.bridge = UiBridge()
        self.api_port = api_port
        self.use_production_server = use_production_server
        self.api_server = None
        self.demo_overlays = demo_overlays

        self.setWindowTitle("MPV Player")
        self.setCursor(QtCore.Qt.BlankCursor)  # kiosk-like
        self.setContentsMargins(0, 0, 0, 0)

        # Central composite layout to allow right/bottom overlays while video resizes
        central = QtWidgets.QWidget(self)
        central.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(central)

        self.outer_v = QtWidgets.QVBoxLayout(central)
        self.outer_v.setContentsMargins(0, 0, 0, 0)
        self.outer_v.setSpacing(0)

        top_row = QtWidgets.QWidget(central)
        top_row_layout = QtWidgets.QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(0)

        # Video host on the left of top row
        self.video_host = QtWidgets.QWidget(top_row)
        self.video_host.setContentsMargins(0, 0, 0, 0)

        # Right overlay container
        self.right_overlay = OverlayBanner(top_row)
        self.right_overlay.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.right_overlay.setFixedWidth(240)
        self.right_overlay.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding
        )
        self.right_overlay.hide()

        top_row_layout.addWidget(self.video_host, 1)
        top_row_layout.addWidget(self.right_overlay, 0)

        # Bottom overlay container
        self.bottom_overlay = OverlayBanner(central)
        self.bottom_overlay.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.bottom_overlay.setFixedHeight(96)
        self.bottom_overlay.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.bottom_overlay.hide()

        self.outer_v.addWidget(top_row, 1)
        self.outer_v.addWidget(self.bottom_overlay, 0)

        # Go fullscreen and start mpv once window has a native id
        self.showFullScreen()
        QtCore.QTimer.singleShot(0, self._start_mpv_once_visible)

        # Bridge: connect API thread signals to UI handlers
        self.bridge.showOverlayRequested.connect(self._on_show_overlay)
        self.bridge.hideOverlayRequested.connect(self._on_hide_overlay)

    def _start_mpv_once_visible(self) -> None:
        # Ensure native window is created
        self.video_host.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.video_host.winId()  # force native handle creation

        # Determine the correct wid to embed into: use the video_host's id
        wid = int(self.video_host.winId())
        self.mpv_manager.start(wid=wid, media_dir=self.media_dir)
        
        # Start the API server after MPV is running
        QtCore.QTimer.singleShot(2000, self._start_api_server)  # Wait 2 seconds for MPV to start
        # Optional: start demo overlays shortly after start
        if self.demo_overlays:
            QtCore.QTimer.singleShot(3000, self._demo_show_overlays)
    
    def _start_api_server(self) -> None:
        """Start the REST API server"""
        self.api_server = MediaPlayerAPI(self.mpv_manager, self.bridge, self.api_port)
        self.api_server.start(self.use_production_server)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[name-defined]
        # ensure mpv stops cleanly so resume position is saved
        self.mpv_manager.stop()
        return super().closeEvent(event)

    # ===== Overlay controls on UI thread =====
    def _on_show_overlay(self, payload: dict) -> None:
        position = payload.get("position", "bottom")
        ad_type = payload.get("type", "text")
        content = payload.get("content", "")
        duration = payload.get("duration")
        scroll = bool(payload.get("scroll", False))
        width = payload.get("width")
        height = payload.get("height")

        target = self.bottom_overlay if position == "bottom" else self.right_overlay
        # Apply requested size to reserve layout space like TV banners
        if position == "bottom" and isinstance(height, int) and height > 40:
            self.bottom_overlay.setFixedHeight(height)
        if position == "side" and isinstance(width, int) and width > 80:
            self.right_overlay.setFixedWidth(width)
        if ad_type == "text":
            target.show_text(str(content), scroll=scroll, duration_s=duration)
        else:
            target.show_image(str(content), duration_s=duration if duration is not None else 10)
        target.show()
        # Ensure stacking and layout update (overlays are native so they sit above mpv child window)
        target.raise_()
        self.video_host.lower()
        self.outer_v.invalidate()
        self.outer_v.update()
        target.update()

    def _demo_show_overlays(self) -> None:
        # Show a side image ad and a bottom ticker like TV
        self._on_show_overlay({
            "position": "side",
            "type": "image",
            "content": os.path.abspath(os.path.join(os.path.dirname(__file__), "tests", "media", "test.png")),
            "width": 240,
            "duration": 15,
        })
        self._on_show_overlay({
            "position": "bottom",
            "type": "text",
            "content": "Now Playing: Demo — Tonight 9PM New Episode | Visit example.com",
            "scroll": True,
            "height": 96,
            "duration": 20,
        })

    def _on_hide_overlay(self, position: Optional[str]) -> None:
        if position is None:
            self.bottom_overlay.hide()
            self.right_overlay.hide()
        elif position == "bottom":
            self.bottom_overlay.hide()
        elif position == "side":
            self.right_overlay.hide()

    # ===== Interrupt Ad flow =====
    def play_interrupt_ad(self, ad_path: str) -> None:
        # Pause main playback
        self.mpv_manager.pause()
        # Launch a separate mpv in fullscreen on top for the ad
        args = [
            "mpv",
            ad_path,
            "--fullscreen=yes",
            "--keep-open=no",
            "--idle=no",
            "--no-osd-bar",
            "--no-input-default-bindings",
            "--no-input-vo-keyboard",
            "--no-input-cursor",
            "--cursor-autohide=yes",
            "--vo=x11",
            "--hwdec=no",
            "--speed=1",
            "--quiet",
            "--really-quiet",
        ]
        ad_proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )

        # Poll until ad process exits, then resume main
        def _wait_and_resume():
            ad_proc.wait()
            # Hide any overlays that might have been shown for the ad
            QtCore.QTimer.singleShot(0, lambda: self._on_hide_overlay(None))
            self.mpv_manager.resume()

        threading.Thread(target=_wait_and_resume, daemon=True).start()


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
@click.option(
    "--demo-overlays",
    is_flag=True,
    help="Show a demo side image ad and bottom ticker automatically.",
)
def main(media_dir: str, api_port: int, production_server: bool, demo_overlays: bool) -> None:
    # Qt Application
    app = QtWidgets.QApplication(sys.argv)
    # Make sure our central widget uses native windowing for --wid embedding
    app.setQuitOnLastWindowClosed(True)

    window = PlayerWindow(media_dir=media_dir, api_port=api_port, use_production_server=production_server, demo_overlays=demo_overlays)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


