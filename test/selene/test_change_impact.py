import asyncio
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.tools.base import Tool as McpTool

from selene.changes.model import ProposedFileChange
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.impact.service import ChangeImpactAnalyzer
from selene.project import Project
from selene.tools import AnalyzeChangeTool
from solidlsp.ls_config import LanguageServerId


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()
    files = {
        "payment_api.py": "def charge(amount: int) -> int:\n    return amount\n",
        "client.py": "from payment_api import charge as imported_charge\n\ndef caller():\n    return imported_charge(1) + imported_charge(2)\n",
        "unrelated.py": "def charge(value):\n    return value\n\ndef other():\n    return charge(9)\n",
        "tests/test_flow.py": "from client import caller\n\ndef test_flow():\n    assert caller() == 3\n",
        "tests/test_dynamic.py": "import payment_api\n\ndef test_dynamic():\n    method = getattr(payment_api, 'charge')\n    assert method(1) == 1\n",
    }
    for path, content in files.items():
        (tmp_path / path).write_text(content)
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="impact", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )
    yield project
    project.shutdown()


def proposal(tmp_path, path="payment_api.py", new_content="def charge(amount: int, extra: int) -> int:\n    return amount + extra\n"):
    return ProposedFileChange(path, hashlib.sha256((tmp_path / path).read_bytes()).hexdigest(), new_content)


def test_without_semantics_report_separates_heuristics_and_unresolved_behavior(project, tmp_path):
    before = (tmp_path / "payment_api.py").read_bytes()
    raw = ChangeImpactAnalyzer(project).analyze(changes=(proposal(tmp_path),))
    report = json.loads(raw)
    assert report["status"] == "partial"
    assert report["language_server_relationships"] == []
    assert report["heuristic_candidates"]
    reasons = {item["reason"] for item in report["uncertainties"]}
    assert "semantic_backend_unavailable" in reasons
    assert "dynamic_lookup_or_dependency_injection_candidate" in reasons
    assert all(test["evidence"] == "heuristic" for test in report["recommended_tests"])
    assert report["changes"][0]["expected_sha256"] == hashlib.sha256(before).hexdigest()
    assert (tmp_path / "payment_api.py").read_bytes() == before
    assert report["budget"]["used"] == len(raw) <= 20000


def test_schema_pointer_and_generation_mappings_have_declared_versioned_evidence(project, tmp_path):
    schema = {"properties": {"name": {"type": "string"}, "count": {"type": "integer"}}}
    changed = {"properties": {"name": {"type": "integer"}, "count": {"type": "integer"}}}
    sources = {
        "api.json": schema,
        "consumer.json": {"$ref": "api.json#/properties/name"},
        "unaffected.json": {"$ref": "api.json#/properties/count"},
        "remote.json": {"$ref": "https://example.invalid/private-schema.json"},
        "selene-impact.json": {"version": 1, "generators": [{"inputs": ["api.json"], "outputs": ["generated_client.py"]}]},
    }
    for path, value in sources.items():
        (tmp_path / path).write_text(json.dumps(value))
    (tmp_path / "generated_client.py").write_text("class ApiClient:\n    name: str\n")
    report = json.loads(ChangeImpactAnalyzer(project).analyze(changes=(proposal(tmp_path, "api.json", json.dumps(changed)),)))
    relationships = report["declared_relationships"]
    assert {(item["target"]["path"], item["relationship"]) for item in relationships} == {
        ("consumer.json", "local_json_schema_reference"),
        ("generated_client.py", "declared_generation_input"),
    }
    for item in relationships:
        assert item["target"]["sha256"] == hashlib.sha256((tmp_path / item["target"]["path"]).read_bytes()).hexdigest()
        assert item["site"]["sha256"] == hashlib.sha256((tmp_path / item["site"]["path"]).read_bytes()).hexdigest()
    reasons = {item["reason"] for item in report["uncertainties"]}
    assert reasons >= {"remote_schema_reference_not_followed", "generation_freshness_unverified"}


@pytest.mark.parametrize(
    "before,after,affected",
    [
        (1, True, True),
        (True, 1, True),
        (0, False, True),
        (False, 0, True),
        ([1], [True], True),
        ({"nested": [0]}, {"nested": [False]}, True),
        ({"nested": [1]}, {"nested": [1.0]}, False),
        ({"a": True, "b": 1}, {"b": 1, "a": True}, False),
    ],
)
def test_schema_consumers_use_json_boolean_and_number_semantics(project, tmp_path, before, after, affected):
    # declare consumers of the changed and unchanged schema locations
    schema = {"properties": {"value": {"const": before}, "unchanged": {"type": "string"}}}
    (tmp_path / "api.json").write_text(json.dumps(schema))
    for path, reference in (
        ("consumer.json", "api.json#/properties/value"),
        ("root-consumer.json", "api.json"),
        ("unaffected.json", "api.json#/properties/unchanged"),
    ):
        (tmp_path / path).write_text(json.dumps({"$ref": reference}))

    # compare the proposed value through the public change impact report
    schema["properties"]["value"]["const"] = after
    report = json.loads(ChangeImpactAnalyzer(project).analyze(changes=(proposal(tmp_path, "api.json", json.dumps(schema)),)))
    consumers = {finding["target"]["path"] for finding in report["declared_relationships"]}
    assert consumers == ({"consumer.json", "root-consumer.json"} if affected else set())


