import os
import sys
import threading
import webbrowser
import time
from app import app

def open_browser():
    """Open browser after a short delay"""
    time.sleep(1.5)
    webbrowser.open_new('http://localhost:5000/')

def start_app():
    """Start the Flask application"""
    # Ensure app runs on a specific port
    port = 5000
    
    # Open browser in a separate thread
    threading.Timer(1, open_browser).start()
    
    # Disable Flask's reloader when running as executable
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    # Check if running as PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Set the application path to the directory containing the executable
        application_path = os.path.dirname(sys.executable)
        os.chdir(application_path)
    
    start_app()
