"""YamlConfidenceHighlighter / SqlHighlighter が正しい位置に書式を適用することを検証する。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from highlighters import YamlConfidenceHighlighter, SqlHighlighter

_app = QApplication.instance() or QApplication([])


def _format_at(doc: QTextDocument, block_no: int, offset: int) -> dict | None:
    """指定オフセットの書式を、その場でプリミティブ値に変換して返す。

    PySide6ではQTextLayout.FormatRange.formatが軽量なプロキシで、式を跨いで保持すると
    (libshiboken: Internal C++ object already deleted) になるため、ここで値を取り出しきる。
    """
    block = doc.findBlockByNumber(block_no)
    layout = block.layout()
    for fr in layout.formats():
        if fr.start <= offset < fr.start + fr.length:
            f = fr.format
            return {
                "fg": f.foreground().color().name(),
                "bg": f.background().color().name(),
                "bold": f.fontWeight() > 50,
            }
    return None


def _highlight(highlighter_cls, text: str) -> QTextDocument:
    doc = QTextDocument()
    highlighter = highlighter_cls(doc)
    doc.setPlainText(text)
    highlighter.rehighlight()
    doc._highlighter = highlighter  # GC避け
    return doc


# ---------- YamlConfidenceHighlighter ----------


def test_confidence_high_is_highlighted():
    line = "    table: users  # 確信度: 高（一致 3/3）"
    doc = _highlight(YamlConfidenceHighlighter, line)
    idx = line.index("確信度")
    fmt = _format_at(doc, 0, idx)
    assert fmt is not None
    assert fmt["fg"] == "#1b7a1b"


def test_confidence_medium_is_highlighted():
    line = "    table: users  # 確信度: 中（一致 2/3）"
    doc = _highlight(YamlConfidenceHighlighter, line)
    idx = line.index("確信度")
    fmt = _format_at(doc, 0, idx)
    assert fmt["fg"] == "#b36b00"


def test_confidence_low_is_highlighted():
    line = "    table: __FILL_ME_IN__  # 確信度: 低（一致するテーブルが見つかりませんでした）"
    doc = _highlight(YamlConfidenceHighlighter, line)
    idx = line.index("確信度")
    fmt = _format_at(doc, 0, idx)
    assert fmt["fg"] == "#c0392b"


def test_placeholder_marker_is_highlighted():
    line = "    table: __FILL_ME_IN__"
    doc = _highlight(YamlConfidenceHighlighter, line)
    idx = line.index("__FILL_ME_IN__")
    fmt = _format_at(doc, 0, idx)
    assert fmt["bg"] == "#c0392b"


def test_yaml_key_is_highlighted():
    line = "operations:"
    doc = _highlight(YamlConfidenceHighlighter, line)
    fmt = _format_at(doc, 0, 0)
    assert fmt is not None
    assert fmt["bold"] is True


def test_plain_line_without_confidence_has_no_confidence_format():
    line = "    engine: postgres"
    doc = _highlight(YamlConfidenceHighlighter, line)
    # "engine"部分はキー書式(青)であって、確信度書式(緑/橙/赤)ではないこと
    fmt = _format_at(doc, 0, 4)
    assert fmt["fg"] not in ("#1b7a1b", "#b36b00", "#c0392b")


# ---------- SqlHighlighter ----------


def test_sql_warning_comment_is_highlighted():
    line = '-- WARNING: "orders"."status" にCHECK制約があります'
    doc = _highlight(SqlHighlighter, line)
    idx = line.index("WARNING")
    fmt = _format_at(doc, 0, idx)
    assert fmt["bg"] == "#c0392b"


def test_sql_normal_comment_is_not_warning_colored():
    line = "-- 自動生成された雛形です"
    doc = _highlight(SqlHighlighter, line)
    fmt = _format_at(doc, 0, 3)
    assert fmt["fg"] == "#6a6a6a"
    assert fmt["bg"] != "#c0392b"


def test_sql_keyword_is_highlighted():
    line = 'INSERT INTO "users" ("id") VALUES (1);'
    doc = _highlight(SqlHighlighter, line)
    idx = line.index("INSERT")
    fmt = _format_at(doc, 0, idx)
    assert fmt["fg"] == "#1f5fa8"


def test_sql_string_literal_is_highlighted():
    line = "INSERT INTO users (name) VALUES ('placeholder_name');"
    doc = _highlight(SqlHighlighter, line)
    idx = line.index("'placeholder_name'") + 1
    fmt = _format_at(doc, 0, idx)
    assert fmt["fg"] == "#2f7d32"
