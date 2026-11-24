"""Serve scoped Studio tools over MCP Streamable HTTP."""

import argparse
import os

import httpx
import uvicorn

from .server import LOCAL_HOSTS, create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--allowed-host", action="append", metavar="HOST",
                        help="Allow this HTTP Host (including port when present). Repeat for more.")
    parser.add_argument("--allowed-origin", action="append", metavar="ORIGIN",
                        help="Allow this Origin header. Repeat for more.")
    options = parser.parse_args()
    upstream = os.getenv("STUDIO_API_URL")
    if not upstream:
        parser.error("STUDIO_API_URL is required")
    try:
        app = create_app(upstream, allowed_hosts=tuple(options.allowed_host or LOCAL_HOSTS),
                         allowed_origins=tuple(options.allowed_origin or ()))
    except (ValueError, httpx.InvalidURL):
        parser.error("STUDIO_API_URL must be an HTTP(S) origin")
    uvicorn.run(app, host=options.host, port=options.port, access_log=False)


if __name__ == "__main__":
    main()
