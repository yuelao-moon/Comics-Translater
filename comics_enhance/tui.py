#!/usr/bin/env python3
"""ComicsEnhance TUI — Interactive terminal interface for batch comic processing.

Dependencies: rich, questionary
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ── Import optional TUI deps; exit early if missing ──

_MISSING_DEPS = []
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.table import Table
    from rich.panel import Panel
    _rich_ok = True
except ImportError:
    _rich_ok = False
    _MISSING_DEPS.append("rich")

try:
    import questionary
    _q_ok = True
except ImportError:
    _q_ok = False
    _MISSING_DEPS.append("questionary")

# App imports (always available)
from comics_enhance.config import (
    MODEL_CATALOG, DEFAULT_MODEL, WAIFU2X_TILE_SIZE,
    WAIFU2X_OUTPUT_FORMAT, SUPPORTED_INPUT_FORMATS,
    get_model_id, model_description, is_pillow_model,
    find_calibre_debug, ensure_dirs,
)
from comics_enhance.epub_extractor import extract_images, extract_metadata
from comics_enhance.waifu2x_enhancer import is_waifu2x_available, enhance_images_batch
from comics_enhance.epub_packer import pack_epub


# ── Singletons (lazy, after install check) ──

_console = None  # set in _init_console()


def _init_console():
    global _console
    if _console is None:
        _console = Console() if _rich_ok else None


def _ok_rich():
    return _rich_ok


def _ok_q():
    return _q_ok


# ── Deps helper ──

def _install_missing_deps():
    import subprocess
    deps = []
    if not _rich_ok:
        deps.append("rich")
    if not _q_ok:
        deps.append("questionary")
    if deps:
        print(f"安装缺失依赖: {' '.join(deps)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + deps,
            stdout=sys.stdout, stderr=sys.stderr,
        )
        print("\n依赖安装完成。请重新运行 comics-tui。")
        sys.exit(0)


# ── Output helpers ──

def _print_header():
    _init_console()
    if _console:
        _console.print()
        _console.print(Panel.fit(
            "[bold cyan]ComicsEnhance[/] — 漫画批量处理工具\n"
            "解包 → 超分辨率增强 → EPUB3 打包",
            border_style="cyan",
        ))
    else:
        print("\n=== ComicsEnhance — 漫画批量处理工具 ===\n")


def _print_step(msg: str):
    _init_console()
    if _console:
        _console.print(f"  [bold yellow]▸[/] {msg}")
    else:
        print(f"  > {msg}")


def _print_table(title: str, rows: list[tuple[str, str]]):
    _init_console()
    if _console:
        table = Table(title=title, show_header=False)
        table.add_column(style="dim")
        table.add_column()
        for k, v in rows:
            table.add_row(k, str(v))
        _console.print(table)
    else:
        print(f"\n=== {title} ===")
        for k, v in rows:
            print(f"  {k}: {v}")
        print()


# ── Interactive selectors (safe wrappers around questionary) ──

def _q_text(msg: str, default: str = "") -> str:
    if _ok_q():
        return questionary.text(msg, default=default).unsafe_ask() or ""
    return input(f"{msg} ").strip()


def _q_confirm(msg: str, default: bool = True) -> bool:
    if _ok_q():
        return questionary.confirm(msg, default=default).unsafe_ask()
    return input(f"{msg} [{'Y/n' if default else 'y/N'}]: ").strip().lower() in ("", "y", "yes")


def _q_select(msg: str, choices: list, default=None) -> str:
    if _ok_q():
        return questionary.select(msg, choices=choices, default=default).unsafe_ask()
    # Plain fallback
    print(f"\n{msg}")
    for i, c in enumerate(choices):
        if isinstance(c, str):
            print(f"  [{i}] {c}")
        else:
            print(f"  [{i}] {c}")
    sel = input(f"选择 [0-{len(choices)-1}]: ").strip()
    try:
        idx = int(sel)
        if 0 <= idx < len(choices):
            c = choices[idx]
            if hasattr(c, 'value'):
                return c.value
            return c
    except ValueError:
        pass
    return default or ""


def _select_files() -> list[str]:
    import glob
    while True:
        raw = _q_text("输入文件路径（空格分隔，支持 *.epub 通配符）:")
        if not raw:
            return []
        files = []
        for part in raw.strip().split():
            for f in glob.glob(part):
                if Path(f).is_file() and Path(f).suffix.lower() in SUPPORTED_INPUT_FORMATS:
                    files.append(os.path.abspath(f))
        if not files:
            _print_step("无匹配文件，请重试")
            continue
        _init_console()
        if _console:
            table = Table(title="已选文件", style="cyan")
            table.add_column("#", style="dim")
            table.add_column("路径")
            for i, f in enumerate(files, 1):
                table.add_row(str(i), f)
            _console.print(table)
        else:
            print(f"\n已选文件 ({len(files)}):")
            for i, f in enumerate(files, 1):
                print(f"  [{i}] {f}")
        if _q_confirm(f"共 {len(files)} 个文件，确认？"):
            return files


def _select_model() -> str:
    if not _ok_q():
        print("\n模型列表:")
        for name in sorted(MODEL_CATALOG.keys()):
            print(f"  {name:25s} — {MODEL_CATALOG[name]['desc']}")
        while True:
            choice = input(f"\n模型名（默认 {DEFAULT_MODEL}）: ").strip()
            if not choice:
                return DEFAULT_MODEL
            if choice in MODEL_CATALOG:
                return choice
            print(f"  未知模型: {choice}")

    groups = [
        ("CPU (Pillow)", [n for n in MODEL_CATALOG if n.startswith("pillow")]),
        ("Separator", []),
        ("Waifu2x Anime", [n for n in MODEL_CATALOG if n.startswith("anime")]),
        ("Waifu2x Photo", [n for n in MODEL_CATALOG if n.startswith("photo")]),
        ("Waifu2x CUNet", [n for n in MODEL_CATALOG if n.startswith("cunet")]),
        ("RealESRGAN", [n for n in MODEL_CATALOG if n.startswith("realesr")]),
        ("RealCUGAN / RealSR", [n for n in MODEL_CATALOG if n.startswith(("realcugan", "realsr"))]),
    ]
    choices = []
    for grp_name, names in groups:
        if names:
            choices.append(questionary.Separator(f"── {grp_name} ──"))
            for n in sorted(names):
                choices.append(questionary.Choice(
                    title=f"{n:25s} {MODEL_CATALOG[n]['desc']}",
                    value=n,
                ))
    result = questionary.select(
        "选择增强模型:", choices=choices, default=DEFAULT_MODEL, use_indicator=True,
    ).unsafe_ask()
    return result or DEFAULT_MODEL


def _select_output() -> str:
    if _ok_q():
        path = questionary.path(
            "输出目录:", default=os.path.join(os.getcwd(), "output"),
            only_directories=True,
        ).unsafe_ask()
        if path is None:
            return "."
        os.makedirs(path, exist_ok=True)
        return path
    path = input("输出目录（默认: ./output）: ").strip()
    if not path:
        path = "./output"
    os.makedirs(path, exist_ok=True)
    return path


def _configure_options() -> dict:
    opts = {
        "tta": False, "format": WAIFU2X_OUTPUT_FORMAT,
        "tile_size": WAIFU2X_TILE_SIZE, "direction": "rtl",
        "language": "zh", "no_enhance": False,
    }
    if _ok_q():
        opts["tta"] = questionary.confirm("TTA 模式（更高画质, ~2x 更慢）?", default=False).unsafe_ask()
        opts["format"] = questionary.select(
            "输出图片格式:", choices=["jpg", "png", "webp", "bmp"], default="jpg"
        ).unsafe_ask() or "jpg"
        opts["direction"] = questionary.select(
            "阅读方向:", choices=[
                questionary.Choice("日漫 从右到左 (rtl)", "rtl"),
                questionary.Choice("美漫 从左到右 (ltr)", "ltr"),
            ], default="rtl"
        ).unsafe_ask() or "rtl"
        opts["language"] = questionary.select(
            "书籍语言:", choices=["zh", "ja", "en", "ko"], default="zh"
        ).unsafe_ask() or "zh"
        tsize = questionary.text("GPU tile size（0=自动, 400=默认）:", default="400").unsafe_ask()
        try:
            opts["tile_size"] = int(tsize) if tsize else 400
        except (ValueError, TypeError):
            opts["tile_size"] = 400
        opts["no_enhance"] = questionary.confirm("跳过画质增强（仅解包+打包）?", default=False).unsafe_ask()
    else:
        opts["tta"] = input("TTA? [y/N]: ").strip().lower() == "y"
        fmt = input(f"格式 [{WAIFU2X_OUTPUT_FORMAT}]: ").strip()
        if fmt:
            opts["format"] = fmt
        dr = input("方向 rtl/ltr [rtl]: ").strip()
        if dr in ("ltr", "rtl"):
            opts["direction"] = dr
        lang = input("语言 [zh]: ").strip()
        if lang:
            opts["language"] = lang
        opts["no_enhance"] = input("跳过增强? [y/N]: ").strip().lower() == "y"
    return opts


def _model_scale_from_name(name: str) -> int:
    if "4x" in name or "-4x" in name:
        return 4
    if "3x" in name or "-3x" in name:
        return 3
    return 2


# ── Processing ──

def _process_files(files, model_name, output_dir, opts):
    total_files = len(files)
    success = 0
    fail = 0
    has_gpu = is_waifu2x_available()
    has_calibre = find_calibre_debug() is not None

    _print_table("处理配置", [
        ("文件数", total_files),
        ("模型", model_description(model_name)),
        ("缩放", f"{_model_scale_from_name(model_name)}x"),
        ("TTA", "开" if opts["tta"] else "关"),
        ("格式", opts["format"]),
        ("输出", output_dir),
        ("GPU", "可用" if has_gpu else "不可用 (CPU fallback)"),
        ("Calibre", "可用" if has_calibre else "不可用"),
    ])

    if not _q_confirm("确认开始处理?"):
        _print_step("已取消")
        return

    total_start = time.time()
    model_id = get_model_id(model_name)
    force_pillow = is_pillow_model(model_name)
    effective_scale = _model_scale_from_name(model_name)

    for file_idx, input_file in enumerate(files, 1):
        input_name = Path(input_file).stem
        ext = Path(input_file).suffix.lower()
        basename = os.path.basename(input_file)

        _init_console()
        if _console:
            _console.print()
            _console.rule(f"[cyan]{file_idx}/{total_files}  {basename}")
        else:
            print(f"\n--- [{file_idx}/{total_files}] {basename} ---")

        if ext not in SUPPORTED_INPUT_FORMATS:
            _print_step(f"跳过: 不支持的格式 '{ext}'")
            fail += 1
            continue
        if ext not in {".epub", ".cbz", ".zip"} and not has_calibre:
            _print_step("跳过: Calibre 未安装")
            fail += 1
            continue

        tmp_root = tempfile.mkdtemp(prefix=f"comics_enhance_{input_name}_")
        try:
            _print_step("提取图片...")
            image_dir = os.path.join(tmp_root, "extracted")
            start_t = time.time()
            image_paths, _ = extract_images(input_file, image_dir, tmp_dir=tmp_root)
            extract_t = time.time() - start_t
            _print_step(f"提取到 {len(image_paths)} 张 ({extract_t:.1f}s)")

            enhanced_dir = os.path.join(tmp_root, "enhanced")
            if not opts["no_enhance"]:
                _print_step(f"增强中 ({model_description(model_name)})...")
                if _rich_ok:
                    _init_console()
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                        console=_console,
                    ) as progress:
                        task = progress.add_task(
                            f"[cyan]{len(image_paths)} images", total=len(image_paths)
                        )

                        def pb(current, total_, path):
                            progress.update(task, completed=current)

                        enhanced_paths = enhance_images_batch(
                            image_paths=image_paths, output_dir=enhanced_dir,
                            model=model_id, scale=effective_scale,
                            output_format=opts["format"],
                            tile_size=opts["tile_size"], tta=opts["tta"],
                            force_pillow=is_pillow_model(model_name),
                            progress_callback=pb,
                        )
                else:
                    enhanced_paths = enhance_images_batch(
                        image_paths=image_paths, output_dir=enhanced_dir,
                        model=model_id, scale=effective_scale,
                        output_format=opts["format"],
                        tile_size=opts["tile_size"], tta=opts["tta"],
                        force_pillow=is_pillow_model(model_name),
                    )
            else:
                enhanced_paths = image_paths
                _print_step("跳过增强")

            _print_step("打包 EPUB...")
            metadata = extract_metadata(input_file)
            epub_name = f"{input_name}.epub"
            epub_path = os.path.join(output_dir, epub_name)

            start_t = time.time()
            pack_epub(
                image_paths=enhanced_paths, output_path=epub_path,
                title=metadata.get("title", input_name),
                author=metadata.get("author", ""),
                language=opts["language"],
                reading_direction=opts["direction"],
            )
            pack_t = time.time() - start_t
            epub_mb = os.path.getsize(epub_path) / (1024 * 1024)
            _print_step(f"完成: {epub_path} ({epub_mb:.1f} MB, {pack_t:.1f}s)")
            success += 1

        except Exception as e:
            _print_step(f"错误: {e}")
            import traceback
            traceback.print_exc()
            fail += 1
        finally:
            try:
                shutil.rmtree(tmp_root, ignore_errors=True)
            except Exception:
                pass

    total_t = time.time() - total_start
    _print_table("完成", [
        ("成功", success), ("失败", fail), ("耗时", f"{total_t:.1f}s"),
    ])


# ── Main ──

def tui_main():
    """Run the interactive TUI."""
    # Fast path: missing deps → install & exit
    if _MISSING_DEPS:
        print(f"缺少依赖: {', '.join(_MISSING_DEPS)}")
        if questionary is None:
            confirm = input("输入 y 自动安装: ").strip().lower()
        else:
            confirm = questionary.confirm(
                f"缺少依赖: {', '.join(_MISSING_DEPS)}. 自动安装?",
                default=True,
            ).unsafe_ask()
        if confirm in (True, "y", "yes"):
            _install_missing_deps()
        else:
            sys.exit(1)

    ensure_dirs()
    _print_header()

    gpu_ok = is_waifu2x_available()
    calibre_ok = find_calibre_debug() is not None
    _print_table("环境检测", [
        ("GPU 加速", "可用" if gpu_ok else "不可用 (CPU fallback)"),
        ("Calibre", "可用" if calibre_ok else "不可用 (MOBI/PDF 会失败)"),
    ])

    while True:
        if _ok_q():
            action = questionary.select(
                "操作:",
                choices=[
                    questionary.Choice("📁 选择文件并开始处理", "process"),
                    questionary.Separator(),
                    questionary.Choice("🚪 退出", "quit"),
                ],
            ).unsafe_ask()
        else:
            print("\n操作: [p]处理  [q]退出")
            a = input("> ").strip().lower()
            if a in ("p", ""):
                action = "process"
            elif a == "q":
                action = "quit"
            else:
                action = "quit"

        if action == "quit" or action is None:
            break

        files = _select_files()
        if not files:
            _print_step("未选择文件")
            continue

        model_name = _select_model()
        opts = _configure_options()
        output_dir = _select_output()

        _print_table("处理确认", [
            ("文件", f"{len(files)} 个"),
            ("模型", model_description(model_name)),
            ("缩放", f"{_model_scale_from_name(model_name)}x"),
            ("TTA", "开" if opts["tta"] else "关"),
            ("格式", opts["format"]),
            ("方向", opts["direction"]),
            ("输出", output_dir),
            ("增强", "跳过" if opts["no_enhance"] else "启用"),
        ])
        _init_console()
        if _console:
            _console.print("[dim]文件列表:[/]")
            for f in files:
                _console.print(f"  [dim]•[/] {os.path.basename(f)}")

        if not _q_confirm("确认开始处理？"):
            _print_step("已取消")
            continue

        _process_files(files, model_name, output_dir, opts)

        if not _q_confirm("\n继续处理其他文件?"):
            break

    print("\nComicsEnhance TUI 已退出.\n")


if __name__ == "__main__":
    tui_main()
