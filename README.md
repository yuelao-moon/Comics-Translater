# ComicsEnhance

批量漫画处理工具：输入 → 解包提取图片 → 超分辨率增强 → 输出为 EPUB。

```
PDF/MOBI/AZW/EPUB/CBZ
         │
         ▼
  [Calibre 预处理]   ← 非 EPUB 格式需要
         │
         ▼
  [EPUB 图片提取]    ← 按阅读顺序提取所有图片
         │
         ▼
  [超分辨率增强]     ← GPU: Waifu2x/RealESRGAN, CPU: Pillow 多线程
         │
         ▼
  [EPUB 3 固定布局打包] ← 封面、阅读方向、分页
```

## 特性

- **多格式输入**: EPUB, MOBI, AZW, AZW3, PDF, CBZ, ZIP
- **GPU & CPU 双模**: sr-vulkan GPU 加速 或 Pillow LANCZOS CPU 多线程
- **13 种模型**: Waifu2x (Anime/Photo/CUNet × 去噪 0-3), RealESRGAN, RealCUGAN, RealSR, Pillow
- **EPUB 3 固定布局**: 支持日漫右翻/美漫左翻
- **打包为 EXE**: PyInstaller 打包，双击即用
- **自动清理**: 临时文件用完即删

## 安装

```bash
cd ComicsEnhance
pip install -e .
```

