from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode
from models import RunCase
from src.schema_example import NoSchemaExample, find_schema_example
from src.presence import complete_presence

_PATH_PARAM_PATTERN = re.compile(r"\{([^{}]+)\}")

OMIT_MARKERS = {"（省略）", "（フィールドを省略）"}
EMPTY_VALUE_MARKER = "（空文字）"
NULL_VALUE_MARKER = "null"

# ルートbody（paramName == "requestBody"）向けのプレースホルダ値。
# openapi-test-gen の src/generator/rules/object.py が出力する値と対応させている。
_ROOT_BODY_EMPTY_MARKER = "{}"

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

    query = _build_required_operation_query(
        openapi,
        case,
        exclude_tested_parameter=case.param_in == "query",
    ) if openapi is not None else {}
    if case.param_in == "query" and case.input_value not in OMIT_MARKERS:
        val = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        query_val = _build_query_value(case, val, openapi) if openapi is not None else val
        query[case.param_name] = query_val
    if query:
        url += "?" + urlencode(query, doseq=True)

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
    param = _resolve_path_param(openapi, case, param_name)
    if param is None:
        return "1"
    value = _expand_value(param.get("schema") or {})
    style = param.get("style", "simple")
    explode = param.get("explode", False)
    return _serialize_path_parameter(param_name, value, style, explode)


def _resolve_path_param_schema(openapi: dict, case: RunCase, param_name: str) -> dict | None:
    param = _resolve_path_param(openapi, case, param_name)
    return (param or {}).get("schema")


def _resolve_path_param(openapi: dict, case: RunCase, param_name: str) -> dict | None:
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
            return p
    return None


def _serialize_path_parameter(name: str, value: object, style: str, explode: bool) -> str:
    def encode(item: object) -> str:
        if isinstance(item, bool):
            item = "true" if item else "false"
        return quote(str(item), safe="-._~")

    if isinstance(value, list):
        values = [encode(item) for item in value]
        if style == "label":
            return "." + ("." if explode else ",").join(values)
        if style == "matrix":
            if explode:
                return "".join(f";{quote(name, safe='-._~')}={item}" for item in values)
            return f";{quote(name, safe='-._~')}=" + ",".join(values)
        return ",".join(values)
    if isinstance(value, dict):
        pairs = [(encode(key), encode(item)) for key, item in value.items()]
        if style == "label":
            separator = "." if explode else ","
            return "." + separator.join(f"{key}={item}" for key, item in pairs) if explode else "." + ",".join(
                part for pair in pairs for part in pair
            )
        if style == "matrix":
            if explode:
                return "".join(f";{key}={item}" for key, item in pairs)
            return f";{quote(name, safe='-._~')}=" + ",".join(part for pair in pairs for part in pair)
        return ",".join(f"{key}={item}" for key, item in pairs) if explode else ",".join(
            part for pair in pairs for part in pair
        )
    scalar = encode(value)
    if style == "label":
        return "." + scalar
    if style == "matrix":
        return f";{quote(name, safe='-._~')}={scalar}"
    return scalar


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


def _resolve_path_item(openapi: dict, case: RunCase) -> dict | None:
    path_item = (openapi.get("paths") or {}).get(case.path)
    if path_item is None:
        path_item = _find_path_by_operation_id(openapi.get("paths", {}), case.operation_id)
    return path_item if isinstance(path_item, dict) else None


def _resolve_operation(openapi: dict, case: RunCase) -> dict | None:
    path_item = _resolve_path_item(openapi, case)
    operation = path_item.get(case.method.lower()) if path_item else None
    return operation if isinstance(operation, dict) else None


def _merged_operation_parameters(path_item: dict, operation: dict) -> list[dict]:
    merged: dict[tuple[str | None, str | None], dict] = {}
    for param in (*(path_item.get("parameters") or []), *(operation.get("parameters") or [])):
        if isinstance(param, dict):
            merged[(param.get("name"), param.get("in"))] = param
    return list(merged.values())


