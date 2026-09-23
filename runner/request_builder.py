from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode
from models import RunCase

_PATH_PARAM_PATTERN = re.compile(r"\{([^{}]+)\}")

OMIT_MARKERS = {"（省略）", "（フィールドを省略）"}
EMPTY_VALUE_MARKER = "（空文字）"
NULL_VALUE_MARKER = "null"

# ルートbody（paramName == "requestBody"）向けのプレースホルダ値。
# openapi-test-gen の src/generator/rules/object.py が出力する値と対応させている。
_ROOT_BODY_EMPTY_MARKER = "{}"
_ROOT_BODY_EXTRA_PROP_MARKER = '{ ...validBody, "__extra__": "value" }'

# oneOf/anyOfバリアント網羅生成用マーカー。
# src/generator/rules/common.py の ONE_OF_VARIANT_MARKER_PREFIX と対応させている。
# 末尾の数字が schema["_oneOfVariants"]（parser.py が残す正規化済みバリアント一覧）
# のインデックス。
_ONE_OF_VARIANT_MARKER_PREFIX = "__ONE_OF_VARIANT__"

# multipart/form-data のファイルアップロードフィールド用マーカー。
# src/generator/rules/file.py の FILE_UPLOAD_MARKER と対応させている。
_FILE_UPLOAD_MARKER = "（ファイルアップロード：ダミーファイル）"

FORMAT_SAMPLES: dict[str, str | int | bool] = {
    "email": "test@example.com",
    "date": "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "uri": "https://example.com",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "hostname": "example.com",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
}


def build_url(base_url: str, case: RunCase, openapi: dict | None = None) -> str:
    path = _fill_path_params(case, openapi)

    url = base_url.rstrip("/") + path

    if case.param_in == "query" and case.input_value not in OMIT_MARKERS:
        val = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        query_val = _build_query_value(case, val, openapi) if openapi is not None else val
        url += "?" + urlencode({case.param_name: query_val}, doseq=True)

    return url


def _fill_path_params(case: RunCase, openapi: dict | None) -> str:
    """path テンプレート中の全ての {paramName} プレースホルダを埋める。

    テスト対象のパラメータ（case.param_in == "path" かつ同名）は case.input_value を
    そのまま使う（省略/空文字マーカーの特殊挙動を含め、既存の挙動を維持する）。

    それ以外の path パラメータ（body/query フィールドをテストしている場合の
    テスト対象外の path param、および複数 path param を持つエンドポイントで
    テスト対象でない方）は、openapi.json のスキーマからベースライン値を自動生成して
    埋める。埋めないと "/users/{userId}" のような未置換のプレースホルダがそのまま
    URLとして送信され、多くのサーバー実装でルーティング失敗・型エラー（例: 422）に
    なり、本来テストしたいフィールドの検証にならない。
    """
    path = case.path
    for match in _PATH_PARAM_PATTERN.finditer(case.path):
        param_name = match.group(1)
        placeholder = "{" + param_name + "}"
        if placeholder not in path:
            continue  # 既に置換済み（同名の path param が複数出現するケースはない前提）

        if case.param_in == "path" and param_name == case.param_name:
            if case.input_value in OMIT_MARKERS:
                continue
            val = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        else:
            val = _baseline_path_value(openapi, case, param_name)
        path = path.replace(placeholder, val)
    return path


def _baseline_path_value(openapi: dict | None, case: RunCase, param_name: str) -> str:
    if openapi is None:
        return "1"
    schema = _resolve_path_param_schema(openapi, case, param_name)
    value = _expand_value(schema) if schema is not None else "1"
    return str(value)


def _resolve_path_param_schema(openapi: dict, case: RunCase, param_name: str) -> dict | None:
    paths = openapi.get("paths", {})
    path_item = paths.get(case.path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, case.operation_id)
    if path_item is None:
        return None
    op = path_item.get(case.method.lower())
    all_params = [*(path_item.get("parameters") or [])]
    if isinstance(op, dict):
        all_params += op.get("parameters") or []
    for p in all_params:
        if isinstance(p, dict) and p.get("name") == param_name and p.get("in") == "path":
            return p.get("schema") or {}
    return None


