"""VMIC Editor - desktop entry point.

Starts the local tile server and opens a native window pointing at it.
File open/save use the OS's native dialogs (so we get real file paths, which
is what lets us read multi-gigabyte slides lazily from disk).

Run:
    pip install -r requirements.txt
    # place an OpenSeadragon build in static/vendor/openseadragon/ (see README)
    python app.py
"""

import socket
import threading

import webview

import server


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api:
    """Exposed to the page as window.pywebview.api for native dialogs."""

    def __init__(self):
        self.window = None

    def open_vmic(self):
        res = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('VMIC slides (*.vmic)', 'All files (*.*)'),
        )
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    def pick_save_vmic(self, default_name='rotated.vmic'):
        res = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_name,
            file_types=('VMIC slides (*.vmic)', 'All files (*.*)'),
        )
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    def pick_dir(self):
        res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res


def main():
    port = _free_port()
    threading.Thread(target=server.run_server, args=(port,), daemon=True).start()

    api = Api()
    window = webview.create_window(
        'VMIC Editor',
        'http://127.0.0.1:%d/' % port,
        width=1320, height=880, js_api=api,
    )
    api.window = window
    webview.start()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
