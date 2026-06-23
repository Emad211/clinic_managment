import sys
import os
import threading

# Ensure the project root is importable (both source and frozen modes).
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    sys.path.insert(0, BASE_DIR)
    if hasattr(sys, '_MEIPASS'):
        sys.path.insert(0, sys._MEIPASS)
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    sys.path.insert(0, BASE_DIR)

from src.app import create_app, open_browser
from src.config.settings import Config

if __name__ == '__main__':
    app = create_app()
    threading.Timer(1.5, open_browser).start()
    app.run(debug=False,
            host=('127.0.0.1' if app.config.get('PRODUCTION') else '0.0.0.0'),
            port=Config.PORT, use_reloader=False, threaded=True)
