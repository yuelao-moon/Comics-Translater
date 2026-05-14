import py_compile
for m in ['tui_app.py', 'tui_runner.py', 'tui_settings.py', 'tui_tasks.py',
           'mobi_options.py', 'packers.py', 'comics_enhance.py', 'waifu2x_enhancer.py',
           'epub_extractor.py', 'epub_packer.py', 'config.py']:
    path = fr'D:\Project\AI-Project\ComicsTanslater\ComicsEnhance\comics_enhance\{m}'
    try:
        py_compile.compile(path, doraise=True)
        print(f'OK: {m}')
    except py_compile.PyCompileError as e:
        print(f'FAIL: {m} - {e}')
