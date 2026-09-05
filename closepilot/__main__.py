"""Main executable entrypoint for ClosePilot Continuous Finance Controller."""

import os
from closepilot.dashboard import run_dashboard

if __name__ == "__main__":
    # PaaS platforms (Render, Railway, Fly) inject PORT and require binding all
    # interfaces. When PORT is absent we are on a local machine and the safe
    # default is loopback only.
    _platform_port = os.environ.get("PORT")
    port = int(_platform_port or os.environ.get("CLOSEPILOT_PORT", "8430"))
    host = os.environ.get(
        "CLOSEPILOT_HOST",
        "0.0.0.0" if _platform_port else "127.0.0.1",
    )
    open_browser = os.environ.get("CLOSEPILOT_NO_BROWSER", "0") != "1"
    run_dashboard(host=host, port=port, open_browser=open_browser)