**可选依赖：**

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| sr-vulkan | GPU 加速超分辨率 | `pip install sr_vulkan-*.whl` |
| sr-vulkan-model-waifu2x | Waifu2x 模型文件 | `pip install sr-vulkan-model-waifu2x` |
| sr-vulkan-model-realesrgan | RealESRGAN 模型文件 | `pip install sr-vulkan-model-realesrgan` |
| Calibre | MOBI/AZW/PDF 预处理 | [calibre-ebook.com](https://calibre-ebook.com) |
| rich + questionary | TUI 交互界面 | `pip install rich questionary` |

## 打包为 EXE

```bash
python build_exe.py
```

输出两个单文件 EXE (`dist/`)：
- `ComicsEnhance.exe` — TUI 交互界面
- `comics-enhance.exe` — CLI 命令行工具

---

## 命令行用法

```
comics-enhance [全局选项] 文件1 [文件2 ...]
```

### 快速示例

```bash
comics-enhance manga.epub                           # 默认：anime-n3, 2x, 右翻
comics-enhance --model pillow manga.epub            # CPU 增强（黑白漫画推荐）
comics-enhance --model realesr-anime --tta *.epub   # RealESRGAN 高画质
comics-enhance --model anime-n1 manga.epub          # 弱去噪保留细节
comics-enhance --no-enhance manga.pdf               # 仅解包+打包
comics-enhance --output ./out *.epub *.mobi         # 批量 + 指定输出目录
```

### 完整选项

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `FILE` | 位置 | — | 一个或多个输入文件 |
| `--output` `-o` | 路径 | `.` | 输出目录 |
| `--direction` | `rtl`/`ltr` | `rtl` | 阅读方向 |
| `--language` `-l` | ISO 639-1 | `zh` | 书籍语言 |
| `--model` | 见下文 | `anime-n3` | 增强模型 |
| `--tta` | flag | off | TTA 模式，画质更好约 2x 更慢 |
| `--format` | `jpg`/`png`/`webp`/`bmp` | `jpg` | 输出图片格式 |
| `--tile-size` | int | `400` | GPU 分块大小 (0=自动) |
| `--no-enhance` | flag | off | 跳过增强仅解包打包 |

---

## 模型列表 & 推荐

### 🥇 黑白漫画推荐

```
pillow          Pillow 2x — CPU 多线程，输出 4:4:4 色度，体积大品质最高
pillow-4x       Pillow 4x — 同上，高倍放大
```

黑白漫画使用动画模型反而会引入人造纹理（过度平滑），Pillow LANCZOS 保留原汁原味的线条。

### 🥈 彩色漫画推荐

```
anime-n3        Waifu2x Anime 2x + 去噪 3（默认）
anime-n2        Waifu2x Anime 2x + 去噪 2（保留更多噪点）
realesr-anime   RealESRGAN AnimeVideoV3 2x（更现代，效果好）
```

### 🥉 照片类/写实风格

```
photo-n3        Waifu2x Photo 2x + 去噪 3
photo-n2        Waifu2x Photo 2x + 去噪 2
```

### 📐 高倍放大

```
realesr-anime-4x  RealESRGAN 4x — 一本漫画 → 150MB+，建议精装输出用
realesr-x4        RealESRGAN x4+ Anime 4x
pillow-4x         Pillow 4x — CPU，高色度质量
```

### 完整模型表

**Waifu2x（2x 缩放）** — `-nX` = 去噪 0-3

| 模型 | sr-vulkan ID | 去噪 | 适用 |
|------|-------------|------|------|
| `anime` | 18 | — | Anime 2x 基础 |
| `anime-n0` | 20 | 0 | + 无去噪 |
| `anime-n1` | 22 | 1 | + 弱去噪 |
| `anime-n2` | 24 | 2 | + 中去噪 |
| `anime-n3` | 26 | 3 | + 强去噪（默认） |
| `photo` ~ `photo-n3` | 28 ~ 36 | 0-3 | 照片模型 |
| `cunet` ~ `cunet-n3` | 8 ~ 16 | 0-3 | CUNet 模型 |

**RealESRGAN**

| 模型 | ID | 说明 |
|------|----|------|
| `realesr-anime` | 74 | AnimeVideoV3 2x |
| `realesr-anime-3x` | 76 | AnimeVideoV3 3x |
| `realesr-anime-4x` | 78 | AnimeVideoV3 4x |
| `realesr-x4` | 82 | x4+ Anime 4x |

**Pillow CPU**

| 模型 | 说明 |
|------|------|
| `pillow` | Pillow LANCZOS 2x (默认 4:4:4) |
| `pillow-4x` | Pillow LANCZOS 4x |

**其他**

| 模型 | ID | 说明 |
|------|----|------|
| `realcugan-pro-2x` | 38 | RealCUGAN Pro 2x |
| `realcugan-pro-d3` | 42 | RealCUGAN Pro 2x + 去噪 3 |
| `realcugan-pro-3x` | 44 | RealCUGAN Pro 3x |
| `realsr-4x` | 72 | RealSR DF2K 4x |

### `--tta` 选项

启用后 sr-vulkan 模型 ID +1（奇数），对每张图片做 4 种变换后取平均。

- **效果**: 画质最高，降低噪点、改善边缘
- **代价**: 约 2x 推理时间
- **适用**: 精品单本最终输出，不推荐批量

---

## TUI 交互界面

```
comics-tui
```

交互流程：
1. **选择文件** — 通配符批量选取
2. **选择模型** — 分组列表（CPU / Waifu2x Anime / Photo / RealESRGAN）
3. **配置选项** — TTA、格式、方向、语言、分块
4. **输出目录**
5. **确认** → 实时进度条

---

## 技术细节

### CPU 多线程策略

| 逻辑核心数 | 工作线程 | 策略 |
|-----------|---------|------|
| ≤4 | 全部 | 全核参与 |
| 5-8 | 核心-1 | 留给系统一个 |
| ≥9 | 8 | 上限 8 |

Pillow 底层 C 实现释放 GIL，多线程能有效并行利用多核。

### JPEG 色度采样（仅 Pillow 路径）

- Pillow 路径默认 4:4:4 (全色度)，体积大品质高
- sr-vulkan 路径输出由引擎编码决定
- `waifu2x_enhancer.py` 中可修改 `jpeg_quality` 和 `jpeg_subsampling`

### 输出文件命名

```
输入 1.mobi   →  1.epub
输入 manga.epub  →  manga.epub
```

与输入同名，请把 MOBI/PDF 源文件和输出 EPUB 放不同目录，避免覆盖。

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| Calibre conversion failed | Calibre 未安装 | [calibre-ebook.com](https://calibre-ebook.com) |
| No images found | 文件不含图片 | 解压 EPUB 确认 |
| GPU out of memory | 显存不足 | `--tile-size 200` |
| 速度慢 | 无 GPU | `--model pillow` CPU 多线程 |
| Batch submit failed: waifu2x not init | 模型包未装 | `pip install sr-vulkan-model-waifu2x` |
| TUI 依赖缺失 | rich/questionary 未装 | `pip install rich questionary` |
| comics-tui 找不到 | 未用系统 Python 安装 | `pip install -e .` 在系统 Python 下执行 |

## 项目结构

```
ComicsEnhance/
├── comics_enhance/
│   ├── __init__.py
│   ├── config.py            # 全局配置 + 22 种模型目录
│   ├── epub_extractor.py    # 多格式漫画图片提取
│   ├── waifu2x_enhancer.py  # GPU/CPU 增强 + 多线程
│   ├── epub_packer.py       # EPUB 3 固定布局打包
│   ├── comics_enhance.py    # CLI 入口
│   └── tui.py               # TUI 交互界面
├── setup.py                 # pip install
├── build_exe.py             # PyInstaller 打包脚本
├── requirements.txt
└── README.md
```

## 技术来源

- [kindle-comic-workaround](https://github.com/HankunYu/kindle-comic-workaround-5.19.x) — EPUB/MOBI/PDF 图片提取
- [JMComic-qt](https://github.com/tonquer/JMComic-qt) — sr-vulkan 调用模式
- [kindleunpack-calibre-plugin](https://github.com/dougmassay/kindleunpack-calibre-plugin) — MOBI 解包
- [sr-vulkan](https://github.com/tonquer/sr-vulkan) — Vulkan 超分辨率引擎

## License

MIT
