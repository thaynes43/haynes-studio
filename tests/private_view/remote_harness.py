"""Local-only HTTP double for the literal in-container private-view program.

The filesystem program is unmodified. Only urllib's API boundary is faked; no socket
or kubectl process is started. argv holds the exact fixed source and separate data.
"""
import io
import json
import pathlib
import sys
import urllib.request

code, action, root, raw = sys.argv[1:]


def open_url(url, **kwargs):
    ledger_id = url.split("/videos/", 1)[1].split("/", 1)[0]
    document = json.loads((pathlib.Path(root) / "jobs" / (ledger_id + ".json")).read_bytes())
    response = io.BytesIO((pathlib.Path(root) / "output" / document["output"]).read_bytes())
    response.status = 200
    response.headers = {"Content-Type": "video/mp4"}
    return response


urllib.request.urlopen = open_url
sys.argv = ["private-view", action, root, raw]
exec(compile(code, "<fixed-private-view-program>", "exec"), {"__name__": "__main__"})
