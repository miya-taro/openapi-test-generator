"""Complete non-targeted body presence constraints around a field-level test."""
from __future__ import annotations

from collections.abc import Callable


def complete_presence(body: dict, schema: dict, example: Callable, target: str | None = None) -> dict:
    """Preserve the tested field (including intentional omission) and fix its companions.

    This applies equally to normal and abnormal values: a format/type test must not
    accidentally pass because a different presence constraint was violated.
    """
    rules = schema.get("x-otg-presence-rules") or []
    properties = schema.get("properties") or {}
    parents = {name: name for name in properties}

    def root(name):
        while parents[name] != name:
            name = parents[name]
        return name

    for rule in rules:
        if rule["kind"] == "together":
            first, second = rule["fields"]
            parents[root(second)] = root(first)
    groups = {}
    for name in properties:
        groups.setdefault(root(name), []).append(name)
    absent_group = root(target) if target in properties and target not in body else None
    if absent_group is not None:
        for name in groups[absent_group]:
            body.pop(name, None)

    def include(group):
        for name in groups[group]:
            if name not in body:
                body[name] = example(properties[name])

    for group, names in groups.items():
        if any(name in body for name in names):
            include(group)
    for rule in rules:
        if rule["kind"] != "atLeastOne" or any(name in body for name in rule["fields"]):
            continue
        choice = next((name for name in rule["fields"] if root(name) != absent_group), None)
        if choice is None:
            raise ValueError("項目間の必須条件を満たす試験リクエストを生成できません")
        include(root(choice))
    for rule in rules:
        sent = [name in body for name in rule["fields"]]
        valid = any(sent) if rule["kind"] == "atLeastOne" else len(set(sent)) == 1
        if not valid:
            raise ValueError("項目間の必須条件を満たす試験リクエストを生成できません")
    return body
