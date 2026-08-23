"""生成結果プレビュー欄（編集可能）用のシンタックスハイライト。

一般的なYAML/SQLの色分けというより、「危ない箇所を目立たせる」ことを優先している:
mapping.yamlの確信度コメント（高/中/低）、setup.sqlのWARNINGコメントを最優先で強調する。
"""
from __future__ import annotations
import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _fmt(color: str, bold: bool = False, background: str | None = None) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if background:
        fmt.setBackground(QColor(background))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


class YamlConfidenceHighlighter(QSyntaxHighlighter):
    """mapping.yaml / scenarios.generated.yaml 向け。

    確信度コメント（高=緑/中=橙/低=赤）を最優先で強調し、その上で
    通常のYAMLコメント・キー・文字列に軽く色を付ける。
    """

    _COMMENT_RE = QRegularExpression(r"#.*$")
    _KEY_RE = QRegularExpression(r"^\s*[\w.\-]+(?=:)")
    _STRING_RE = QRegularExpression(r"'[^']*'|\"[^\"]*\"")

    _CONFIDENCE_HIGH_RE = QRegularExpression(r"確信度[：:]\s*高.*$")
    _CONFIDENCE_MEDIUM_RE = QRegularExpression(r"確信度[：:]\s*中.*$")
    _CONFIDENCE_LOW_RE = QRegularExpression(r"確信度[：:]\s*低.*$")
    _PLACEHOLDER_RE = QRegularExpression(r"__FILL_ME_IN__")

    def __init__(self, document) -> None:
        super().__init__(document)
        # プレビューエディタの地の背景は#0f172a（ほぼ黒）のため、明るい背景向けの
        # 暗い色（旧: #6a6a6a/#1f5fa8/#2f7d32）だと逆に地の文より読みにくくなる。
        self._comment_fmt = _fmt("#94a3b8")
        self._key_fmt = _fmt("#7dd3fc", bold=True)
        self._string_fmt = _fmt("#86efac")
        self._high_fmt = _fmt("#1b7a1b", bold=True, background="#e2efda")
        self._medium_fmt = _fmt("#b36b00", bold=True, background="#fff2cc")
        self._low_fmt = _fmt("#c0392b", bold=True, background="#fce4d6")
        self._placeholder_fmt = _fmt("#ffffff", bold=True, background="#c0392b")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qtのオーバーライド規約
        self._apply(self._KEY_RE, text, self._key_fmt)
        self._apply(self._STRING_RE, text, self._string_fmt)
        self._apply(self._COMMENT_RE, text, self._comment_fmt)
        # 確信度・プレースホルダは通常コメントより優先して上書きする
        self._apply(self._CONFIDENCE_HIGH_RE, text, self._high_fmt)
        self._apply(self._CONFIDENCE_MEDIUM_RE, text, self._medium_fmt)
        self._apply(self._CONFIDENCE_LOW_RE, text, self._low_fmt)
        self._apply(self._PLACEHOLDER_RE, text, self._placeholder_fmt)

    def _apply(self, pattern: QRegularExpression, text: str, fmt: QTextCharFormat) -> None:
        it = pattern.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


_SQL_KEYWORDS = (
    r"\b(INSERT|INTO|VALUES|TRUNCATE|TABLE|CASCADE|RESTART|IDENTITY|SELECT|FROM|WHERE|"
    r"AND|OR|NULL|NOT|DEFAULT|NOW|CURRENT_DATE)\b"
)


class SqlHighlighter(QSyntaxHighlighter):
    """setup.sql.generated / teardown.sql.generated 向け。

    WARNINGコメント（CHECK制約を自動で満たせなかった箇所）を最優先で強調する。
    """

    _COMMENT_RE = QRegularExpression(r"--.*$")
    _WARNING_RE = QRegularExpression(r"--\s*WARNING.*$")
    _STRING_RE = QRegularExpression(r"'(?:[^']|'')*'")
    _KEYWORD_RE = QRegularExpression(_SQL_KEYWORDS, QRegularExpression.PatternOption.CaseInsensitiveOption)

    def __init__(self, document) -> None:
        super().__init__(document)
        self._comment_fmt = _fmt("#94a3b8")
        self._string_fmt = _fmt("#86efac")
        self._keyword_fmt = _fmt("#7dd3fc", bold=True)
        self._warning_fmt = _fmt("#ffffff", bold=True, background="#c0392b")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qtのオーバーライド規約
        self._apply(self._KEYWORD_RE, text, self._keyword_fmt)
        self._apply(self._STRING_RE, text, self._string_fmt)
        self._apply(self._COMMENT_RE, text, self._comment_fmt)
        self._apply(self._WARNING_RE, text, self._warning_fmt)

    def _apply(self, pattern: QRegularExpression, text: str, fmt: QTextCharFormat) -> None:
        it = pattern.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
