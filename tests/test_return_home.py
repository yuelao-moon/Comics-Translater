# -*- coding: utf-8 -*-
"""
Test: verify return_home() brings the app back to HomeScreen without black screen.
Run:
    python tests/test_return_home.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from textual.screen import Screen
from textual.widgets import Static
from textual.app import ComposeResult

from comics_enhance.tui_app import ComicsEnhanceApp, HomeScreen
from comics_enhance.tui_settings import load_settings


class _DummyScreen(Screen):
    """A minimal screen with no dependencies, used to build up stack depth."""
    def compose(self) -> ComposeResult:
        yield Static("dummy")


async def _run_test() -> None:
    settings = load_settings()
    app = ComicsEnhanceApp(settings=settings)

    async with app.run_test(headless=True, size=(120, 40)) as pilot:
        # 1. Initial screen should be HomeScreen
        assert isinstance(app.screen, HomeScreen), (
            "FAIL: initial screen should be HomeScreen, got " + type(app.screen).__name__
        )
        print("PASS: initial screen is HomeScreen")

        # 2. Push dummy screens to simulate deep stack (like after a full run)
        app.push_screen(_DummyScreen())
        await pilot.pause()
        app.push_screen(_DummyScreen())
        await pilot.pause()
        app.push_screen(_DummyScreen())
        await pilot.pause()

        depth_before = len(app.screen_stack)
        print("PASS: stack depth before return_home =", depth_before)
        assert depth_before == 5, "FAIL: expected stack depth 5, got " + str(depth_before)

        # 3. Call return_home() directly (same as what the button does)
        app.return_home()
        await pilot.pause(delay=0.3)

        # 4. Verify we are back on HomeScreen
        current_name = type(app.screen).__name__
        assert isinstance(app.screen, HomeScreen), (
            "FAIL: after return_home, screen should be HomeScreen, got " + current_name
        )
        print("PASS: after return_home, current screen is HomeScreen")

        # 5. Stack should be exactly 1 deep
        depth_after = len(app.screen_stack)
        assert depth_after == 2, (
            "FAIL: stack depth after return_home should be 2 (base+HomeScreen), got " + str(depth_after)
        )
        print("PASS: stack depth after return_home =", depth_after)

        print("")
        print("All tests passed. return_home works correctly.")
        app.exit()


def main() -> None:
    try:
        asyncio.run(_run_test())
    except AssertionError as e:
        print(str(e))
        sys.exit(1)
    except Exception as e:
        print("ERROR: " + str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
