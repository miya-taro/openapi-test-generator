# Contract validation API

`validation_api.py` is a small local HTTP target for exercising the request and response contract checks. Its record-creation endpoint requires query, header, cookie, and JSON-body inputs together, so an abnormal case can verify one invalid or omitted value while the other required inputs remain valid. It validates parameters and JSON bodies against `validation_openapi.json`, returns documented `400`/`422`/`415` responses for rejected requests, and emits schema-valid success responses. It has no database or business rules.

From the repository root, run the generator and runner against it:

```sh
python -m pip install -r requirements-runtime.txt -r docs/requirements-mock.txt
python docs/run_validation_e2e.py
```

To keep the generated JSON, test specification, and result workbook:

```sh
python docs/run_validation_e2e.py --output-dir /tmp/openapi-validation-e2e
```

The script starts the API on loopback, waits for `/health`, executes all generated normal and abnormal cases, then stops the API. It does not call an external service.
