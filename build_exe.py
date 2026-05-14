"""Build standalone ComicsEnhance EXE via PyInstaller.

Usage:
  cd ComicsEnhance
  python build_exe.py

Requires PyInstaller:
  pip install pyinstaller

Output:
  dist/ComicsEnhance.exe     ← TUI (default)
  dist/comics-enhance.exe    ← CLI
"""

import os
import site
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.join(PROJECT_ROOT, "comics_enhance")

if not os.path.isdir(PACKAGE_DIR):
    print(f"ERROR: run from {os.path.basename(PROJECT_ROOT)} directory")
    sys.exit(1)


def _find_model_bins() -> list[str]:
    """Find all .bin model files from sr-vulkan model packages."""
    bins = []
    model_pkg_names = ["sr_vulkan_model_waifu2x", "sr_vulkan_model_realesrgan"]
    for sp in site.getsitepackages():
        for pkg in model_pkg_names:
            pkg_dir = os.path.join(sp, pkg, "models")
            if os.path.isdir(pkg_dir):
                for f in os.listdir(pkg_dir):
                    if f.endswith(".bin"):
                        bins.append(os.path.join(pkg_dir, f))
                        print(f"  model: {f}")
    return bins


def build(name: str, entry_script: str):
    """Build one EXE with PyInstaller."""
    import subprocess

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name", name,
        "--console",
        "--onefile",
        entry_script,
        # Pillow
        "--hidden-import", "PIL",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "PIL._webp",
        "--hidden-import", "PIL.JpegImagePlugin",
        "--hidden-import", "PIL.PngImagePlugin",
        "--hidden-import", "sqlite3",
        "--hidden-import", "textual",
        "--hidden-import", "textual.app",
        "--hidden-import", "textual.widgets",
        "--hidden-import", "textual.containers",
        # sr-vulkan (runtime detected)
        "--hidden-import", "sr_vulkan",
        "--hidden-import", "comics_enhance.kpf_generator",
        "--hidden-import", "comics_enhance.mobi_options",
        "--hidden-import", "comics_enhance.mobi_preprocessor",
        # Exclude bloat
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
    ]

    # Add sr-vulkan package dir
    try:
        import sr_vulkan
        vk_dir = os.path.dirname(sr_vulkan.__file__)
        cmd.append(f"--add-data={vk_dir};sr_vulkan")
        print(f"sr_vulkan: {vk_dir}")
    except ImportError:
        pass

    # Add model .bin files individually (PyInstaller needs explicit paths)
    model_bins = _find_model_bins()
    for mb in model_bins:
        cmd.append(f"--add-data={mb};.")

    # Add sr_vulkan_model_waifu2x pkg for model loading
    for sp in site.getsitepackages():
        for pkg in ["sr_vulkan_model_waifu2x", "sr_vulkan_model_realesrgan"]:
            pkg_dir = os.path.join(sp, pkg)
            if os.path.isdir(pkg_dir):
                cmd.append(f"--add-data={pkg_dir};{pkg}")
                print(f"{pkg}: {pkg_dir}")

    print(f"\nBuilding {name}...")
    cmd_str = " ".join(cmd)
    print(cmd_str[:200] + "...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        for line in result.stderr.splitlines():
            if "ERROR" in line:
                print(f"  {line}")
    else:
        # Check output
        dist_path = os.path.join(PROJECT_ROOT, "dist", f"{name}.exe")
        if os.path.isfile(dist_path):
            size_mb = os.path.getsize(dist_path) / (1024 * 1024)
            print(f"  OK: {dist_path} ({size_mb:.1f} MB)")
        else:
            print(f"  OK (check dist/{name}.exe)")


def run():
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("Installing PyInstaller...")
        os.system(f"{sys.executable} -m pip install pyinstaller")

    # Clean previous build output
    for d in ["build", "dist"]:
        d_path = os.path.join(PROJECT_ROOT, d)
        if os.path.isdir(d_path):
            import shutil
            shutil.rmtree(d_path, ignore_errors=True)
    for f in ["ComicsEnhance.spec", "comics-enhance.spec"]:
        f_path = os.path.join(PROJECT_ROOT, f)
        if os.path.isfile(f_path):
            os.remove(f_path)

    print("Model files to bundle:")
    model_bins = _find_model_bins()
    if model_bins:
        print(f"  Total: {len(model_bins)} .bin files")
    else:
        print("  (none — GPU models not installed)")
    print()

    # Build TUI
    build("ComicsEnhance", os.path.join(PACKAGE_DIR, "tui.py"))

    # Build CLI
    build("comics-enhance", os.path.join(PACKAGE_DIR, "comics_enhance.py"))

    print("\nDone!")


if __name__ == "__main__":
    run()
