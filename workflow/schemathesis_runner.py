from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


def build_schemathesis_command(
    executable: str,
    schema_path: Path,
    base_url: str,
    junit_path: Path,
    cassette_path: Path | None,
    *,
    include_mutating: bool,
    max_examples: int,
    selected_operations: tuple[str, ...] = (),
    config_path: Path | None = None,
) -> list[str]:
    if not isinstance(max_examples, int) or isinstance(max_examples, bool) or not 1 <= max_examples <= 100:
        raise ValueError("max_examples は1..100の整数で指定してください")
    if not isinstance(include_mutating, bool):
        raise ValueError("include_mutating は真偽値で指定してください")
    if any(not item.strip() for item in selected_operations) or len(set(selected_operations)) != len(selected_operations):
        raise ValueError("selected operation ID は空欄や重複を含めず指定してください")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url は http:// または https:// で指定してください")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Base URLにユーザー名やパスワードを含めないでください")

    command = [executable]
    if config_path is not None:
        command.extend(["--config-file", str(config_path)])
    command.extend([
        "run", str(schema_path),
        "--url", base_url,
        "--workers", "1",
        "--phases", "examples,coverage,fuzzing",
        "--max-examples", str(max_examples),
        "--seed", "1",
        "--request-timeout", "10",
        "--rate-limit", "5/s",
        "--generation-database", "none",
        "--report-junit-path", str(junit_path),
    ])
    if cassette_path is None:
        command.extend(["--report", "junit"])
    else:
        command.extend([
            "--report", "junit,vcr",
            "--report-vcr-path", str(cassette_path),
        ])
    if not include_mutating:
        command.extend(["--include-method", "GET"])
    for operation_id in selected_operations:
        command.append(f"--include-operation-id={operation_id}")
    return command