def _build_required_operation_query(
    openapi: dict,
    case: RunCase,
    exclude_tested_parameter: bool = False,
) -> dict[str, object]:
    path_item = _resolve_path_item(openapi, case)
    operation = _resolve_operation(openapi, case)
    if path_item is None or operation is None:
        return {}

    query: dict[str, object] = {}
    for param in _merged_operation_parameters(path_item, operation):
        if not param.get("required") or param.get("in") != "query":
            continue
        if (
            exclude_tested_parameter
            and case.param_in == "query"
            and param.get("name") == case.param_name
        ):
            continue
        value = _expand_value(param.get("schema") or {})
        name = param.get("name", "")
        style = param.get("style", "form")
        explode = param.get("explode", style == "form")
        if isinstance(value, list):
            items = [str(item) for item in value]
            if style == "form" and explode:
                query[name] = items
            else:
                separator = {"spaceDelimited": " ", "pipeDelimited": "|"}.get(style, ",")
                query[name] = separator.join(items)
        elif isinstance(value, dict):
            if style == "deepObject":
                query.update({f"{name}[{key}]": str(item) for key, item in value.items()})
            elif style == "form" and explode:
                query.update({str(key): str(item) for key, item in value.items()})
            else:
                parts = [str(part) for pair in value.items() for part in pair]
                query[name] = ",".join(parts)
        elif isinstance(value, bool):
            query[name] = "true" if value else "false"
        else:
            query[name] = str(value)
    return query


