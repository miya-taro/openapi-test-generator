"""Inventory declared constraints and their generated cases; never infer execution coverage."""
from .coverage_obligations import obligations
from .schema_contract import validation_schema
from .extractor import _merge_parameters, _resolve_operation_id
from jsonschema import Draft202012Validator, FormatChecker

ANNOTATIONS = {"title", "description", "default", "example", "examples", "deprecated", "readOnly", "writeOnly", "$schema", "$id", "$comment", "discriminator", "xml", "externalDocs"}
RULES = {"type", "enum", "const", "format", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties", "additionalProperties", "nullable", "required"}
COMPOSED = {"allOf", "oneOf", "anyOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas", "x-otg-presence-rules", "x-otg-comparison-rules"}


def build_coverage(api, cases, selected=None, excluded=None):
    rows = []
    def add(op, loc, name, keyword, status, ids=(), detail=""):
        rows.append({"operationId": op, "location": loc, "field": name, "keyword": keyword,
                     "status": status, "caseIds": list(ids), "detail": detail})

    def walk(schema, op, loc, name, response=False, inherited_partial=False, source_name=None, branch_index=None):
        schema = validation_schema(schema)
        if not isinstance(schema, dict):
            add(op, loc, name, "booleanSchema", "実行時検証" if response else "未対応", detail="専用入力ケースは生成しません")
            return
        for key, value in schema.items():
            if key in ANNOTATIONS or key.startswith("_") or (key.startswith("x-") and key not in COMPOSED):
                continue
            if key == "properties":
                for prop, child in value.items():
                    walk(child, op, loc, prop if name == "requestBody" else f"{name}.{prop}", response, inherited_partial)
                continue
            if key == "items" and isinstance(value, (dict, bool)):
                walk(value, op, loc, name + "[]", response, inherited_partial)
                continue
            if key == "required" and isinstance(value, list) and not response:
                for prop in value:
                    field = prop if name == "requestBody" else f"{name}.{prop}"
                    walk({"required": True}, op, loc, field, False, inherited_partial)
                continue
            if key in {"$defs", "definitions"}:
                continue  # Dereferenced schemas are counted at their use sites.
            candidate_cases = [c for c in cases if c["operationId"] == op and c["in"] == loc
                               and c["paramName"] == (source_name or name)
                               and (branch_index is None or c.get("branchIndex") == branch_index)
                               and (c["keyword"] == key or key in c["keyword"].split("+"))]
            matching = [c["id"] for c in candidate_cases]
            if (key == "format" and value not in FormatChecker.checkers) or (response and key not in Draft202012Validator.VALIDATORS):
                status, detail = "未対応", "この制約の検証には対応していません"
            elif response:
                status, detail = "実行時検証", "応答が返った場合に契約を検証。各応答分岐の実行済みを意味しません"
            elif key in COMPOSED or inherited_partial:
                status, detail = "一部対応", "契約は保持。専用ケース・条件の全組み合わせの生成は保証しません"
            elif key in RULES:
                status = "ケース生成済み" if matching else "未生成"
                detail = "実行・全境界の網羅を意味しません" if matching else "設定・制約の組み合わせによりケースがありません"
            else:
                status, detail = "未対応", "この制約専用の入力ケースを生成するルールがありません"
            add(op, loc, name, key, status, matching, detail)
            if not response and key in RULES:
                for label, ids, reason in obligations(schema, key, value, [c for c in candidate_cases if c["keyword"] == key], loc):
                    add(op, loc, name, f"{key} / {label}",
                        "ケース生成済み" if ids else "該当なし" if reason else "未生成", ids,
                        reason or ("この観点の入力ケースを生成。実行結果は別途確認" if ids else
                                   "制約の組み合わせ・生成設定・未対応によりケースがありません。自動試験済みには含めません"))
            if key in {"allOf", "oneOf", "anyOf", "prefixItems"} and isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, op, loc, f"{name}/{key}/{index}", response, True,
                         source_name=name if key in {"oneOf", "anyOf"} else None,
                         branch_index=index if key in {"oneOf", "anyOf"} else None)
            elif key in {"not", "if", "then", "else", "contains", "additionalProperties", "propertyNames"} and isinstance(value, dict):
                walk(value, op, loc, f"{name}/{key}", response, True)

    for path, item in (api.get("paths") or {}).items():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options"} or not isinstance(operation, dict):
                continue
            op = _resolve_operation_id(operation, method, path)
            if (selected and op not in selected) or (excluded and op in excluded):
                continue
            baseline = [c["id"] for c in cases if c["operationId"] == op and c["in"] == "operation"]
            add(op, "operation", "request", "baseline", "ケース生成済み" if baseline else "未生成", baseline,
                "有効リクエストの合成可否と生成設定に依存。実行結果は別途確認")
            security = operation.get("security", api.get("security")) or []
            if security:
                optional_auth = any(requirement == {} for requirement in security)
                auth_cases = [c for c in cases if c["operationId"] == op and c["keyword"] == "auth"]
                for label, perspective in (("認証なし", "異常系_認証なし"), ("全認証情報が無効", "異常系_無効トークン")):
                    ids = [c["id"] for c in auth_cases if c.get("perspective") == perspective]
                    add(op, "security", "request", label,
                        "該当なし" if optional_auth else "ケース生成済み" if ids else "未生成", ids,
                        "認証なしの利用が仕様で許可されています" if optional_auth else "認証方式ごとの権限・期限の試験を含みません")
                for index, requirement in enumerate(security):
                    for scheme, scopes in requirement.items():
                        if len(requirement) > 1:
                            for label in ("単独欠落", "単独無効"):
                                add(op, "security", f"選択肢{index + 1}/{scheme}", label, "未生成",
                                    detail="他の認証情報を有効にした個別試験が必要です。全欠落・全無効の試験では代用できません")
                        if len(security) > 1 or scopes:
                            add(op, "security", f"選択肢{index + 1}/{scheme}", "認証選択肢・scope", "未生成",
                                detail="各選択肢の有効な資格情報・権限別の期待結果の設定が必要です")
            for p in _merge_parameters(item.get("parameters") or [], operation.get("parameters") or []):
                walk(p.get("schema", {}), op, p.get("in", "parameter"), p.get("name", ""))
                if p.get("required") or p.get("in") == "path":
                    walk({"required": True}, op, p["in"], p["name"])
            if operation.get("requestBody"):
                body_required = bool(operation["requestBody"].get("required"))
                ids = [c["id"] for c in cases if c["operationId"] == op and c["in"] == "body"
                       and c["paramName"] == "requestBody" and c.get("inputValue") in {"（省略）", "（フィールドを省略）"}]
                add(op, "body", "requestBody", "body必須 / 欠落" if body_required else "body任意 / 省略",
                    "ケース生成済み" if ids else "未生成", ids)
            for media, value in ((operation.get("requestBody") or {}).get("content") or {}).items():
                if media not in {"application/json", "multipart/form-data"}:
                    add(op, "body", "requestBody", media, "未対応", detail="入力ケース生成対象外のメディアタイプ")
                else:
                    walk(value.get("schema", {}), op, "body", "requestBody")
            for code, response in (operation.get("responses") or {}).items():
                for header, definition in (response.get("headers") or {}).items():
                    if isinstance(definition, dict):
                        walk(definition.get("schema", {}), op, f"response:{code}:header", header, True)
                for media, value in (response.get("content") or {}).items():
                    loc = f"response:{code}:{media}"
                    if media == "application/json" or media.endswith("+json"):
                        walk(value.get("schema", {}), op, loc, "response", True)
                    else:
                        add(op, loc, "response", "body", "未対応", detail="本文schema検証はJSONのみ")
    return rows


def write_coverage_sheet(workbook, rows):
    sheet = workbook.create_sheet("対応状況")
    sheet.append(["API操作", "場所", "項目", "制約", "生成・対応状況", "試験ID", "補足"])
    for row in rows:
        values = [row.get(k, "") for k in ("operationId", "location", "field", "keyword", "status")]
        values += [", ".join(row.get("caseIds", [])), row.get("detail", "")]
        sheet.append(["'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v for v in values])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
