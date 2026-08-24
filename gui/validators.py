"""GUIの「入力を確認」ボタンから使う、各種設定ファイルの事前検証。

実際の生成・実行と同じ検証ロジック（src.parser.parse_openapi / config_loader /
auth_login.load_auth_config / db_scenario.load_scenarios）をそのまま呼び出す。
独自に検証ルールを再実装すると、実行時のエラーメッセージと食い違う恐れがあるため。
"""
from __future__ import annotations
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "runner")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _missing_or_blank(path: str, required: bool) -> str | None:
    if not path:
        return None if not required else "NG: 未入力です"
    if not Path(path).exists():
        return "NG: ファイルが見つかりません"
    return None


def validate_openapi(path: str, required: bool = True) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"

    from src.parser import parse_openapi, OpenAPIParseError

    try:
        openapi = parse_openapi(path)
    except OpenAPIParseError as e:
        return f"NG: {e}"

    op_count = sum(
        1
        for item in (openapi.get("paths") or {}).values()
        if isinstance(item, dict)
        for m in item
        if m in ("get", "post", "put", "patch", "delete")
    )
    return f"OK（operation数: {op_count}）"


_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def list_operations(path: str) -> list[dict]:
    """openapi.jsonに定義されているoperation一覧を返す（GUIのAPI選択リスト用）。

    [{"operationId": ..., "method": "GET", "path": "/users/{id}"}, ...] の形。
    operationIdが無いoperationは、--operations/--exclude-opsで指定しようがないため除く。
    パースできない場合は空リストを返す（呼び出し側はエラーダイアログを別途出す）。
    """
    if not path or not Path(path).exists():
        return []

    from src.parser import parse_openapi, OpenAPIParseError

    try:
        openapi = parse_openapi(path)
    except OpenAPIParseError:
        return []

    operations: list[dict] = []
    for p, item in (openapi.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if not op_id:
                continue
            operations.append({"operationId": op_id, "method": method.upper(), "path": p})
    return operations


def validate_db_config(path: str, required: bool = True) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"

    from config_loader import load_config, get_postgres_config, get_influxdb_config

    try:
        data = load_config(path)
    except (FileNotFoundError, ValueError) as e:
        return f"NG: {e}"

    sections = []
    if "postgres" in data:
        try:
            get_postgres_config(data)
            sections.append("postgres: OK")
        except ValueError as e:
            sections.append(f"postgres: NG（{e}）")
    if "influxdb" in data:
        try:
            get_influxdb_config(data)
            sections.append("influxdb: OK")
        except ValueError as e:
            sections.append(f"influxdb: NG（{e}）")

    if not sections:
        return "NG: postgres/influxdb のいずれのセクションもありません"
    return "OK（" + " / ".join(sections) + "）"


def validate_auth_config(path: str, required: bool = False) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"

    from auth_login import load_auth_config, AuthLoginError

    try:
        cfg = load_auth_config(path)
    except AuthLoginError as e:
        return f"NG: {e}"
    return f"OK（login_url: {cfg.get('login_url')}）"


def validate_scenarios_yaml(path: str, required: bool = True) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"
    return validate_scenarios_yaml_text(Path(path).read_text(encoding="utf-8"))


def validate_scenarios_yaml_text(text: str) -> str:
    """parse_scenarios()と同じ検証を、ファイルではなくテキストに対して行う。

    GUIの編集中プレビュー（未保存の内容）をその場で検証するために使う。
    """
    if not text.strip():
        return "（空です）"

    from db_scenario import parse_scenarios, ScenarioError

    try:
        scenarios = parse_scenarios(text)
    except ScenarioError as e:
        return f"NG: {e}"
    return f"OK（{len(scenarios)}件のシナリオ）"


def validate_mapping_yaml(path: str, required: bool = True) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"
    return validate_mapping_yaml_text(Path(path).read_text(encoding="utf-8"))


def validate_mapping_yaml_text(text: str) -> str:
    """generate_mapping.pyの出力（"operations"キーを持つYAML）と同じ形式かを、
    ファイルではなくテキストに対して検証する。GUIの編集中プレビューの検証に使う。
    """
    if not text.strip():
        return "（空です）"

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return f"NG: YAML解析に失敗しました: {e}"

    if not isinstance(data, dict) or "operations" not in data:
        return 'NG: "operations" キーがありません'
    operations = data["operations"]
    if not isinstance(operations, dict):
        return 'NG: "operations" はオブジェクトである必要があります'
    return f"OK（{len(operations)}件のoperation対応）"


def _run_sql_against_db(sql_text: str, config_path: str, timeout: int, commit: bool) -> str:
    """setup.sql/teardown.sqlをPostgreSQLへ流す共通処理。

    commit=Falseなら必ずROLLBACKして何も残さない（check_sql_syntaxの構文検証用）。
    commit=Trueなら成功時にCOMMITし、実際にDBへ反映する（execute_sqlの本実行用）。
    どちらもネットワーク呼び出しを伴うため、GUI側は必ずバックグラウンドスレッドで呼ぶこと。
    """
    if not sql_text.strip():
        return "（空です）"
    if not config_path:
        return "（DB接続設定が未入力です）"
    if not Path(config_path).exists():
        return "NG: DB接続設定ファイルが見つかりません"

    from config_loader import load_config, get_postgres_config

    try:
        data = load_config(config_path)
        pg_config = get_postgres_config(data)
    except (FileNotFoundError, ValueError) as e:
        return f"NG: DB接続設定の読み込みに失敗しました: {e}"

    import psycopg2

    try:
        conn = psycopg2.connect(connect_timeout=timeout, **pg_config)
    except Exception as e:  # 接続失敗の例外種別は多岐にわたるため、境界での広い捕捉として許容する
        return f"NG: DB接続に失敗しました: {e}"

    try:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        if commit:
            conn.commit()
            return "OK: DBに反映しました"
        conn.rollback()
        return "OK: 構文チェックを通過しました（ロールバック済み・DBへの変更はありません）"
    except Exception as e:  # SQL実行エラーの例外種別は多岐にわたるため、境界での広い捕捉として許容する
        conn.rollback()
        suffix = "" if commit else "（ロールバック済み・DBへの変更はありません）"
        return f"NG: SQL実行エラー{suffix}: {e}"
    finally:
        conn.close()


def check_sql_syntax(sql_text: str, config_path: str, timeout: int = 5) -> str:
    """setup.sql/teardown.sqlの内容を、実際にPostgreSQLへBEGIN〜ROLLBACKで試し実行して検証する。

    静的なパースだけでは検出できない実際のエラー（型不一致・制約違反等）を、DBへの変更を
    残さずに検出できる。DBには一切反映されない（本実行はexecute_sqlを使うこと）。
    """
    return _run_sql_against_db(sql_text, config_path, timeout, commit=False)


def execute_sql(sql_text: str, config_path: str, timeout: int = 5) -> str:
    """setup.sql/teardown.sqlの内容を、実際にPostgreSQLへ本実行してコミットする。

    check_sql_syntaxとは違い、成功すればDBに実際に反映される（TRUNCATE/INSERT等）。
    破壊的な操作になり得るため、呼び出し前に必ずユーザーへの確認を取ること。
    """
    return _run_sql_against_db(sql_text, config_path, timeout, commit=True)


def check_db_connectivity(path: str, timeout: int = 5) -> str:
    """config.json に書かれたDB接続情報で、実際に接続できるかを確認する（形式チェックのみのvalidate_db_configとは別）。

    ネットワーク呼び出しを伴い数秒かかることがあるため、GUI側は必ずバックグラウンドスレッドで呼ぶこと。
    """
    if not path:
        return "（未入力）"
    if not Path(path).exists():
        return "NG: ファイルが見つかりません"

    from config_loader import load_config

    try:
        data = load_config(path)
    except (FileNotFoundError, ValueError) as e:
        return f"NG: {e}"

    results = []
    if "postgres" in data:
        results.append(f"postgres: {_check_postgres_connectivity(data, timeout)}")
    if "influxdb" in data:
        results.append(f"influxdb: {_check_influxdb_connectivity(data)}")

    if not results:
        return "NG: postgres/influxdb のいずれのセクションもありません"
    return " / ".join(results)


def _check_postgres_connectivity(data: dict, timeout: int) -> str:
    from config_loader import get_postgres_config

    try:
        pg_config = get_postgres_config(data)
    except ValueError as e:
        return f"NG（{e}）"

    import psycopg2

    try:
        conn = psycopg2.connect(connect_timeout=timeout, **pg_config)
        conn.close()
    except Exception as e:  # 接続失敗の例外種別は多岐にわたるため、境界での広い捕捉として許容する
        return f"NG（接続に失敗しました: {e}）"
    return "OK（接続できました）"


def _check_influxdb_connectivity(data: dict) -> str:
    from config_loader import get_influxdb_config

    try:
        influx_config = get_influxdb_config(data)
    except ValueError as e:
        return f"NG（{e}）"

    from influxdb import InfluxDBClient

    client = InfluxDBClient(
        host=influx_config["host"],
        port=influx_config["port"],
        username=influx_config.get("username"),
        password=influx_config.get("password"),
        database=influx_config["database"],
    )
    try:
        client.ping()
    except Exception as e:  # 接続失敗の例外種別は多岐にわたるため、境界での広い捕捉として許容する
        return f"NG（接続に失敗しました: {e}）"
    finally:
        client.close()
    return "OK（接続できました）"


def validate_sql_file(path: str, required: bool = False) -> str:
    err = _missing_or_blank(path, required)
    if err is not None:
        return err
    if not path:
        return "（未入力・任意）"

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return "NG: ファイルが空です"
    stmt_count = text.count(";")
    return f"OK（約{stmt_count}文）"
