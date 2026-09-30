from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from .core import BuildOptions, ForgeError, build_motion_photo, inspect_template


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wechat-live")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser(
        "inspect", help="Inspect a native phone Motion Photo template"
    )
    inspect.add_argument("template")

    build = subparsers.add_parser(
        "build", help="Build a WeChat-compatible Motion Photo"
    )
    build.add_argument(
        "--template", required=True, help="Native Motion Photo from the target phone"
    )
    build.add_argument("--cover", required=True, help="Cover image")
    build.add_argument("--video", required=True, help="Motion video")
    build.add_argument("--output", help="Output JPG; defaults to IMGyyyyMMddHHmmss.jpg")
    build.add_argument("--start", type=float, default=0.0)
    build.add_argument("--duration", type=float)
    build.add_argument(
        "--key-time", type=float, help="Cover position inside output video, in seconds"
    )
    build.add_argument("--mode", choices=("crop", "fit"), default="crop")
    build.add_argument("--cover-rotate", type=int, choices=(0, 90, 180, 270), default=0)
    build.add_argument("--video-rotate", type=int, choices=(0, 90, 180, 270), default=0)
    build.add_argument("--crf", type=int, default=18)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            print(
                json.dumps(
                    inspect_template(args.template).to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        output = args.output or f"IMG{datetime.now().astimezone():%Y%m%d%H%M%S}.jpg"
        result = build_motion_photo(
            template=args.template,
            cover=args.cover,
            video=args.video,
            output=output,
            options=BuildOptions(
                start=args.start,
                duration=args.duration,
                key_time=args.key_time,
                crop_mode=args.mode,
                cover_rotation=args.cover_rotate,
                video_rotation=args.video_rotate,
                crf=args.crf,
            ),
        )
        print(
            json.dumps(
                {
                    "output": str(result.output.resolve()),
                    "sha256": result.sha256,
                    "video_length": result.video_length,
                    "trailer_length": result.trailer_length,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
