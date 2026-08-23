from src.id_assigner import assign_ids


def _case(operation_id: str, path: str, method: str, in_: str, param_name: str, perspective: str) -> dict:
    return {
        "operationId": operation_id,
        "path": path,
        "method": method,
        "in": in_,
        "paramName": param_name,
        "perspective": perspective,
        "verdict": "",
    }


def test_ids_prefixed_with_operation_id_and_sequential():
    cases = [
        _case("getUser", "/users/{id}", "GET", "path", "id", "正常系_最小値"),
        _case("getUser", "/users/{id}", "GET", "path", "id", "正常系_最大値"),
    ]
    result = assign_ids(cases)
    assert result[0]["id"] == "TC-getUser-001"
    assert result[1]["id"] == "TC-getUser-002"


def test_same_operation_multiple_cases_not_treated_as_collision():
    # 同一 (path, method) から生成された複数ケースは同じ operationId のまま、
    # サフィックスは付与されない
    cases = [
        _case("createUser", "/users", "POST", "body", "name", "異常系_必須欠落"),
        _case("createUser", "/users", "POST", "body", "email", "異常系_必須欠落"),
        _case("createUser", "/users", "POST", "body", "age", "正常系_省略"),
    ]
    result = assign_ids(cases)
    assert all(r["id"].startswith("TC-createUser-") for r in result)
    assert not any("_2" in r["id"] for r in result)


def test_different_operations_with_colliding_operation_id_get_suffixed():
    # 異なる (path, method) が同じ operationId 文字列を持つ場合（真の衝突）は
    # 2件目以降に _2, _3... のサフィックスを付与し、別グループとして連番する
    cases = [
        _case("listItems", "/a/items", "GET", "query", "page", "正常系_省略"),
        _case("listItems", "/b/items", "GET", "query", "page", "正常系_省略"),
        _case("listItems", "/b/items", "GET", "query", "limit", "正常系_省略"),
    ]
    result = assign_ids(cases)
    a_group = [r for r in result if r["path"] == "/a/items"]
    b_group = [r for r in result if r["path"] == "/b/items"]

    assert all(r["id"].startswith("TC-listItems-") for r in a_group)
    assert all(not r["id"].startswith("TC-listItems-") or "_2" in r["id"] for r in b_group)
    assert all(r["id"].startswith("TC-listItems_2-") for r in b_group)
    # 別グループとして 001 から採番される
    assert b_group[0]["id"] == "TC-listItems_2-001"


def test_sort_order_path_before_query_before_body():
    cases = [
        _case("op", "/x", "POST", "body", "field", "正常系_省略"),
        _case("op", "/x", "POST", "query", "q", "正常系_省略"),
        _case("op", "/x", "POST", "path", "id", "正常系_省略"),
    ]
    result = assign_ids(cases)
    assert [r["in"] for r in result] == ["path", "query", "body"]


def test_sort_order_normal_before_abnormal_within_same_param():
    cases = [
        _case("op", "/x", "GET", "query", "q", "異常系_型不正"),
        _case("op", "/x", "GET", "query", "q", "正常系_省略"),
    ]
    result = assign_ids(cases)
    assert result[0]["perspective"].startswith("正常系")
    assert result[1]["perspective"].startswith("異常系")
