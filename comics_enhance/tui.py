#!/usr/bin/env python3
"""Compatibility entrypoint for the Textual TUI."""

from comics_enhance.tui_app import run_tui


def tui_main() -> None:
    run_tui()


if __name__ == "__main__":
    tui_main()
