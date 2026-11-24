"""Launch studio-api or emit its OpenAPI 3.1 document."""

import argparse
import json

import uvicorn


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
        # Access logs could contain OIDC callback query strings (code and state).
        uvicorn.run("haynes_studio.api.app:from_env", factory=True,
                    host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 8000),
                    access_log=False)


if __name__ == "__main__":
    main()
