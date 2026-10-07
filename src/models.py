"""共有型定義（TypedDict）。

実行時のデータは全てプレーンな dict として流れる。ここでの型は
ドキュメント・IDE補完用であり、ランタイムの挙動には影響しない。
"""
from __future__ import annotations
from typing import TypedDict, NotRequired, Literal, Union

ParamIn = Literal["path", "query", "header", "cookie"]


class ResponseInfo(TypedDict):
    contentTypes: list[str]
    headerNames: list[str]
    headers: dict  # ヘッダ名 -> OpenAPIのheaderオブジェクト（schema/example等、生の定義）


class ResolvedSchema(TypedDict, total=False):
    type: str | list[str]
    format: str
    enum: list[object]
    const: object
    example: object
    default: object
    minimum: float
    maximum: float
    exclusiveMinimum: float | bool
    exclusiveMaximum: float | bool
    multipleOf: float
    minLength: int
    maxLength: int
    pattern: str
    minItems: int
    maxItems: int
    uniqueItems: bool
    minProperties: int
    maxProperties: int
    required: list[str]
    properties: dict[str, "ResolvedSchema"]
    additionalProperties: bool | "ResolvedSchema"
    items: "ResolvedSchema"
    nullable: bool
    # parser.py の正規化後は exclusiveMinimum/Maximum は常に float
    # （OAS 3.0 の bool 形式は minimum/maximum を吸収した数値形式に変換される）


class ParamSpec(TypedDict):
    operationId: str
    path: str
    method: str
    in_: ParamIn  # 実データのキーは "in"（Python予約語のため別名を用意）
    name: str
    required: bool
    schema: ResolvedSchema
    successStatus: str
    responsesInfo: dict[str, ResponseInfo]


class BodyFieldSpec(TypedDict):
    operationId: str
    path: str
    method: str
    fieldPath: str
    required: bool
    schema: ResolvedSchema
    successStatus: str
    responsesInfo: dict[str, ResponseInfo]


FieldSpec = Union[ParamSpec, BodyFieldSpec]


class TestCase(TypedDict):
    id: str
    operationId: str
    summary: str
    path: str
    method: str
    in_: str
    paramName: str
    keyword: str
    perspective: str
    inputValue: str
    expectedStatus: str
    expectedResponseBody: str
    expectedResponseHeader: str
    expectedResponseTime: str
    expectedResult: str
    verdict: str
    notes: str


class AuthSpec(TypedDict):
    operationId: str
    path: str
    method: str
    schemeType: Literal["bearer", "apiKey", "basic", "other"]
    headerName: str
    securitySchemes: list[dict[str, str]]
    successStatus: str
    responsesInfo: dict[str, ResponseInfo]


class GenerateOptions(TypedDict):
    includeNormal: bool
    includeAbnormal: bool
    enumFullCoverage: NotRequired[bool]
    oneOfFullCoverage: NotRequired[bool]
