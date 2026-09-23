"""Windows cmd.exe 向けのコマンドライン引数エスケープ。

src/renderer/excel_output.py（生成時点のcurlコマンドプレビュー）と runner/http_client.py
（実行時点の実際に送信されたcurlコマンド相当の記録）の両方で、curl.exe を含む一般的な
Windows プログラムが従う MSVCRT 互換の argv パース規則が必要なため、ここに一本化する。
"""
from __future__ import annotations


def escape_cmd_arg(value: str) -> str:
    """Windows cmd.exe 上でダブルクォート引数として渡す値をエスケープする（引用符は付与しない）。

    curl.exe のような一般的な Windows プログラムは MSVCRT 互換の argv パース規則
    （N 個の連続する \\ の直後に " が続く場合、\\ は N//2 個に圧縮され、N が奇数なら
    リテラル " が1つ挿入される）でコマンドラインを解釈するため、その規則に従って
    " と \\ をエスケープする。これにより外部入力（openapi.json 由来の値）で
    ダブルクォートを脱出してコマンドを注入できないようにする。

    戻り値は常にダブルクォートで囲んで使う前提（quote_cmd_arg参照）。末尾の連続する \\ は
    直後に閉じ引用符が続くことを前提に2倍にする（そうしないと閉じ引用符自体をエスケープ
    してしまい、引数の境界がずれる）。
    """
    result: list[str] = []
    n_backslashes = 0
    for ch in value:
        if ch == "\\":
            n_backslashes += 1
            continue
        if ch == '"':
            result.append("\\" * (n_backslashes * 2 + 1))
            result.append('"')
        else:
            if n_backslashes:
                result.append("\\" * n_backslashes)
            result.append(ch)
        n_backslashes = 0
    if n_backslashes:
        result.append("\\" * (n_backslashes * 2))
    return "".join(result)


def quote_cmd_arg(value: str) -> str:
    return '"' + escape_cmd_arg(value) + '"'
