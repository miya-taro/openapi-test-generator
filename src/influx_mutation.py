"""Explicit, serializable single-point mutation contract shared by UI and runner."""
import math

from src.db_scope import IDENTIFIER
from rfc3339_validator import validate_rfc3339


def validate_mutation(value):
    if not isinstance(value, dict) or set(value) - {'measurement', 'time', 'tags', 'fields', 'action', 'preserve_unmapped'}:
        raise ValueError('InfluxDB変更確認の設定形式が不正です')
    if value.get('action') not in ('insert', 'update', 'delete'):
        raise ValueError('InfluxDB変更確認はinsert・update・deleteを指定してください')
    measurement = value.get('measurement')
    if not isinstance(measurement, str) or not IDENTIFIER.fullmatch(measurement):
        raise ValueError('有効なmeasurement名が必要です')
    when = value.get('time')
    if not isinstance(when, str) or not validate_rfc3339(when.upper()):
        raise ValueError('ポイント時刻はタイムゾーン付き日時を指定してください')
    tags = value.get('tags')
    if not isinstance(tags, dict) or not all(isinstance(k, str) and IDENTIFIER.fullmatch(k) and k != 'time'
                                           and isinstance(v, str) and v for k, v in tags.items()):
        raise ValueError('タグはタグ名と空でない文字列値のオブジェクトにしてください')
    fields = value.get('fields', {})
    if not isinstance(fields, dict) or not all(isinstance(k, str) and IDENTIFIER.fullmatch(k) and k != 'time'
                                             and k not in tags for k in fields):
        raise ValueError('期待フィールドはtime・タグと重複しない項目にしてください')
    for v in fields.values():
        if not isinstance(v, (str, int, float, bool)) or (isinstance(v, (int, float)) and not math.isfinite(v)):
            raise ValueError('期待フィールドには文字列・有限数値・booleanを指定してください')
    if value['action'] != 'delete' and not fields:
        raise ValueError('保存・更新で照合するフィールドを1件以上指定してください')
    if value['action'] == 'delete' and fields:
        raise ValueError('削除確認には期待フィールドを設定しません')
    if not isinstance(value.get('preserve_unmapped', False), bool):
        raise ValueError('未指定フィールドの維持設定は真偽値にしてください')
    return value
