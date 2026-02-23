"""
Run any API service locally for development.

Usage:
    python api/run_local.py outbound_trigger          # port 8010
    python api/run_local.py outbound_trigger --port 9000
"""

import argparse
import importlib
import sys
from pathlib import Path

SERVICE_PORTS = {
    "outbound_trigger": 8010,
}


def main():
    parser = argparse.ArgumentParser(description="Run an API service locally")
    parser.add_argument("service", choices=list(SERVICE_PORTS.keys()), help="Service to run")
    parser.add_argument("--port", type=int, default=None, help="Port override")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    args = parser.parse_args()

    port = args.port or SERVICE_PORTS[args.service]

    # Add project root to path so `api.common` imports work
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required for local dev: pip install uvicorn")
        sys.exit(1)

    module_path = f"api.{args.service}.main"
    print(f"Starting {args.service} on http://{args.host}:{port}")
    print(f"Docs: http://{args.host}:{port}/docs")

    uvicorn.run(f"{module_path}:app", host=args.host, port=port, reload=True)


if __name__ == "__main__":
    main()
