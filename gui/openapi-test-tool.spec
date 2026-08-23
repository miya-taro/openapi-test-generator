# -*- mode: python ; coding: utf-8 -*-
"""PyInstallerビルド定義。リポジトリ直下で `pyinstaller gui/openapi-test-tool.spec` を実行する。

GUIは各機能をsrc/・runner/配下のCLIスクリプトへのサブプロセス呼び出しとして実装している
（gui/app.py の _script_cmd 参照）。exe化するとsys.executableはこのexe自身になるため、
`--exec-script <script.py> <args...>` で自分自身を再起動し、その場でスクリプトを実行する
モードに分岐させている。そのためsrc/・runner/のソース一式（.pyファイル）をdatasとして
まるごと同梱する必要がある（コンパイル済みモジュールとしてではなく、実ファイルとして）。

--onedir（フォルダ形式）でビルドする。--onefileにすると、ボタンを押すたびに
サブプロセスとして自分自身を再起動する構造上、クリックのたびに一時展開が走って
毎回もたつくため、起動が一瞬で済むonedirを採用している。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - PyInstallerがspec実行時に注入するグローバル


def _collect_py_tree(src_dir: Path) -> list[tuple[str, str]]:
    """src_dir配下の.pyファイルを、tests/と__pycache__を除いてdatasタプルに変換する。"""
    entries: list[tuple[str, str]] = []
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in py_file.parts or "tests" in py_file.parts:
            continue
        rel_dir = py_file.parent.relative_to(REPO_ROOT)
        entries.append((str(py_file), str(rel_dir)))
    return entries


datas = []
datas += _collect_py_tree(REPO_ROOT / "src")
datas += _collect_py_tree(REPO_ROOT / "runner")
datas += [(str(REPO_ROOT / "gui" / "style.qss"), "gui")]
datas += [(str(REPO_ROOT / "gui" / "assets"), "gui/assets")]

hiddenimports = [
    "psycopg2", "psycopg2.extras", "influxdb", "yaml", "exrex", "jsonschema",
]
hiddenimports += collect_submodules("openpyxl")

a = Analysis(  # noqa: F821 - PyInstallerのspec実行時グローバル
    [str(REPO_ROOT / "gui" / "app.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "gui")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openapi-test-tool",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(REPO_ROOT / "gui" / "assets" / "icon.ico"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="openapi-test-tool",
)
