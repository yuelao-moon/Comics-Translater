import unittest

from comics_enhance.tui_app import ComicsEnhanceApp, HomeScreen, MobiKfxOptionsPanel
from comics_enhance.tui_tasks import TaskConfig, TaskMode
from comics_enhance.tui_settings import TuiSettings


class TextualAppTests(unittest.TestCase):
    def test_app_initializes_with_home_screen_and_settings(self):
        settings = TuiSettings.default(work_dir="C:/tmp/comics")
        app = ComicsEnhanceApp(settings=settings)

        self.assertIs(app.settings, settings)
        self.assertEqual(app.CSS_PATH, None)
        self.assertIn(("q", "quit", "退出"), app.BINDINGS)

    def test_home_screen_can_be_constructed(self):
        screen = HomeScreen()

        self.assertIsNotNone(screen)

    def test_mobi_kfx_options_panel_is_rendered_for_selected_formats(self):
        settings = TuiSettings.default(work_dir="C:/tmp/comics")
        config = TaskConfig.from_settings(TaskMode.FULL, ["C:/tmp/book.cbz"], settings)
        config.output_formats = ["mobi", "kfx"]

        panel = MobiKfxOptionsPanel(config)

        self.assertTrue(panel.show_mobi)
        self.assertTrue(panel.show_kfx)


if __name__ == "__main__":
    unittest.main()