def build_operation_header_and_cookie_values(
    case: RunCase, openapi: dict | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build other required header/cookie parameters around the current test input."""
    if not openapi:
        return {}, {}
    path_item = _resolve_path_item(openapi, case)
    operation = _resolve_operation(openapi, case)
    if path_item is None or operation is None:
        return {}, {}

    headers: dict[str, str] = {}
    cookies: dict[str, str] = {}
    for param in _merged_operation_parameters(path_item, operation):
        location = param.get("in")
        if not param.get("required") or location not in {"header", "cookie"}:
            continue
        same_parameter = (
            param.get("name", "").lower() == case.param_name.lower()
            if location == "header"
            else param.get("name") == case.param_name
        )
        if location == case.param_in and same_parameter:
            # The case itself supplies, invalidates, or omits this one parameter.
            continue
        value = _expand_value(param.get("schema") or {})
        rendered = _serialize_simple_parameter_value(value, bool(param.get("explode", False)))
        if location == "header":
            headers[param["name"]] = rendered
        else:
            cookies[param["name"]] = rendered
    return headers, cookies


def _serialize_simple_parameter_value(value: object, explode: bool = False) -> str:
    if isinstance(value, list):
        return ",".join(_parameter_scalar(item) for item in value)
    if isinstance(value, dict):
        if explode:
            return ",".join(
                f"{_parameter_scalar(key)}={_parameter_scalar(item)}"
                for key, item in value.items()
            )
        return ",".join(
            _parameter_scalar(part) for pair in value.items() for part in pair
        )
    return _parameter_scalar(value)


def _parameter_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


@dataclass
class PreparedBody:
    """requests に渡す body 情報。

    json_body は JSON として送る値（None は JSON null、空dict {} も含む）。
    is_multipart が True の場合は multipart_fields を files= として送る
    （テキストフィールドも (None, value) 形式で files= に含めることで、ファイル
    フィールドが1つも無いスキーマでも確実に multipart/form-data エンコードになる。
    requests は files= に何も渡さないと application/x-www-form-urlencoded に
    フォールバックしてしまうため）。
    body 自体を省略する場合は build_request_body が None を返す。
    """
    json_body: object | None = None
    is_multipart: bool = False
    multipart_fields: dict[str, tuple] = field(default_factory=dict)


def build_request_body(case: RunCase, openapi: dict | None) -> PreparedBody | None:
    if case.param_in == "header" and case.param_name.lower() == "content-type":
        if not openapi:
            return PreparedBody(json_body={})
        schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi)
        if schema is None:
            return PreparedBody(json_body={})
        content_type = _resolve_request_body_content_type(case.operation_id, case.path, case.method, openapi)
        if content_type == "multipart/form-data":
            fields = _expand_multipart_baseline(schema)
            multipart_fields = {
                key: ((_DUMMY_UPLOAD_FILENAME, _DUMMY_UPLOAD_CONTENT, _DUMMY_UPLOAD_CONTENT_TYPE)
                      if isinstance(value, _FileUploadValue) else (None, str(value)))
                for key, value in fields.items()
            }
            return PreparedBody(is_multipart=True, multipart_fields=multipart_fields)
        return PreparedBody(json_body=_expand_value(schema))

    if case.param_in == "operation":
        return _build_required_operation_body(case, openapi)

    if case.param_in != "body":
        # A negative query/path/header/cookie case should differ from a valid request
        # only in its target parameter. Keep any required request body valid as well.
        return _build_required_operation_body(case, openapi)
    if case.param_name == "requestBody" and case.input_value in OMIT_MARKERS:
        # Omission of the entire requestBody is different from omission of a property.
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


def _build_required_operation_body(case: RunCase, openapi: dict | None) -> PreparedBody | None:
    if not openapi:
        return None
    operation = _resolve_operation(openapi, case)
    request_body = (operation or {}).get("requestBody") or {}
    if not request_body.get("required"):
        return None
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi)
    if schema is None:
        return None
    content_type = _resolve_request_body_content_type(case.operation_id, case.path, case.method, openapi)
    if content_type == "multipart/form-data":
        fields = _expand_multipart_baseline(schema)
        multipart_fields = {
            key: ((_DUMMY_UPLOAD_FILENAME, _DUMMY_UPLOAD_CONTENT, _DUMMY_UPLOAD_CONTENT_TYPE)
                  if isinstance(value, _FileUploadValue) else (None, str(value)))
            for key, value in fields.items()
        }
        return PreparedBody(is_multipart=True, multipart_fields=multipart_fields)
    return PreparedBody(json_body=_expand_value(schema))


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


def _build_body(case: RunCase, openapi: dict | None) -> object:
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi) if openapi else None

    # ベースライン: required フィールドを（ネスト・配列要素も含めて）全階層分、有効な値で埋めた body
    baseline = _expand_value(schema) if schema is not None else {}
    body = baseline if isinstance(baseline, (dict, list)) else {}

    # ルートbody全体を対象とするケース（空body / additionalProperties / oneOfバリアント）は
    # body 全体を差し替える
    if case.param_name == "requestBody":
        if case.input_value.startswith("__PRESENCE_RULE__"):
            return _presence_rule_body(schema or {}, case.input_value)
        if case.input_value == NULL_VALUE_MARKER:
            return None
        if case.input_value == EMPTY_VALUE_MARKER:
            return ""
        if case.input_value == _ROOT_BODY_EMPTY_MARKER:
            return {}
        extra_property_body = _build_extra_property_body(case.input_value, schema or {})
        if extra_property_body is not _MISSING:
            return extra_property_body
        if case.input_value.startswith(_ONE_OF_VARIANT_MARKER_PREFIX):
            variant_value = _resolve_one_of_variant_value(schema, case.input_value)
            if variant_value is not _MISSING:
                return variant_value
            return baseline
        return _coerce_value(case.input_value, schema or {})

    field_path = case.param_name
    if field_path.startswith("requestBody[]"):
        field_path = field_path[len("requestBody"):]
    if case.input_value in OMIT_MARKERS:
        _delete_nested(body, field_path, schema)
    elif case.input_value == NULL_VALUE_MARKER:
        _set_nested(body, field_path, None, schema)
    elif case.input_value.startswith("{ ...validBody,"):
        field_schema = _resolve_nested_schema(schema, field_path) if schema is not None else {}
        extra_property_body = _build_extra_property_body(case.input_value, field_schema)
        if extra_property_body is not _MISSING:
            _set_nested(body, field_path, extra_property_body, schema)
    else:
        raw = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        field_schema = _resolve_nested_schema(schema, field_path) if schema is not None else {}
        if raw.startswith(_ONE_OF_VARIANT_MARKER_PREFIX):
            # バリアントごとに型が異なりうるため、field_schema（代表バリアントの型）を
            # 基準にした _coerce_value の型判定には委ねず、対象バリアントのスキーマから
            # 直接ベースライン値を組み立てる。
            variant_value = _resolve_one_of_variant_value(field_schema, raw)
            if variant_value is not _MISSING:
                _set_nested(body, field_path, variant_value, schema)
                if isinstance(body, dict):
                    complete_presence(body, schema or {}, _expand_value, target=case.param_name)
                return body
            # An invalid internal marker is not user input. Leave the valid baseline field intact.
            return body
        _set_nested(body, field_path, _coerce_value(raw, field_schema), schema)

    if isinstance(body, dict):
        complete_presence(body, schema or {}, _expand_value, target=case.param_name)
    return body


_MISSING = object()


def _build_extra_property_body(input_value: str, schema: dict) -> object:
    """Expand the generator's validBody expression into a concrete object value."""
    match = re.fullmatch(
        r'\{\s*\.\.\.validBody,\s*("(?:\\.|[^"\\])*")\s*:\s*(.*?)\s*\}',
        input_value,
        flags=re.DOTALL,
    )
    if not match:
        return _MISSING
    try:
        key = json.loads(match.group(1))
        extra_value = json.loads(match.group(2))
    except json.JSONDecodeError:
        return _MISSING

    value = _expand_value(schema)
    if not isinstance(value, dict):
        return _MISSING
    value[key] = extra_value
    return value


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


def _normalize_array_path(dotted_path: str) -> str:
    """Normalize both ``items[].field`` and ``items.[].field`` path spellings."""
    parts = dotted_path.split(".")
    normalized: list[str] = []
    for part in parts:
        if part == "[]" and normalized and normalized[-1] != "[]":
            normalized[-1] += "[]"
        else:
            normalized.append(part)
    return ".".join(normalized)


def _navigate_to_parent(body: object, dotted_path: str, root_schema: dict | None) -> tuple[object, str]:
    """ドット区切りパスの最終セグメント手前まで辿り、(親コンテナ, 最終キー) を返す。

    セグメントが "lines[]" または独立した "[]" の場合は配列として扱い、
    先頭要素（存在しなければスキーマに合う値）に読み替える。
    途中のコンテナが存在しない場合（親フィールドが required でない等）は、
    スキーマから有効なベースライン値を生成して埋める
    （そうしないと、そのコンテナの他の required フィールドが欠けたリクエストになってしまう）。
    """
    parts = _normalize_array_path(dotted_path).split(".")
    container = body
    schema_node: dict | None = root_schema
    for part in parts[:-1]:
        if part == "[]":
            item_schema = schema_node.get("items") if isinstance(schema_node, dict) else None
            if not isinstance(container, list):
                raise ValueError(f"配列要素のbodyパスが不正です: {dotted_path}")
            if not container:
                seed = _expand_value(item_schema) if isinstance(item_schema, dict) else {}
                container.append(seed)
            container = container[0]
            schema_node = item_schema if isinstance(item_schema, dict) else None
            continue

        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part

        props = schema_node.get("properties", {}) if isinstance(schema_node, dict) else {}
        field_schema = props.get(key) if isinstance(props, dict) else None
        if not isinstance(container, dict):
            raise ValueError(f"object要素のbodyパスが不正です: {dotted_path}")

        if is_array:
            item_schema = field_schema.get("items") if isinstance(field_schema, dict) else None
            lst = container.get(key)
            if not isinstance(lst, list) or not lst or not isinstance(lst[0], dict):
                candidate = _expand_value(field_schema) if isinstance(field_schema, dict) else []
                if not isinstance(candidate, list) or not candidate:
                    seed = _expand_value(item_schema) if isinstance(item_schema, dict) else {}
                    candidate = [seed if isinstance(seed, dict) else {}]
                lst = candidate
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


def _set_nested(body: object, dotted_path: str, value: object, root_schema: dict | None) -> None:
    if dotted_path == "[]":
        if isinstance(body, list):
            if body:
                body[0] = value
            else:
                body.append(value)
            return

    if dotted_path.endswith("[]"):
        array_path = dotted_path[:-2].rstrip(".")
        values = body if not array_path else _resolve_body_path(body, array_path, root_schema)
        if isinstance(values, list):
            if values:
                values[0] = value
            else:
                values.append(value)
            return

    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    if not isinstance(container, dict):
        raise ValueError(f"object要素のbodyパスが不正です: {dotted_path}")
    container[key] = value


def _resolve_body_path(body: object, dotted_path: str, root_schema: dict | None) -> object | None:
    """Resolve a schema-aware body path, including array items, and seed missing containers."""
    container = body
    schema_node = root_schema
    for part in _normalize_array_path(dotted_path).split("."):
        if part == "[]":
            item_schema = schema_node.get("items") if isinstance(schema_node, dict) else None
            if not isinstance(container, list):
                return None
            if not container:
                container.append(_expand_value(item_schema) if isinstance(item_schema, dict) else {})
            container = container[0]
            schema_node = item_schema if isinstance(item_schema, dict) else None
            continue

        if not isinstance(container, dict):
            return None
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        properties = schema_node.get("properties", {}) if isinstance(schema_node, dict) else {}
        field_schema = properties.get(key) if isinstance(properties, dict) else None

        if is_array:
            item_schema = field_schema.get("items") if isinstance(field_schema, dict) else None
            values = container.get(key)
            if not isinstance(values, list) or not values:
                candidate = _expand_value(field_schema) if isinstance(field_schema, dict) else []
                if not isinstance(candidate, list) or not candidate:
                    candidate = [_expand_value(item_schema) if isinstance(item_schema, dict) else {}]
                values = candidate
                container[key] = values
            container = values[0]
            schema_node = item_schema if isinstance(item_schema, dict) else None
        else:
            if key not in container:
                container[key] = _expand_value(field_schema) if isinstance(field_schema, dict) else {}
            container = container[key]
            schema_node = field_schema if isinstance(field_schema, dict) else None
    return container


def _delete_nested(body: object, dotted_path: str, root_schema: dict | None) -> None:
    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    if isinstance(container, dict):
        container.pop(key, None)


def _resolve_nested_schema(root_schema: dict | None, dotted_path: str) -> dict:
    """ドット区切りパス（配列要素を表す "[]" 区切りを含む）からフィールドのスキーマを解決する。"""
    if root_schema is None:
        return {}
    node: dict = root_schema
    for part in dotted_path.split("."):
        if part == "[]":
            node = node.get("items", {})
            if not isinstance(node, dict):
                return {}
            continue
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
    try:
        value = find_schema_example(schema)
    except NoSchemaExample:
        # Field-level negative cases predate the operation baseline. Retain the historic fallback
        # for those cases; operation-level baseline cases are only emitted after extractor-side
        # preflight confirms that every required schema can be synthesized and validated.
        value = _fallback_expand_value(schema)
    if isinstance(value, dict):
        complete_presence(value, schema, _expand_value)
    return value


def _presence_rule_body(schema: dict, marker: str) -> dict:
    match = re.fullmatch(r"__PRESENCE_RULE__(\d+):(first|second|both|neither)", marker)
    if not match:
        raise ValueError("条件付き必須の試験指定が不正です")
    rules = schema.get("x-otg-presence-rules") or []
    index = int(match.group(1))
    if index >= len(rules):
        raise ValueError("条件付き必須の試験指定が見つかりません")
    rule = rules[index]
    first, second = rule["fields"]
    value = _expand_value(schema)
    if not isinstance(value, dict):
        raise ValueError("条件付き必須の対象はJSONオブジェクトにしてください")
    value.pop(first, None)
    value.pop(second, None)
    variant = match.group(2)
    for name, selected in ((first, variant in {"first", "both"}), (second, variant in {"second", "both"})):
        if selected:
            value[name] = _expand_value(schema["properties"][name])
    return value


def _fallback_expand_value(schema: dict) -> object:
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        return schema["default"]

    enum = schema.get("enum")
    if enum:
        return enum[0]

    t = schema.get("type", "string")
    if isinstance(t, list):
        t = next((item for item in t if item != "null"), "null")
    fmt = schema.get("format", "")

    if t in ("integer", "number"):
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
        return {
            k: _expand_value(props[k])
            for k in required
            if k in props and not props[k].get("readOnly")
        }

    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len
    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]
    return "test"


def _coerce_value(raw_value: str, field_schema: dict) -> object:
    t = field_schema.get("type", "string")
    if isinstance(t, list):
        non_null_types = [value for value in t if value != "null"]
        t = non_null_types[0] if len(non_null_types) == 1 else None
    if t in ("integer", "number"):
        try:
            return int(raw_value) if t == "integer" else float(raw_value)
        except ValueError:
            pass
    if t == "boolean":
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        if isinstance(value, bool):
            return value
        # JSON-quoted strings such as "yes" are deliberately invalid boolean
        # inputs; only unquoted runner literals are coerced to boolean values.
        if value == raw_value and isinstance(value, str) and value.lower() in ("true", "1", "yes"):
            return True
        if value == raw_value and isinstance(value, str) and value.lower() in ("false", "0", "no"):
            return False
        return value
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