def _build_query_value(case: RunCase, val: str, openapi: dict) -> object:
    """クエリパラメータの値を組み立てる。

    配列型のクエリパラメータは、generator（array.py）がJSONリテラル文字列
    （例: '["a", "b"]'）をinputValueとして出力するが、これをそのままURLに
    埋め込むと本来の配列としてサーバーに解釈されない。OpenAPIの`style`/`explode`
    （既定はstyle: form, explode: true = 繰り返しキー形式）に従って正しく
    シリアライズする。配列型でない場合は入力値をそのまま返す（従来通り）。
    """
    param_schema = _resolve_query_param_schema(openapi, case)
    schema = (param_schema or {}).get("schema") or {}
    if schema.get("type") != "array":
        return val

    try:
        items = json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val
    if not isinstance(items, list):
        return val

    style = (param_schema or {}).get("style", "form")
    explode = (param_schema or {}).get("explode", style == "form")
    if style == "form" and explode:
        return [str(v) for v in items]  # urlencode(doseq=True) が繰り返しキーに展開する
    if style == "spaceDelimited":
        sep = " "
    elif style == "pipeDelimited":
        sep = "|"
    else:  # style: form かつ explode: false、または未対応スタイル
        sep = ","
    return sep.join(str(v) for v in items)


def _resolve_query_param_schema(openapi: dict, case: RunCase) -> dict | None:
    paths = openapi.get("paths", {})
    path_item = paths.get(case.path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, case.operation_id)
    if path_item is None:
        return None
    op = path_item.get(case.method.lower())
    if not isinstance(op, dict):
        return None
    for p in (*(path_item.get("parameters") or []), *(op.get("parameters") or [])):
        if isinstance(p, dict) and p.get("name") == case.param_name and p.get("in") == "query":
            return p
    return None


@dataclass
class PreparedBody:
    """requests に渡す body 情報。

    json_body が None でない場合（空dict {} も含む）は json= として送る。
    is_multipart が True の場合は multipart_fields を files= として送る
    （テキストフィールドも (None, value) 形式で files= に含めることで、ファイル
    フィールドが1つも無いスキーマでも確実に multipart/form-data エンコードになる。
    requests は files= に何も渡さないと application/x-www-form-urlencoded に
    フォールバックしてしまうため）。
    どちらでもない場合（build_request_body が None を返す場合）は body なし。
    """
    json_body: object | None = None
    is_multipart: bool = False
    multipart_fields: dict[str, tuple] = field(default_factory=dict)


def build_request_body(case: RunCase, openapi: dict | None) -> PreparedBody | None:
    if case.param_in != "body":
        return None

    content_type = (
        _resolve_request_body_content_type(case.operation_id, case.path, case.method, openapi)
        if openapi else "application/json"
    )
    if content_type == "multipart/form-data":
        fields = _build_multipart_fields(case, openapi)
        return PreparedBody(is_multipart=True, multipart_fields=fields)

    body = _build_body(case, openapi)
    return PreparedBody(json_body=body)


def _resolve_request_body_content_type(operation_id: str, path: str, method: str, openapi: dict) -> str:
    paths = openapi.get("paths", {})
    path_item = paths.get(path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, operation_id)
    if path_item is None:
        return "application/json"
    op = path_item.get(method.lower())
    if not isinstance(op, dict):
        return "application/json"
    content = ((op.get("requestBody") or {}).get("content")) or {}
    if "application/json" not in content and "multipart/form-data" in content:
        return "multipart/form-data"
    return "application/json"


_DUMMY_UPLOAD_FILENAME = "dummy_upload.txt"
_DUMMY_UPLOAD_CONTENT = b"dummy upload content for automated testing\n"
_DUMMY_UPLOAD_CONTENT_TYPE = "text/plain"


def _build_multipart_fields(case: RunCase, openapi: dict | None) -> dict[str, tuple]:
    """multipart/form-data 用のフォームフィールドを requests の files= 形式で組み立てる。

    テキストフィールドは (None, value)、ファイルフィールドは
    (filename, content, content_type) というタプルで表現する（requests の作法）。
    全フィールドを files= 経由にすることで、ファイルフィールドが1つも
    含まれないスキーマでも確実に multipart/form-data エンコードになる
    （files= が空だと requests は application/x-www-form-urlencoded に
    フォールバックしてしまうため）。multipart のスキーマは通常フラット
    （フォームフィールドの集合）なので、_build_body のようなネスト対応は行わず、
    トップレベルの properties のみを扱う。
    """
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi) if openapi else None
    fields = _expand_multipart_baseline(schema) if schema is not None else {}

    if case.input_value in OMIT_MARKERS:
        fields.pop(case.param_name, None)
    elif case.input_value == _FILE_UPLOAD_MARKER:
        fields[case.param_name] = _FileUploadValue()
    elif case.input_value == NULL_VALUE_MARKER:
        fields[case.param_name] = ""
    else:
        raw = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        fields[case.param_name] = raw

    result: dict[str, tuple] = {}
    for key, value in fields.items():
        if isinstance(value, _FileUploadValue):
            result[key] = (_DUMMY_UPLOAD_FILENAME, _DUMMY_UPLOAD_CONTENT, _DUMMY_UPLOAD_CONTENT_TYPE)
        else:
            result[key] = (None, value)
    return result