def test_each_heuristic_preserves_the_correct_changed_source_origin(project, tmp_path):
    (tmp_path / "independent.py").write_text("def zebra():\n    return 7\n")
    (tmp_path / "tests/test_zebra.py").write_text("from independent import zebra\n\ndef test_zebra():\n    assert zebra() == 7\n")
    changes = (proposal(tmp_path), proposal(tmp_path, "independent.py", "def zebra(value):\n    return value\n"))
    report = json.loads(ChangeImpactAnalyzer(project).analyze(changes=changes, max_chars=100000))
    zebra = [finding for finding in report["heuristic_candidates"] if finding["target"]["path"] == "tests/test_zebra.py"]
    assert zebra
    assert any(finding["origin"]["path"] == "independent.py" for finding in zebra)


def test_output_budget_discloses_omitted_findings_and_scopes_report_targets(project, tmp_path):
    for number in range(20):
        (tmp_path / "tests" / f"test_extra_{number}.py").write_text(f"def test_charge_{number}():\n    return payment_api.charge(1)\n")
    raw = ChangeImpactAnalyzer(project).analyze(changes=(proposal(tmp_path),), scope="tests", max_chars=4096)
    report = json.loads(raw)
    assert report["budget"]["used"] == len(raw) <= 4096
    assert report["omitted_findings"] > 0
    assert report["changes"][0]["path"] == "payment_api.py"
    assert all(item["target"]["path"].startswith("tests/") for item in report["heuristic_candidates"])


def test_mcp_accepts_nested_proposed_file_change(project, tmp_path):
    agent = MagicMock()
    agent.get_active_project_or_raise.return_value = project
    tool = McpTool.from_function(AnalyzeChangeTool(agent).apply, name="analyze_change")
    change = proposal(tmp_path)
    raw = asyncio.run(
        tool.run({"changes": [{"path": change.path, "expected_sha256": change.expected_sha256, "new_content": change.new_content}]})
    )
    report = json.loads(raw)
    assert report["changes"][0]["path"] == "payment_api.py"
    assert report["changes"][0]["proposed_sha256"] == hashlib.sha256(change.new_content.encode()).hexdigest()


@pytest.mark.python
@pytest.mark.parametrize("delete", [False, True])
def test_real_pyright_finds_aliased_call_sites_and_indirect_tests_for_changed_or_deleted_api(project, tmp_path, delete):
    project.create_language_server_manager()
    change = proposal(tmp_path, new_content=None) if delete else proposal(tmp_path)
    report = json.loads(ChangeImpactAnalyzer(project).analyze(changes=(change,), max_chars=100000))
    relationships = report["language_server_relationships"]
    clients = [finding for finding in relationships if finding["target"]["path"] == "client.py" and finding["target"]["symbol"] == "caller"]
    assert len(clients) == 2
    assert len({finding["site_column"] for finding in clients}) == 2
    assert {finding["site"]["start_line"] for finding in clients} == {4}
    assert all(finding["target"]["path"] != "unrelated.py" for finding in relationships)
    tests = [test for test in report["recommended_tests"] if test["path"] == "tests/test_flow.py"]
    assert any(test["evidence"] == "language_server" and test["depth"] == 2 for test in tests)
    assert all(test["evidence"] == "heuristic" for test in report["recommended_tests"] if test["path"] == "tests/test_dynamic.py")
    assert (tmp_path / "payment_api.py").read_text() == "def charge(amount: int) -> int:\n    return amount\n"


@pytest.mark.typescript
def test_real_typescript_interface_change_finds_implementation_callers_and_tests(tmp_path):
    executable = os.environ.get("SELENE_TEST_TYPESCRIPT_LS")
    if executable is None or not Path(executable).is_file():
        pytest.skip("Provide a pre-provisioned TypeScript language server through SELENE_TEST_TYPESCRIPT_LS")
    (tmp_path / "tests").mkdir()
    sources = {
        "gateway.ts": "export interface PaymentGateway {\n    authorize(amount: number): boolean;\n}\n",
        "real.ts": "import { PaymentGateway } from './gateway';\nexport class RealGateway implements PaymentGateway {\n    authorize(amount: number): boolean { return amount < 100; }\n}\n",
        "client.ts": "import { PaymentGateway } from './gateway';\nexport function checkout(gateway: PaymentGateway): boolean {\n    return gateway.authorize(50);\n}\n",
        "other.ts": "export class Other {\n    authorize(amount: number): boolean { return false; }\n}\nexport function unused(): boolean { return new Other().authorize(10); }\n",
        "tests/checkout.test.ts": "import { checkout } from '../client';\nimport { RealGateway } from '../real';\nexport function test_checkout(): boolean { return checkout(new RealGateway()); }\n",
        "tsconfig.json": json.dumps(
            {"compilerOptions": {"strict": True, "target": "ES2020", "module": "commonjs"}, "include": ["**/*.ts"]}
        ),
    }
    for path, content in sources.items():
        (tmp_path / path).write_text(content)
    configuration = SeleneConfig(ls_specific_settings={"typescript": {"ls_path": executable}}).with_headless_mode_overrides()
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="interface-impact", language_servers=[LanguageServerId.TYPESCRIPT]),
        selene_config=configuration,
    )
    try:
        project.create_language_server_manager()
        change = proposal(tmp_path, "gateway.ts", sources["gateway.ts"].replace("amount: number", "amount: number, approval: string"))
        report = json.loads(ChangeImpactAnalyzer(project).analyze(changes=(change,), max_chars=100000))
        relationships = report["language_server_relationships"]
        assert any(
            finding["target"]["path"] == "real.ts" and finding["relationship"] == "implementation_of_symbol" for finding in relationships
        )
        assert any(finding["target"]["path"] == "client.ts" for finding in relationships)
        assert all(finding["target"]["path"] != "other.ts" for finding in relationships)
        assert any(
            test["path"] == "tests/checkout.test.ts" and test["evidence"] == "language_server" for test in report["recommended_tests"]
        )
        assert (tmp_path / "gateway.ts").read_text() == sources["gateway.ts"]
    finally:
        project.shutdown()
