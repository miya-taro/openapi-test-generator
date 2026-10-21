"""Declared DB mappings and input partitions, separate from execution results."""

import json

MISSING = object()
ONE = object()
MANY = object()


def leaves(schema, path="", depth=0):
    if not isinstance(schema, dict) or depth > 12:
        return []
    if schema.get("type") == "array":
        return leaves(schema.get("items", {}), path + "[]", depth + 1)
    props = schema.get("properties", {})
    if props:
        return [
            field
            for key, child in props.items()
            for field in leaves(child, f"{path}.{key}" if path else key, depth + 1)
        ]
    return [path] if path else []


def schema_for(content):
    schema = next(
        (
            media.get("schema", {})
            for key, media in (content or {}).items()
            if ("json" in key) and isinstance(media, dict)
        ),
        {},
    )
    return schema if isinstance(schema, dict) else {}


def covers(mapped, field):
    return any(field == path or field.startswith(path + ".") for path in mapped)


def build_db_coverage(api, cases):
    rows = []
    db_cases = [case for case in cases if case.get("kind") == "db-scenario"]

    def add(op, loc, field, keyword, matches, detail, missing="未照合"):
        rows.append(
            {
                "operationId": op,
                "location": loc,
                "field": field,
                "keyword": keyword,
                "status": "照合設定あり" if matches else missing,
                "caseIds": [case["caseId"] for case in matches],
                "detail": detail,
            }
        )

    def success(case):
        status = (case["definition"].get("responseCheck") or {}).get("expectedStatus")
        return isinstance(status, int) and 200 <= status < 300

    def request_maps(case):
        check = case["definition"].get("dbInsertCheck") or {}
        result = []
        for rule in check.get("columns", {}).values():
            result.extend(
                rule[key]
                for key in ["path", "date", "time", "preferred_path"]
                if rule.get(key)
            )
        return result

    def response_maps(case):
        definition = case["definition"]
        sql = definition.get("dbSqlResponseCheck") or {}
        result = list(sql.get("fields", {}))
        check = definition.get("dbResponseCheck") or {}
        prefix = check.get("arrayPath")
        if prefix is not None:
            prefix = prefix.removeprefix("$.")
            prefix = "" if prefix == "$" else prefix
            prefix += "[]"
        for field in check.get("fields", {}):
            result.append((prefix + "." if prefix else "") + field.removeprefix("$."))
        return result

    for route, item in api.get("paths", {}).items():
        for method, operation in item.items():
            if method not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
            } or not isinstance(operation, dict):
                continue
            op = operation.get("operationId")
            if not op:
                continue
            related = [case for case in db_cases if case["source"]["operationId"] == op]
            positives = [case for case in related if success(case)]
            body_schema = schema_for(
                (operation.get("requestBody") or {}).get("content")
            )
            if method in {"post", "put", "patch"}:
                for field in leaves(body_schema):
                    found = [
                        case for case in positives if covers(request_maps(case), field)
                    ]
                    add(
                        op,
                        "DB保存",
                        field,
                        "リクエスト値→DB",
                        found,
                        "配列INSERTの明示した対応を集計。DB保存不要の項目かも含めて人が確認。従来形式・InfluxDBの対応は自動判定対象外",
                        missing="要手動確認"
                        if any(
                            case["definition"].get("dbCheck")
                            or case["definition"].get("expectationRules")
                            or case["definition"].get("influxMutation")
                            for case in positives
                        )
                        else "未照合",
                    )
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                for field in leaves(schema_for((response or {}).get("content"))):
                    found = [
                        case
                        for case in positives
                        if str(case["definition"]["responseCheck"]["expectedStatus"])
                        == str(status)
                        and covers(response_maps(case), field)
                    ]
                    add(
                        op,
                        "DB取得",
                        field,
                        f"{status}の返却値→DB",
                        found,
                        "SQL結果またはDB取得の対応設定。期待値ルールによる照合はルール詳細を別途確認。SQLの抽出条件の正しさや全DB列の照合を保証しない",
                        missing="要手動確認" if any(case["definition"].get("expectationRules") for case in positives) else "未照合",
                    )
            for rule in body_schema.get("x-otg-presence-rules", []):
                names = rule.get("fields", [])
                if rule.get("kind") != "atLeastOne" or len(names) != 2:
                    continue
                for present in [
                    (True, False),
                    (False, True),
                    (True, True),
                    (False, False),
                ]:
                    found = []
                    for case in related:
                        request = case["definition"]["request"].get("body", {})
                        if (
                            not isinstance(request, dict)
                            or tuple(name in request for name in names) != present
                        ):
                            continue
                        status = (case["definition"].get("responseCheck") or {}).get(
                            "expectedStatus"
                        )
                        if (
                            success(case)
                            if any(present)
                            else isinstance(status, int) and status >= 400
                        ):
                            found.append(case)
                    add(
                        op,
                        "body",
                        " / ".join(names),
                        "存在条件: "
                        + ", ".join(
                            name + ("あり" if exists else "なし")
                            for name, exists in zip(names, present, strict=True)
                        ),
                        found,
                        "存在の組合せのケース有無。両方指定時の優先順位・値の妥当性は別途確認",
                        missing="ケース未設定",
                    )
            inputs = [
                ("body", key, child, key in body_schema.get("required", []))
                for key, child in body_schema.get("properties", {}).items()
            ]
            parameters = {}
            for p in [*item.get("parameters", []), *operation.get("parameters", [])]:
                if p.get("in") in {"query", "path"}:
                    parameters[(p["in"], p["name"])] = p
            inputs += [
                (loc, name, p.get("schema", {}), bool(p.get("required")))
                for (loc, name), p in parameters.items()
            ]
            for loc, name, schema, required in inputs:
                if not isinstance(schema, dict):
                    continue
                values = schema.get(
                    "enum", [True, False] if schema.get("type") == "boolean" else []
                )
                variants = [(json.dumps(v, ensure_ascii=False), v) for v in values]
                if not required:
                    variants.append(("省略", MISSING))
                if schema.get("type") == "array":
                    variants.extend([("1要素", ONE), ("複数要素", MANY)])
                for label, value in variants:
                    found = []
                    for case in positives:
                        req = case["definition"]["request"].get(
                            {
                                "body": "body",
                                "query": "queryParams",
                                "path": "pathParams",
                            }[loc],
                            {},
                        )
                        actual = (
                            req.get(name, MISSING) if isinstance(req, dict) else MISSING
                        )
                        match = (
                            actual is MISSING
                            if value is MISSING
                            else (
                                isinstance(actual, list)
                                and (
                                    len(actual) == 1
                                    if value is ONE
                                    else len(actual) > 1
                                )
                                if value is ONE or value is MANY
                                else actual is not MISSING
                                and type(actual) is type(value)
                                and actual == value
                            )
                        )
                        if match:
                            found.append(case)
                    add(
                        op,
                        loc,
                        name,
                        "正常条件: " + label,
                        found,
                        "該当入力のケースの有無。条件の直積・業務分岐・必要DBデータの有無は保証しない",
                        missing="ケース未設定",
                    )
            errors = [
                case
                for case in related
                if isinstance(
                    (case["definition"].get("responseCheck") or {}).get(
                        "expectedStatus"
                    ),
                    int,
                )
                and case["definition"]["responseCheck"]["expectedStatus"] >= 400
            ]
            kinds = {'combinations': '項目の組み合わせ'}
            if method == 'get':
                kinds.update(boundary='期間の境界', priority='データの優先順位', empty='対象データ0件')
            for kind, label in kinds.items():
                matched = [case for case in related if (case['definition'].get('ruleTest') or {}).get('kind') == kind]
                conditions = list(dict.fromkeys(case['definition']['ruleTest']['condition'] for case in matched))
                add(op, '共通ルール', label, '明示した試験条件', matched,
                    ('登録条件: ' + ' / '.join(conditions) + '。設定外の条件・値・業務分岐の網羅は保証しない')
                    if matched else 'この条件を仕様が持つ場合は共通ルールのケースを設定してください。該当するかは人が確認',
                    missing='要手動確認')
            if method in {"post", "put", "patch", "delete"}:
                for case in errors:
                    add(
                        op,
                        "DB変更なし",
                        case["caseId"],
                        "異常応答時の副作用",
                        [case] if case["definition"].get("dbUnchanged") else [],
                        "指定されたDB範囲の変更なし確認。範囲外のテーブルは未確認",
                    )
            add(
                op,
                "適用範囲",
                route,
                "未確定の範囲",
                [],
                "DB列一覧・SQLの業務条件・組合せ網羅・同時実行・非同期反映はこの一覧では判定しない",
                missing="要手動確認",
            )
    return rows


def execution_summary(row, statuses):
    ids = row.get("caseIds", [])
    if not ids:
        return "未試験（対応ケースなし）"
    counts = {
        key: sum(statuses.get(case, "not-run") == key for case in ids)
        for key in ["passed", "failed", "error", "warning", "skipped", "not-run"]
    }
    labels = {
        "passed": "合格",
        "failed": "不合格",
        "error": "エラー",
        "warning": "未確認",
        "skipped": "スキップ",
        "not-run": "未実行",
    }
    return " / ".join(
        f"{labels[key]} {value}件" for key, value in counts.items() if value
    )
