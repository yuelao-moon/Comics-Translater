"""Setup for ComicsEnhance - Batch comic unpack, enhance, and repack."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="comics-enhance",
    version="0.1.0",
    author="ComicsEnhance",
    description="Batch comic/manga processing: unpack, Waifu2x enhance, repack as EPUB/CBZ/MOBI/KFX",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    install_requires=[
        "Pillow>=10.0.0",
    ],
    extras_require={
        "tui": ["rich>=13.0", "textual>=0.89"],
        "gpu": ["sr-vulkan"],
    },
    entry_points={
        "console_scripts": [
            "comics-enhance=comics_enhance.comics_enhance:main",
            "comics-tui=comics_enhance.tui:tui_main",
        ],
    },
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
