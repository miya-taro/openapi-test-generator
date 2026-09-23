from src.cmd_escape import escape_cmd_arg, quote_cmd_arg


def test_plain_value_unchanged():
    assert escape_cmd_arg("hello") == "hello"


def test_quote_is_escaped():
    assert escape_cmd_arg('a"b') == 'a\\"b'


def test_backslash_before_quote_is_doubled_then_quote_escaped():
    # \" は「1個の\ + "」なので、N=1(奇数)により \\ が1個(N//2=0個)+リテラル" になる規則。
    # つまり元の1個の\は2個(N*2+1=1*2+1=3個の\、うち最後の1個は"のエスケープ用)に展開される。
    assert escape_cmd_arg('a\\"b') == 'a\\\\\\"b'


def test_trailing_backslashes_are_doubled():
    # 戻り値は常にダブルクォートで囲んで使われる前提のため、末尾の連続する\は
    # 直後の閉じ引用符をエスケープしてしまわないよう2倍にする必要がある
    # （回帰テスト: quote_cmd_arg で実際に囲んだ結果をMSVCRT規則で逆読みして検証する）。
    assert escape_cmd_arg("C:\\") == "C:\\\\"


def test_quote_cmd_arg_wraps_in_quotes():
    assert quote_cmd_arg("hello world") == '"hello world"'


def test_quote_cmd_arg_trailing_backslash_round_trips_correctly():
    """末尾が\\の値をquote_cmd_argで囲んだ結果が、MSVCRT規則で正しく1個の\\として
    読み戻せること（閉じ引用符を巻き込んで引数境界が壊れるバグの回帰テスト）。"""
    quoted = quote_cmd_arg("C:\\")
    assert quoted == '"C:\\\\"'
    # MSVCRT規則で読み戻す: 開き" → C: → \\ (2個の\は1個に圧縮、直後の"が終端) → 終端
    inner = quoted[1:-1]  # ダブルクォートを剥がす
    assert inner == "C:\\\\"  # 2個の\（1個のリテラル\に対応）


def test_double_quote_wraps_and_escapes_together():
    assert quote_cmd_arg('secret" & calc.exe & "') == '"secret\\" & calc.exe & \\""'
