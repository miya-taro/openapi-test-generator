"""Keep the validation contract independent of the generator's flattened view."""
from copy import deepcopy

CONTRACT = "_otgContract"
MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
SINGLES = {"items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
           "contains", "propertyNames", "not", "if", "then", "else"}
LISTS = {"allOf", "anyOf", "oneOf", "prefixItems"}


def map_children(schema, transform):
    result = deepcopy(schema)
    if not isinstance(result, dict):
        return result
    for key in MAPS:
        if isinstance(result.get(key), dict):
            result[key] = {name: transform(child) for name, child in result[key].items()}
    for key in SINGLES:
        if isinstance(result.get(key), (dict, bool)):
            result[key] = transform(result[key])
    for key in LISTS:
        if isinstance(result.get(key), list):
            result[key] = [transform(child) for child in result[key]]
    return result


def validation_schema(schema):
    """Restore exact combinators recursively, including inside arrays and objects."""
    if isinstance(schema, dict) and CONTRACT in schema:
        schema = schema[CONTRACT]
    return map_children(schema, validation_schema)
