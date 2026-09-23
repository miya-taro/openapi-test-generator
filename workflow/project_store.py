from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from workflow.models import ProjectConfig, ProjectConfigError


_REQUIRED_KEYS = {"schemaVersion", "name", "openapiPath", "baseUrl", "outputDir"}
_OPTIONAL_KEYS = {
    "selectedOperations",
    "setupSqlPath",
    "teardownSqlPath",
    "dbScenariosPath",
}
_ALLOWED_KEYS = _REQUIRED_KEYS | _OPTIONAL_KEYS
_SECRET_FRAGMENTS = ("password", "secret", "token", "cookie", "authorization")


def _resolve_path(project_dir: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"{field} は空でない文字列で指定してください")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve(strict=False)


def _optional_path(project_dir: Path, value: object, field: str) -> Path | None:
    if value is None or value == "":
        return None
    return _resolve_path(project_dir, value, field)


def _validate_keys(data: dict) -> None:
    missing = sorted(_REQUIRED_KEYS - data.keys())
    if missing:
        raise ProjectConfigError(f"必須項目がありません: {', '.join(missing)}")

    unknown = sorted(set(data) - _ALLOWED_KEYS)
    secret = [
        key for key in unknown if any(fragment in key.lower() for fragment in _SECRET_FRAGMENTS)
    ]
    if secret:
        raise ProjectConfigError(
            "秘密情報はプロジェクト設定へ保存できません: " + ", ".join(secret)
        )
    if unknown:
        raise ProjectConfigError(f"未対応の項目があります: {', '.join(unknown)}")


def _validate_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise ProjectConfigError("Base URL は文字列で指定してください")
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProjectConfigError("Base URL は http:// または https:// で指定してください")
    return base_url


def load_project(path: Path) -> ProjectConfig:
    project_file = Path(path).resolve(strict=False)
    try:
        data = json.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectConfigError(f"プロジェクト設定を読み込めません: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectConfigError("プロジェクト設定のルートはオブジェクトである必要があります")

    _validate_keys(data)
    if data["schemaVersion"] != 1:
        raise ProjectConfigError("対応していないschemaVersionです（対応値: 1）")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise ProjectConfigError("name は空でない文字列で指定してください")

    operations = data.get("selectedOperations", [])
    if not isinstance(operations, list) or not all(
        isinstance(item, str) and item.strip() for item in operations
    ):
        raise ProjectConfigError("selectedOperations は空でない文字列の配列で指定してください")

    project_dir = project_file.parent
    return ProjectConfig(
        schema_version=1,
        name=data["name"].strip(),
        project_dir=project_dir,
        openapi_path=_resolve_path(project_dir, data["openapiPath"], "openapiPath"),
        base_url=_validate_base_url(data["baseUrl"]),
        output_dir=_resolve_path(project_dir, data["outputDir"], "outputDir"),
        selected_operations=tuple(item.strip() for item in operations),
        setup_sql_path=_optional_path(project_dir, data.get("setupSqlPath"), "setupSqlPath"),
        teardown_sql_path=_optional_path(
            project_dir, data.get("teardownSqlPath"), "teardownSqlPath"
        ),
        db_scenarios_path=_optional_path(
            project_dir, data.get("dbScenariosPath"), "dbScenariosPath"
        ),
    )


def _portable_path(path: Path | None, project_dir: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve(strict=False)
    try:
        return os.path.relpath(resolved, project_dir)
    except ValueError:
        return str(resolved)


def save_project(config: ProjectConfig, path: Path) -> None:
    project_file = Path(path).resolve(strict=False)
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_dir = project_file.parent
    data: dict[str, object] = {
        "schemaVersion": config.schema_version,
        "name": config.name,
        "openapiPath": _portable_path(config.openapi_path, project_dir),
        "baseUrl": config.base_url,
        "outputDir": _portable_path(config.output_dir, project_dir),
    }
    if config.selected_operations:
        data["selectedOperations"] = list(config.selected_operations)
    optional_paths = {
        "setupSqlPath": config.setup_sql_path,
        "teardownSqlPath": config.teardown_sql_path,
        "dbScenariosPath": config.db_scenarios_path,
    }
    for key, value in optional_paths.items():
        if value is not None:
            data[key] = _portable_path(value, project_dir)

    project_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
