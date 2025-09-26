import os
import sys
import time
import socket
import shutil
import subprocess
from typing import Optional

import click

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

    def _send_ipc_quit(self, timeout_s: float = 1.5) -> bool:
        if not os.path.exists(self._ipc_path):
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout_s)
                s.connect(self._ipc_path)
                payload = '{"command":["quit"]}\n'.encode("utf-8")
                s.sendall(payload)
                return True
        except Exception:
            return False

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


class PlayerWindow(QtWidgets.QMainWindow):
    def __init__(self, media_dir: str) -> None:
        super().__init__()
        self.media_dir = media_dir
        self.mpv_manager = MpvProcessManager(self)

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
def main(media_dir: str) -> None:
    # Qt Application
    app = QtWidgets.QApplication(sys.argv)
    # Make sure our central widget uses native windowing for --wid embedding
    app.setQuitOnLastWindowClosed(True)

    window = PlayerWindow(media_dir=media_dir)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


