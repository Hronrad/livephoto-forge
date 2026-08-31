from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
STAMP = VENV / ".wechat-motion-photo-installed"


def main() -> int:
    if sys.version_info < (3, 10):  # noqa: UP036 - launcher runs before package install
        print("需要 Python 3.10 或更高版本。请升级 Python 后重新运行。")
        return 2
    if not PYTHON.exists():
        print("首次启动：正在创建本地 Python 环境…")
        venv.EnvBuilder(with_pip=True).create(VENV)
    source_time = max(
        (ROOT / "pyproject.toml").stat().st_mtime, Path(__file__).stat().st_mtime
    )
    if not STAMP.exists() or STAMP.stat().st_mtime < source_time:
        print("正在安装 WebUI 依赖…")
        subprocess.check_call([str(PYTHON), "-m", "pip", "install", "-e", str(ROOT)])
        STAMP.touch()
    try:
        return subprocess.call(
            [str(PYTHON), "-m", "wechat_motion_photo.web", *sys.argv[1:]]
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
