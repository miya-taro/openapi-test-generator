#!/usr/bin/env python3
"""openapi-test-gen CLI: OpenAPI 3.x からインターフェース観点テスト仕様を生成する。"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# `python src/cli.py ...` として直接実行しても `src` パッケージを import できるように
# リポジトリルートを sys.path へ追加する。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows のコンソール既定コードページ(cp932等)では日本語出力が文字化けするため、
# 標準出力/標準エラーを UTF-8 に固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from src import logger as log
from src.parser import parse_openapi, OpenAPIParseError
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.renderer.json_output import build_output, write_output
from src.renderer.excel_output import write_excel_output


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="openapi-test-gen",
        description="OpenAPI 3.x からインターフェース観点テスト仕様 JSON を自動生成します",
    )
    parser.add_argument("input", help="openapi.json のファイルパス")
    parser.add_argument("-o", "--output", default="./test_cases.json", help="出力ファイルパス")
    parser.add_argument("--operations", help="対象 operationId をカンマ区切りで指定")
    parser.add_argument("--exclude-ops", help="除外する operationId をカンマ区切りで指定")
    parser.add_argument("--no-normal", action="store_true", help="正常系ケースを生成しない")
    parser.add_argument("--no-abnormal", action="store_true", help="異常系ケースを生成しない")
    parser.add_argument("--log-level", default="info", help="ログレベル (debug/info/warn/error)")
    parser.add_argument("--dry-run", action="store_true", help="ケース数のみ表示し、ファイルを出力しない")
    parser.add_argument("--fail-if-exists", action="store_true", help="出力先ファイルが存在する場合はエラー終了")
    parser.add_argument("--excel-output", help="Excel (.xlsx) ファイルも出力する場合にパスを指定")

    args = parser.parse_args()

    log.set_log_level(args.log_level)

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        log.error({"path": str(input_path)}, "入力ファイルが見つかりません")
        return 1

    output_path = Path(args.output).resolve()
    if args.fail_if_exists and output_path.exists():
        log.error({"path": str(output_path)}, "出力先ファイルがすでに存在します (--fail-if-exists)")
        return 3

    filter_ops = set(s.strip() for s in args.operations.split(",")) if args.operations else None
    exclude_ops = set(s.strip() for s in args.exclude_ops.split(",")) if args.exclude_ops else None

    gen_opts = {
        "includeNormal": not args.no_normal,
        "includeAbnormal": not args.no_abnormal,
        # enum/oneOf・anyOfのバリアント網羅は、ユーザーに都度選ばせず常に全件生成する。
        "enumFullCoverage": True,
        "oneOfFullCoverage": True,
    }

    try:
        # Phase 1: Parse
        log.info({"input": str(input_path)}, "Phase 1: パース開始")
        api = parse_openapi(str(input_path))

        # Phase 2: Extract
        log.info("Phase 2: 抽出開始")
        param_specs, body_specs = extract_specs(api)
        auth_specs = extract_auth_specs(api)

        if filter_ops:
            param_specs = [s for s in param_specs if s["operationId"] in filter_ops]
            body_specs = [s for s in body_specs if s["operationId"] in filter_ops]
            auth_specs = [s for s in auth_specs if s["operationId"] in filter_ops]
        if exclude_ops:
            param_specs = [s for s in param_specs if s["operationId"] not in exclude_ops]
            body_specs = [s for s in body_specs if s["operationId"] not in exclude_ops]
            auth_specs = [s for s in auth_specs if s["operationId"] not in exclude_ops]

        log.info(
            {"params": len(param_specs), "bodyFields": len(body_specs), "authOps": len(auth_specs)},
            "Phase 2: 抽出完了",
        )

        # Phase 3: Generate
        log.info("Phase 3: ケース生成開始")
        raw_cases = generate_test_cases(param_specs, body_specs, gen_opts, auth_specs)
        log.info({"count": len(raw_cases)}, "Phase 3: ケース生成完了")

        # Phase 4: ID Assign
        log.info("Phase 4: ID 採番開始")
        cases = assign_ids(raw_cases)

        # dry-run
        if args.dry_run:
            normal = sum(1 for c in cases if c["perspective"].startswith("正常系"))
            abnormal = sum(1 for c in cases if c["perspective"].startswith("異常系"))
            print(f"生成ケース数: {len(cases)} 件（正常系: {normal} 件、異常系: {abnormal} 件）")
            return 0

        # Phase 5: Render
        log.info("Phase 5: JSON 出力開始")
        output = build_output(cases, str(input_path))
        write_output(output, str(output_path))
        log.info({"output": str(output_path), "total": len(cases)}, "出力完了")
        print(f"✓ {len(cases)} 件のテストケースを {output_path} に出力しました")

        # Excel 出力（オプション）
        if args.excel_output:
            excel_path = Path(args.excel_output).resolve()
            log.info({"output": str(excel_path)}, "Excel 出力開始")
            write_excel_output(output, str(excel_path))
            log.info({"output": str(excel_path)}, "Excel 出力完了")
            print(f"✓ Excel を {excel_path} に出力しました")

        return 0

    except OpenAPIParseError as e:
        message = str(e)
        if "OpenAPI 3.x のみ対応" in message or "解析に失敗" in message:
            log.error({"error": message}, "入力ファイルエラー")
            return 1
        if "$ref" in message:
            log.warn({"error": message}, "$ref 解決エラー")
            return 2
        log.error({"error": message}, "出力エラー")
        return 3
    except Exception as e:  # noqa: BLE001 - CLI の最終防衛ライン
        log.error({"error": str(e)}, "出力エラー")
        return 3


if __name__ == "__main__":
    sys.exit(main())
