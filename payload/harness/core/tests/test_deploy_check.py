"""QG3 deploy check: API contract break rules, test runs and the verdict.

No database and no service: the OpenAPI schemas are built here, the tests are stand-in
files in a temporary folder.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_check as dc  # noqa: E402
import harness_config  # noqa: E402


def json_body(schema: dict, required: bool = True) -> dict:
    return {"required": required, "content": {"application/json": {"schema": schema}}}


def ok(schema: dict) -> dict:
    return {"200": {"content": {"application/json": {"schema": schema}}}}


BASE = {
    "openapi": "3.1.0",
    "paths": {
        "/ask": {"post": {
            "requestBody": json_body({"$ref": "#/components/schemas/AskRequest"}),
            "responses": ok({"$ref": "#/components/schemas/AskResponse"})}},
        "/tickets/{tid}/status": {"post": {
            "parameters": [{"in": "path", "name": "tid", "required": True,
                            "schema": {"type": "integer"}}],
            "requestBody": json_body({"type": "object", "required": ["status"],
                                      "properties": {"status": {
                                          "type": "string", "enum": ["NEW", "OPEN", "DONE"]}}}),
            "responses": ok({})}},
        "/history": {"get": {
            "parameters": [{"in": "query", "name": "limit", "required": False,
                            "schema": {"type": "integer"}}],
            "responses": ok({"type": "array", "items": {
                "type": "object", "required": ["id"],
                "properties": {"id": {"type": "string"},
                               "kind": {"type": "string", "enum": ["a", "b"]}}}})}},
    },
    "components": {"schemas": {
        "AskRequest": {"type": "object", "required": ["question"],
                       "properties": {"question": {"type": "string"},
                                      "lang": {"anyOf": [{"type": "string"}, {"type": "null"}]}}},
        "AskResponse": {"type": "object", "required": ["query_id", "value"],
                        "properties": {"query_id": {"type": "string"},
                                       "value": {"type": "integer"}}},
    }},
}


def diff(mutate) -> list[dict]:
    new = copy.deepcopy(BASE)
    mutate(new)
    return dc.contract_diff(BASE, new)


def breaking(found: list[dict]) -> list[str]:
    return [" ".join(x for x in (c["op"], c["where"], c["what"]) if x)
            for c in found if c["kind"] == "breaking"]


class Contract(unittest.TestCase):
    def test_same_contract_no_changes(self):
        self.assertEqual(dc.contract_diff(BASE, copy.deepcopy(BASE)), [])

    def test_removed_operation_breaks(self):
        self.assertEqual(breaking(diff(lambda s: s["paths"].pop("/history"))),
                         ["GET /history operation removed"])

    def test_new_operation_is_not_a_break(self):
        got = diff(lambda s: s["paths"].update({"/saved": {"get": {"responses": ok({})}}}))
        self.assertEqual(breaking(got), [])
        self.assertEqual(got[0]["what"], "new operation")

    def test_renamed_path_parameter_is_the_same_operation(self):
        def rename(s):
            item = s["paths"].pop("/tickets/{tid}/status")
            item["post"]["parameters"][0]["name"] = "ticket_id"
            s["paths"]["/tickets/{ticket_id}/status"] = item
        self.assertEqual(breaking(diff(rename)), [])

    def test_parameters(self):
        add = lambda req: lambda s: s["paths"]["/history"]["get"]["parameters"].append(  # noqa: E731
            {"in": "query", "name": "q", "required": req, "schema": {"type": "string"}})
        self.assertEqual(breaking(diff(add(True))), ["GET /history query:q new required parameter"])
        self.assertEqual(breaking(diff(add(False))), [])
        got = diff(lambda s: s["paths"]["/history"]["get"]["parameters"][0].update(required=True))
        self.assertEqual(breaking(got), ["GET /history query:limit parameter became required"])
        got = diff(lambda s: s["paths"]["/history"]["get"]["parameters"][0].update(
            schema={"type": "string"}))
        self.assertTrue(breaking(got) and "type integer became string" in breaking(got)[0])
        got = diff(lambda s: s["paths"]["/history"]["get"]["parameters"][0].update(
            schema={"type": "number"}))
        self.assertEqual(breaking(got), [], "integer to number in a request is wider")

    def test_request_body_through_ref(self):
        req = lambda s: s["components"]["schemas"]["AskRequest"]  # noqa: E731
        got = diff(lambda s: (req(s)["properties"].update(mode={"type": "string"}),
                              req(s).update(required=["question", "mode"])))
        self.assertEqual(breaking(got), ["POST /ask body.mode new required request field"])
        got = diff(lambda s: req(s)["properties"].update(mode={"type": "string"}))
        self.assertEqual(breaking(got), [])
        got = diff(lambda s: req(s).update(required=["question", "lang"]))
        self.assertEqual(breaking(got), ["POST /ask body.lang request field became required"])
        got = diff(lambda s: req(s)["properties"].update(lang={"type": "string"}))
        self.assertEqual(breaking(got), ["POST /ask body.lang null no longer accepted"])
        got = diff(lambda s: req(s)["properties"].pop("lang"))
        self.assertEqual(breaking(got), [], "an extra request field is ignored")

    def test_response(self):
        resp = lambda s: s["components"]["schemas"]["AskResponse"]  # noqa: E731
        got = diff(lambda s: resp(s)["properties"].pop("value"))
        self.assertTrue(any("value response field removed" in b for b in breaking(got)), got)
        got = diff(lambda s: resp(s).update(required=["query_id"]))
        self.assertEqual(breaking(got), ["POST /ask 200.value response field became optional"])
        got = diff(lambda s: s["paths"]["/history"]["get"]["responses"]["200"]["content"]
                   ["application/json"]["schema"]["items"]["properties"]["kind"]["enum"].append("c"))
        self.assertEqual(breaking(got), ["GET /history 200[].kind new values ['c']"])

    def test_enum_in_request(self):
        enum = lambda s: s["paths"]["/tickets/{tid}/status"]["post"]["requestBody"]["content"] \
            ["application/json"]["schema"]["properties"]["status"]["enum"]  # noqa: E731
        self.assertEqual(breaking(diff(lambda s: enum(s).remove("OPEN"))),
                         ["POST /tickets/{tid}/status body.status values removed ['OPEN']"])
        self.assertEqual(breaking(diff(lambda s: enum(s).append("HOLD"))), [])


class Verdict(unittest.TestCase):
    def test_breaking_blocks_unless_allowed(self):
        contract = {"changes": [{"kind": "breaking", "op": "GET /x", "where": "", "what": "removed"}]}
        tests = [{"file": "test_a.py", "rc": 0}]
        self.assertEqual(dc.verdict(contract, tests, None, ())["verdict"], "blocked")
        self.assertEqual(dc.verdict(contract, tests, "clients updated", ())["verdict"], "pass")

    def test_failed_and_missing_security_tests(self):
        tests = [{"file": "test_a.py", "rc": 1}, {"file": "test_auth.py", "rc": 0}]
        v = dc.verdict({}, tests, None, ("test_auth.py", "test_access.py"))
        self.assertEqual(v["verdict"], "blocked")
        self.assertTrue(any("tests failed: test_a.py" in r for r in v["reasons"]))
        self.assertTrue(any("security tests missing: test_access.py" in r for r in v["reasons"]))

    def test_no_tests_is_not_a_pass(self):
        # B10: nothing ran, so there is no evidence.
        self.assertEqual(dc.verdict({}, [], None, ())["verdict"], "blocked")

    def test_contract_error_blocks(self):
        v = dc.verdict({"error": "no OpenAPI schema"}, [{"file": "t.py", "rc": 0}], None, ())
        self.assertEqual(v["verdict"], "blocked")


class Run(unittest.TestCase):
    def code(self, tests: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "tests").mkdir()
        for name, body in tests.items():
            (root / "tests" / name).write_text(body)
        return root

    def conf(self, **kw) -> dict:
        return {**harness_config.DEFAULTS["deploy_check"], **kw}

    def test_runs_each_file_and_reports(self):
        root = self.code({"test_ok.py": "import sys; sys.exit(0)\n",
                          "test_bad.py": "import sys; print('boom'); sys.exit(1)\n"})
        out = dc.check(root, None, None, self.conf())
        self.assertEqual(out["verdict"], "blocked")
        self.assertEqual((out["tests"]["files"], out["tests"]["passed"]), (2, 1))
        self.assertIn("boom", out["tests"]["failed"][0]["tail"][-1])

    def test_dropped_variables_do_not_reach_tests(self):
        root = self.code({"test_env.py": "import os, sys; sys.exit(1 if 'LIVE_DSN' in os.environ else 0)\n"})
        import os  # noqa: PLC0415
        os.environ["LIVE_DSN"] = "postgres://example"
        try:
            out = dc.check(root, None, None, self.conf(env_drop=["LIVE_DSN"]))
        finally:
            del os.environ["LIVE_DSN"]
        self.assertEqual(out["verdict"], "pass")

    def test_contract_against_current_code(self):
        new = self.code({"test_ok.py": "pass\n"})
        cur = self.code({"test_ok.py": "pass\n"})
        (new / "openapi.json").write_text(json.dumps({"paths": {}}))
        (cur / "openapi.json").write_text(json.dumps({"paths": {"/x": {"get": {"responses": {}}}}}))
        out = dc.check(new, cur, None, self.conf(openapi_cmd="cat openapi.json"))
        self.assertEqual(out["verdict"], "blocked")
        self.assertEqual(out["contract"]["breaking"][0]["what"], "operation removed")


if __name__ == "__main__":
    unittest.main()
