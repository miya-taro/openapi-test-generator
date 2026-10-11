"""Bounded numeric candidate search, respecting integer and multipleOf lattices."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from fractions import Fraction


def numeric_candidates(schema, preferred=()):
    types = schema.get("type", "number")
    integer = (
        types == "integer"
        or isinstance(types, list)
        and "integer" in types
        and "number" not in types
    )
    try:
        bounds = {
            k: Decimal(str(schema[k]))
            for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
            if isinstance(schema.get(k), (int, float))
            and not isinstance(schema[k], bool)
        }
        lower = max((v for k, v in bounds.items() if "inimum" in k), default=None)
        upper = min((v for k, v in bounds.items() if "aximum" in k), default=None)
        multiple = schema.get("multipleOf")
        step = Decimal(1) if integer else Decimal("0.1")
        if multiple is not None and multiple > 0:
            step = (
                Decimal(Fraction(str(multiple)).numerator)
                if integer
                else Decimal(str(multiple))
            )
        elif not integer and lower is not None and upper is not None and upper > lower:
            step = min(step, (upper - lower) / 10)
        targets = [Decimal(str(v)) for v in preferred]
        targets += list(bounds.values())
        if lower is not None and upper is not None:
            targets.append((lower + upper) / 2)
        targets += [Decimal(0), Decimal(1), Decimal(-1), step * 2]
        values = []
        for target in targets:
            candidates = [target]
            for rounding in (ROUND_CEILING, ROUND_FLOOR):
                snapped = (target / step).to_integral_value(rounding=rounding) * step
                candidates.extend((snapped, snapped + step, snapped - step))
            for value in candidates:
                if (
                    not value.is_finite()
                    or integer
                    and value != value.to_integral_value()
                ):
                    continue
                number = int(value) if integer else float(value)
                if number not in values:
                    values.append(number)
        return values
    except (InvalidOperation, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return []
