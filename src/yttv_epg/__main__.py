from __future__ import annotations

import argparse

import uvicorn

from yttv_epg.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="YTTV Sports Deeplink Aggregator")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()
    uvicorn.run("yttv_epg.app:app", host=args.host, port=args.port, factory=False)


if __name__ == "__main__":
    main()