class _FileUploadValue:
    """multipart baseline 内でファイルアップロードフィールドを表すマーカー型。"""


def _expand_multipart_baseline(schema: dict) -> dict:
    """required なフォームフィールドを、テスト対象フィールド以外も含めて有効な値で埋める。"""
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    baseline: dict = {}
    for name in required:
        prop_schema = props.get(name)
        if not isinstance(prop_schema, dict) or prop_schema.get("readOnly"):
            continue
        if prop_schema.get("format") == "binary":
            baseline[name] = _FileUploadValue()
        else:
            value = _expand_value(prop_schema)
            baseline[name] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return baseline


def _build_body(case: RunCase, openapi: dict | None) -> dict:
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi) if openapi else None

    # ベースライン: required フィールドを（ネスト・配列要素も含めて）全階層分、有効な値で埋めた body
    baseline = _expand_value(schema) if schema is not None else {}
    body: dict = baseline if isinstance(baseline, dict) else {}

    # ルートbody全体を対象とするケース（空body / additionalProperties / oneOfバリアント）は
    # body 全体を差し替える
    if case.param_name == "requestBody":
        if case.input_value == _ROOT_BODY_EMPTY_MARKER:
            return {}
        if case.input_value == _ROOT_BODY_EXTRA_PROP_MARKER:
            return {**body, "__extra__": "value"}
        if case.input_value.startswith(_ONE_OF_VARIANT_MARKER_PREFIX):
            variant_value = _resolve_one_of_variant_value(schema, case.input_value)
            if isinstance(variant_value, dict):
                return variant_value
        return body

    if case.input_value in OMIT_MARKERS:
        _delete_nested(body, case.param_name, schema)
    elif case.input_value == NULL_VALUE_MARKER:
        _set_nested(body, case.param_name, None, schema)
    else:
        raw = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        field_schema = _resolve_nested_schema(schema, case.param_name) if schema is not None else {}
        if raw.startswith(_ONE_OF_VARIANT_MARKER_PREFIX):
            # バリアントごとに型が異なりうるため、field_schema（代表バリアントの型）を
            # 基準にした _coerce_value の型判定には委ねず、対象バリアントのスキーマから
            # 直接ベースライン値を組み立てる。
            variant_value = _resolve_one_of_variant_value(field_schema, raw)
            if variant_value is not _MISSING:
                _set_nested(body, case.param_name, variant_value, schema)
                return body
        _set_nested(body, case.param_name, _coerce_value(raw, field_schema), schema)

    return body


_MISSING = object()


def _resolve_one_of_variant_value(schema: dict | None, input_value: str) -> object:
    """`__ONE_OF_VARIANT__{index}` マーカーから、対応するバリアントのベースライン値を組み立てる。

    schema や index が想定外（schema に _oneOfVariants が無い、index範囲外等）の場合は
    _MISSING を返し、呼び出し側で通常のベースライン値にフォールバックする。
    ルートbody・ネストしたbodyフィールドの両方から共通で使う（ルート側は戻り値が
    dict であることを呼び出し側で確認する）。
    """
    if schema is None:
        return _MISSING
    variants = schema.get("_oneOfVariants")
    if not variants:
        return _MISSING
    try:
        index = int(input_value[len(_ONE_OF_VARIANT_MARKER_PREFIX):])
    except ValueError:
        return _MISSING
    if not (0 <= index < len(variants)):
        return _MISSING
    return _expand_value(variants[index])


def _navigate_to_parent(body: dict, dotted_path: str, root_schema: dict | None) -> tuple[dict, str]:
    """ドット区切りパスの最終セグメント手前まで辿り、(親コンテナ, 最終キー) を返す。

    セグメントが "lines[]" のように "[]" で終わる場合は配列として扱い、
    先頭要素（存在しなければ新規作成した空dict）に読み替える。
    途中のコンテナが存在しない場合（親フィールドが required でない等）は、
    スキーマから有効なベースライン値を生成して埋める
    （そうしないと、そのコンテナの他の required フィールドが欠けたリクエストになってしまう）。
    """
    parts = dotted_path.split(".")
    container = body
    schema_node: dict | None = root_schema
    for part in parts[:-1]:
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part

        props = schema_node.get("properties", {}) if isinstance(schema_node, dict) else {}
        field_schema = props.get(key) if isinstance(props, dict) else None

        if is_array:
            item_schema = field_schema.get("items") if isinstance(field_schema, dict) else None
            lst = container.get(key)
            if not isinstance(lst, list) or not lst or not isinstance(lst[0], dict):
                seed = _expand_value(item_schema) if isinstance(item_schema, dict) else {}
                lst = [seed if isinstance(seed, dict) else {}]
                container[key] = lst
            container = lst[0]
            schema_node = item_schema
        else:
            nxt = container.get(key)
            if not isinstance(nxt, dict):
                seed = _expand_value(field_schema) if isinstance(field_schema, dict) else {}
                nxt = seed if isinstance(seed, dict) else {}
                container[key] = nxt
            container = nxt
            schema_node = field_schema
    last = parts[-1]
    last_key = last[:-2] if last.endswith("[]") else last
    return container, last_key


