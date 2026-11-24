"""Launch studio-api or emit its OpenAPI 3.1 document."""

import argparse
import json
from copy import deepcopy

import uvicorn
from uvicorn.config import LOGGING_CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    tasks = parser.add_subparsers(dest="task")
    serve = tasks.add_parser("serve", help="Serve the API (the default)")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", default=8000, type=int)
    tasks.add_parser("openapi", help="Print the versioned OpenAPI JSON")
    args = parser.parse_args()
    if args.task == "openapi":
        from .app import schema_app
        print(json.dumps(schema_app().openapi(), indent=2, sort_keys=True, allow_nan=False))
    else:
        from .transport import access_log

        # The app emits one access line with the request ID and path, without the query.
        log_config = deepcopy(LOGGING_CONFIG)
        log_config["handlers"]["studio_access"] = {
            "class": "logging.StreamHandler", "stream": "ext://sys.stdout",
        }
        log_config["loggers"][access_log.name] = {
            "handlers": ["studio_access"], "level": "INFO", "propagate": False,
        }
        uvicorn.run("haynes_studio.api.app:from_env", factory=True,
                    host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 8000),
                    access_log=False, log_config=log_config)


if __name__ == "__main__":
    main()
