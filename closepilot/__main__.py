"""Main executable entrypoint for ClosePilot Continuous Finance Controller."""

import os
from closepilot.dashboard import run_dashboard

if __name__ == "__main__":
    port = int(os.environ.get("CLOSEPILOT_PORT", "8430"))
    host = os.environ.get("CLOSEPILOT_HOST", "127.0.0.1")
    open_browser = os.environ.get("CLOSEPILOT_NO_BROWSER", "0") != "1"
    run_dashboard(host=host, port=port, open_browser=open_browser)
