"""Build SmartEnergyAssistant.exe for Windows using PyInstaller.

Run from the repository root:

    python scripts/build_windows.py

or double-click scripts/build_windows.bat.

Output: dist/SmartEnergyAssistant.exe (single-file, windowed, no console).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
EXE_NAME = "SmartEnergyAssistant"

# --- Relative paths (src -> dest inside the bundle) ---------------------------
DATAS = [
    (ROOT / "frontend", "frontend"),
    (ROOT / "backend" / "config", "backend/config"),
]

HIDDEN_IMPORTS = [
    # uvicorn dynamically imports its loop/protocol/lifespan implementations
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.middleware.wsgi",
    "uvicorn.middleware.asgi2",
    "uvicorn.logging",
    "websockets",
    "httptools",
    "httpx",
    "httpcore",
    "sqlalchemy.dialects.sqlite",
]

# Heavy / unused packages that must not bloat the EXE. They exist in
# requirements.txt for development tooling but are imported nowhere at runtime.
EXCLUDES = [
    "pandas",
    "numpy",
    "scipy",
    "sklearn",
    "joblib",
    "matplotlib",
    "pytest",
    "PIL",
    "watchfiles",
    "PyInstaller",
]


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build] Installing PyInstaller ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"]
        )


def main() -> int:
    ensure_pyinstaller()

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        EXE_NAME,
        "--paths",
        str(ROOT),
    ]
    for src, dest in DATAS:
        args += ["--add-data", f"{src}{os.pathsep}{dest}"]
    for mod in HIDDEN_IMPORTS:
        args += ["--hidden-import", mod]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    # pydantic ships compiled cores and optional submodules loaded dynamically
    args += [
        "--collect-submodules",
        "pydantic",
        "--copy-metadata",
        "pydantic",
        "--copy-metadata",
        "pydantic-settings",
        "--collect-submodules",
        "fastapi",
        "--collect-submodules",
        "uvicorn",
    ]
    args.append(str(ROOT / "launcher.py"))

    print(f"[build] Working dir : {ROOT}")
    print(f"[build] Output       : {DIST / (EXE_NAME + '.exe')}")
    subprocess.check_call(args, cwd=str(ROOT))

    exe = DIST / f"{EXE_NAME}.exe"
    if not exe.exists():
        print(f"[build] FAILED: expected output {exe} not found")
        return 1

    print(f"[build] DONE: {exe} ({exe.stat().st_size / 1_000_000:.1f} MB)")
    print("        Verify from a directory OUTSIDE the repo, e.g.:")
    print("        copy dist\\SmartEnergyAssistant.exe path\\to\\other\\folder")
    return 0


if __name__ == "__main__":
    sys.exit(main())