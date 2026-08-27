"""
build_portable.py
=================
Creates a portable USB deployment of the Abrechnung Editor.

This script:
1. Downloads Python 3.12 embeddable package
2. Installs pip into it
3. Installs all required packages
4. Copies the app source and templates
5. Creates a batch launcher

Result: A 'portable/' folder that can be copied to USB and run on any Win PC.
"""

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# ── Config ────────────────────────────────────────────────────────────────────

PYTHON_VERSION = "3.12.10"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTABLE_DIR = os.path.join(SCRIPT_DIR, "portable")
PYTHON_DIR = os.path.join(PORTABLE_DIR, "python")
APP_DIR = os.path.join(PORTABLE_DIR, "app")

PACKAGES = [
    "PyQt5",
    "pypdfium2",
    "pikepdf",
    "reportlab",
    "opencv-python-headless",
    "numpy",
    "Pillow",
]


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def download(url, dest):
    print(f"  Downloading {url.split('/')[-1]} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  -> Saved to {dest}")


def main():
    # ── Clean previous build ──────────────────────────────────────────
    if os.path.exists(PORTABLE_DIR):
        step("Cleaning previous portable build")
        shutil.rmtree(PORTABLE_DIR)
    os.makedirs(PYTHON_DIR, exist_ok=True)
    os.makedirs(APP_DIR, exist_ok=True)

    # ── Download & extract Python embeddable ──────────────────────────
    step(f"Downloading Python {PYTHON_VERSION} embeddable")
    zip_path = os.path.join(PORTABLE_DIR, "python_embed.zip")
    download(PYTHON_EMBED_URL, zip_path)

    print("  Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(PYTHON_DIR)
    os.remove(zip_path)

    # ── Enable pip (edit python3XX._pth) ──────────────────────────────
    step("Enabling pip in embeddable Python")
    pth_files = [f for f in os.listdir(PYTHON_DIR)
                 if f.endswith("._pth")]
    if not pth_files:
        print("ERROR: No ._pth file found!")
        return
    pth_file = os.path.join(PYTHON_DIR, pth_files[0])
    with open(pth_file, 'r') as f:
        content = f.read()
    # Uncomment 'import site' and add Lib/site-packages
    content = content.replace("#import site", "import site")
    if "Lib\\site-packages" not in content:
        content += "\nLib\\site-packages\n"
    # Add the app directory to the path
    content += "..\\app\n"
    with open(pth_file, 'w') as f:
        f.write(content)
    print(f"  Updated {pth_files[0]}")

    # ── Install pip ───────────────────────────────────────────────────
    step("Installing pip")
    get_pip_path = os.path.join(PORTABLE_DIR, "get-pip.py")
    download(GET_PIP_URL, get_pip_path)

    python_exe = os.path.join(PYTHON_DIR, "python.exe")
    subprocess.run(
        [python_exe, get_pip_path, "--no-warn-script-location"],
        check=True
    )
    os.remove(get_pip_path)

    # ── Install packages ──────────────────────────────────────────────
    step("Installing packages")
    # Use 'python -m pip' (not Scripts/pip.exe) — on Windows embeddable,
    # pip.exe may resolve to the system Python and install in the wrong place.
    subprocess.run(
        [python_exe, "-m", "pip", "install"] + PACKAGES
        + ["--no-warn-script-location"],
        check=True
    )

    # ── Copy app source ───────────────────────────────────────────────
    step("Copying app source")

    # Copy pdf_editor package
    src_pkg = os.path.join(SCRIPT_DIR, "pdf_editor")
    dst_pkg = os.path.join(APP_DIR, "pdf_editor")
    shutil.copytree(src_pkg, dst_pkg,
                    ignore=shutil.ignore_patterns(
                        '__pycache__', '*.pyc', '.vscode'))
    print(f"  Copied pdf_editor/")

    # Copy main.py
    shutil.copy2(os.path.join(SCRIPT_DIR, "main.py"),
                 os.path.join(APP_DIR, "main.py"))
    print(f"  Copied main.py")

    # Copy files/ (blank template)
    src_files = os.path.join(SCRIPT_DIR, "files")
    dst_files = os.path.join(APP_DIR, "files")
    shutil.copytree(src_files, dst_files)
    print(f"  Copied files/")

    # ── Create batch launcher ─────────────────────────────────────────
    step("Creating launcher")

    bat_content = '''@echo off
title Brutto-Netto-Abrechnung Editor
cd /d "%~dp0"
start "" "python\\pythonw.exe" "app\\main.py"
'''
    bat_path = os.path.join(PORTABLE_DIR, "Abrechnung starten.bat")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    print(f"  Created: Abrechnung starten.bat")

    # ── Also create a debug launcher (with console) ───────────────────
    bat_debug = '''@echo off
title Brutto-Netto-Abrechnung Editor (Debug)
cd /d "%~dp0"
"python\\python.exe" "app\\main.py"
pause
'''
    bat_debug_path = os.path.join(PORTABLE_DIR, "Abrechnung starten (Debug).bat")
    with open(bat_debug_path, 'w', encoding='utf-8') as f:
        f.write(bat_debug)
    print(f"  Created: Abrechnung starten (Debug).bat")

    # ── Summary ───────────────────────────────────────────────────────
    step("BUILD COMPLETE!")

    total_size = 0
    for dirpath, dirnames, filenames in os.walk(PORTABLE_DIR):
        for f in filenames:
            total_size += os.path.getsize(os.path.join(dirpath, f))
    size_mb = total_size / (1024 * 1024)

    print(f"""
  Output:  {PORTABLE_DIR}
  Size:    {size_mb:.0f} MB

  To deploy:
    1. Copy the entire 'portable' folder to your USB drive
    2. On any Windows PC, double-click 'Abrechnung starten.bat'
    3. No installation needed!

  Debug mode:
    Use 'Abrechnung starten (Debug).bat' to see error messages
""")


if __name__ == "__main__":
    main()