def _set_nested(body: dict, dotted_path: str, value: object, root_schema: dict | None) -> None:
    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    container[key] = value


def _delete_nested(body: dict, dotted_path: str, root_schema: dict | None) -> None:
    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    container.pop(key, None)


def _resolve_nested_schema(root_schema: dict | None, dotted_path: str) -> dict:
    """ドット区切りパス（配列要素を表す "[]" 区切りを含む）からフィールドのスキーマを解決する。"""
    if root_schema is None:
        return {}
    node: dict = root_schema
    for part in dotted_path.split("."):
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        props = node.get("properties", {}) if isinstance(node, dict) else {}
        node = props.get(key)
        if not isinstance(node, dict):
            return {}
        if is_array:
            node = node.get("items", {})
            if not isinstance(node, dict):
                return {}
    return node


def _resolve_request_body_schema(operation_id: str, path: str, method: str, openapi: dict) -> dict | None:
    paths = openapi.get("paths", {})
    path_item = paths.get(path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, operation_id)
    if path_item is None:
        return None

    op = path_item.get(method.lower())
    if op is None:
        return None

    rb = op.get("requestBody", {})
    content = rb.get("content", {})
    picked_content = content.get("application/json") or content.get("multipart/form-data") or {}
    schema = picked_content.get("schema", {})
    return _resolve_ref(schema, openapi) if schema else None


def _find_path_by_operation_id(paths: dict, operation_id: str) -> dict | None:
    for path_item in paths.values():
        for method_item in path_item.values():
            if isinstance(method_item, dict) and method_item.get("operationId") == operation_id:
                return path_item
    return None


def _resolve_ref(schema: dict, openapi: dict) -> dict:
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"]
    parts = ref.lstrip("#/").split("/")
    node = openapi
    for part in parts:
        node = node.get(part, {})
    return node


def _expand_value(schema: dict) -> object:
    # スキーマに default が明示されていれば、型ベースの適当な値より優先する
    # （リクエストのベースラインとして、実際にAPIが期待するデフォルト値に近い方が正確なため）。
    if "default" in schema:
        return schema["default"]

    t = schema.get("type", "string")
    fmt = schema.get("format", "")
    enum = schema.get("enum")

    if enum:
        return enum[0]

    if t == "integer" or t == "number":
        minimum = schema.get("minimum")
        return minimum if minimum is not None else 1

    if t == "boolean":
        return True

    if t == "array":
        items = schema.get("items", {})
        return [_expand_value(items)]

    if t == "object":
        props = schema.get("properties", {})
        required = schema.get("required", [])
        # readOnly なプロパティ（サーバー側専用）はリクエストには含めない
        # readOnly なプロパティ（サーバー側専用）はリクエストには含めない
        return {
            k: _expand_value(props[k])
            for k in required
            if k in props and not props[k].get("readOnly")
        }

    # string
    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len

    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]

    return "test"


def _coerce_value(raw_value: str, field_schema: dict) -> object:
    t = field_schema.get("type", "string")
    if t in ("integer", "number"):
        try:
            return int(raw_value) if t == "integer" else float(raw_value)
        except ValueError:
            pass
    if t == "boolean":
        return raw_value.lower() in ("true", "1", "yes")
    if t in ("array", "object"):
        # generator（array.py/object.py/common.py）はこのフィールド自体が array/object 型の
        # 場合、inputValue に JSON リテラル文字列（例: '[{"a": 1}]' や '"not-an-array"'）を
        # 出力する。json.loads せずそのまま埋め込むと、リクエストボディの当該フィールドが
        # 「JSON配列/オブジェクト」ではなく「JSON文字列」になってしまい、意図と異なるテストに
        # なってしまう（境界値テストなのに型不正テストとして扱われる等）。
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            pass
    return raw_value
