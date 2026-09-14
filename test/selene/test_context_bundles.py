import asyncio
import hashlib
import json
import os
from concurrent.futures import CancelledError
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.tools.base import Tool as McpTool

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.context.bundles import ContextBundleService
from selene.context.model import ContextAnchor, ContextCandidate, ContextEvidence, SourceReference, StaleContextError
from selene.context.selection import ContextCandidatePool
from selene.context.semantic import IdentifierPositions
from selene.context.sources import ContextDocument
from selene.indexing.scope import SourceRootReplaced, SourceScopeError
from selene.project import Project
from selene.tools import FindContextTool
from selene.util.cancellation import CancellationToken
from solidlsp.ls_config import LanguageServerId


def write_sources(root: Path) -> None:
    sources = {
        "checkout.py": "def checkout(payment):\n    return payment.capture()\n",
        "tests/test_checkout.py": "def test_checkout():\n    assert checkout('payment')\n",
        "docs/checkout.md": "# Checkout\nPayment capture requires approval.\n",
        "settings.toml": "payment_capture = 'approval'\n",
    }
    for path, content in sources.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


@pytest.fixture
def project(tmp_path, request):
    write_sources(tmp_path)
    root = tmp_path
    if getattr(request, "param", False):
        root = tmp_path.with_name(tmp_path.name + "-alias")
        root.symlink_to(tmp_path, target_is_directory=True)
    project = Project(
        project_root=str(root),
        project_config=ProjectConfig(project_name="context", language_servers=[LanguageServerId.PYTHON]),
        selene_config=SeleneConfig().with_headless_mode_overrides(),
    )
    yield project
    project.shutdown()


def assert_page(raw: str, root: Path, budget: int) -> dict:
    page = json.loads(raw)
    assert len(raw) <= budget
    assert page["budget"] == {"unit": "json_characters", "limit": budget, "used": len(raw)}
    for item in page["items"]:
        source = item["source"]
        data = (root / source["path"]).read_bytes()
        assert source["sha256"] == hashlib.sha256(data).hexdigest()
        assert 1 <= source["start_line"] <= source["end_line"]
        if item["shown_end_line"] is not None:
            lines = data.decode().replace("\r\n", "\n").replace("\r", "\n").split("\n")
            assert item["content"] == "\n".join(lines[source["start_line"] - 1 : item["shown_end_line"]])
    return page


def test_lexical_context_has_versioned_code_tests_docs_and_configuration(project, tmp_path):
    raw = project.get_context_service().find("checkout payment")
    page = assert_page(raw, tmp_path, 20000)
    roles = {role for item in page["items"] for role in item["roles"]}
    assert roles >= {"code", "test", "documentation", "configuration"}
    assert "semantic_backend_unavailable" in page["limitations"]
    assert {evidence["strength"] for item in page["items"] for evidence in item["evidence"]} <= {"lexical", "heuristic"}
    assert all(item["body_status"] == "complete" for item in page["items"])


def test_pages_obey_exact_budget_and_replay_without_duplicates(project, tmp_path):
    for number in range(10):
        (tmp_path / f"checkout_{number}.py").write_text("value = 'checkout — \\\" 😀'\n" * 30)
    service = project.get_context_service()
    page = assert_page(service.find("checkout", max_chars=2400), tmp_path, 2400)
    seen = set()
    while True:
        for item in page["items"]:
            assert item["id"] not in seen
            seen.add(item["id"])
        continuation = page["continuation"]
        if continuation is None:
            break
        raw = service.continue_bundle(continuation, max_chars=2400)
        replay = json.loads(service.continue_bundle(continuation, max_chars=2400))
        page = assert_page(raw, tmp_path, 2400)
        assert replay["items"] == page["items"]
    assert len(seen) == page["available_items"]


def test_selected_body_read_reuses_source_versions(project, tmp_path):
    service = project.get_context_service()
    page = json.loads(service.find("checkout", (ContextAnchor("checkout.py"),), include_bodies=False))
    anchor = page["items"][0]
    assert anchor["body_status"] == "omitted"
    selected = assert_page(service.read_items(page["bundle_id"], (anchor["id"],)), tmp_path, 20000)
    assert selected["items"][0]["source"] == anchor["source"]
    assert "def checkout(payment)" in selected["items"][0]["content"]


@pytest.mark.parametrize("change", ["preserved_mtime", "ignore", "alias", "delete"])
def test_changed_sources_reject_continuations_and_selected_reads(project, tmp_path, change):
    for number in range(6):
        (tmp_path / f"checkout_{number}.py").write_text("checkout = 'payment'\n")
    service = project.get_context_service()
    page = json.loads(service.find("checkout", max_chars=2300))
    assert page["continuation"]
    source = tmp_path / "checkout.py"
    if change == "preserved_mtime":
        stamp = source.stat()
        source.write_text(source.read_text().replace("capture", "refund_"))
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == "ignore":
        (tmp_path / ".gitignore").write_text("checkout.py\n")
    elif change == "alias":
        external = tmp_path.parent / (tmp_path.name + "-external.py")
        external.write_text(source.read_text())
        source.unlink()
        source.symlink_to(external)
    else:
        source.unlink()
    with pytest.raises(StaleContextError):
        service.continue_bundle(page["continuation"])
    with pytest.raises(StaleContextError):
        service.read_items(page["bundle_id"], (page["items"][0]["id"],))


@pytest.mark.typescript
def test_real_typescript_context_connects_injected_interface_and_tests_with_fresh_versions(tmp_path):
    executable = os.environ.get("SELENE_TEST_TYPESCRIPT_LS")
    if executable is None or not Path(executable).is_file():
        pytest.skip("Provide a pre-provisioned TypeScript language server through SELENE_TEST_TYPESCRIPT_LS")
    sources = {
        "client.ts": "import { PaymentGateway } from './gateway';\nexport function checkout(gateway: PaymentGateway): boolean {\n    const marker = '💳'; return gateway.authorize(50);\n}\n",
        "gateway.ts": "export interface PaymentGateway {\n    authorize(amount: number): boolean;\n}\n",
        "real.ts": "import { PaymentGateway } from './gateway';\nexport class RealGateway implements PaymentGateway {\n    authorize(amount: number): boolean { return amount < 100; }\n}\n",
        "tests/checkout.test.ts": "import { checkout } from '../client';\nimport { RealGateway } from '../real';\nexport function test_checkout(): boolean { return checkout(new RealGateway()); }\n",
        "other.ts": "export function authorize(): boolean { return false; }\n",
        "docs/approval.md": "# Approval\nCheckout payment authorization uses an injected gateway.\n",
        "settings.json": '{"payment_limit": 100}\n',
        "tsconfig.json": json.dumps({"compilerOptions": {"strict": True, "target": "ES2020", "module": "commonjs"}}),
    }
    for path, content in sources.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    configuration = SeleneConfig(ls_specific_settings={"typescript": {"ls_path": executable}}).with_headless_mode_overrides()
    project = Project(
        project_root=str(tmp_path),
        project_config=ProjectConfig(project_name="interface-context", language_servers=[LanguageServerId.TYPESCRIPT]),
        selene_config=configuration,
    )
    try:
        project.create_language_server_manager()
        service = project.get_context_service()
        page = assert_page(service.find("checkout payment", (ContextAnchor("client.ts", "checkout"),), max_chars=20000), tmp_path, 20000)
        semantic = [item for item in page["items"] if any(edge["strength"] == "language_server" for edge in item["evidence"])]
        assert {item["source"]["path"] for item in semantic} >= {"gateway.ts", "tests/checkout.test.ts"}
        assert all(item["source"]["path"] != "other.ts" for item in semantic)
        assert {item["source"]["path"] for item in page["items"]} >= {"docs/approval.md", "settings.json"}
        explicit = assert_page(
            service.find("payment interface", (ContextAnchor("gateway.ts", "PaymentGateway"),), max_chars=20000), tmp_path, 20000
        )
        assert any(
            item["source"]["path"] == "gateway.ts" and "export interface PaymentGateway" in (item["content"] or "")
            for item in explicit["items"]
        )
        gateway = tmp_path / "gateway.ts"
        stamp = gateway.stat()
        gateway.write_text(sources["gateway.ts"].replace("number", "string"))
        os.utime(gateway, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with pytest.raises(StaleContextError):
            service.read_items(page["bundle_id"], (page["items"][0]["id"],))
    finally:
        project.shutdown()


def test_scope_excludes_private_and_external_aliases(project, tmp_path):
    external = tmp_path.parent / (tmp_path.name + "-secret.py")
    external.write_text("checkout_private_canary = True\n")
    (tmp_path / "external.py").symlink_to(external)
    (tmp_path / "private.py").write_text("checkout_private_canary = True\n")
    (tmp_path / "public_alias.py").symlink_to(tmp_path / "private.py")
    (tmp_path / ".gitignore").write_text("private.py\n")
    service = project.get_context_service()
    page = json.loads(service.find("checkout", scope="docs"))
    assert {item["source"]["path"] for item in page["items"]} == {"docs/checkout.md"}
    with pytest.raises(SourceScopeError):
        service.find("checkout", (ContextAnchor("../secret.py"),))
    with pytest.raises(ValueError):
        service.find("checkout", (ContextAnchor("external.py"),))
    with pytest.raises(ValueError):
        service.find("checkout", (ContextAnchor("public_alias.py"),))


def test_expired_evicted_and_other_project_handles_are_rejected(project, monkeypatch):
    service = ContextBundleService(project, max_plans=1, ttl_seconds=10)
    first = json.loads(service.find("checkout"))
    other = ContextBundleService(project)
    with pytest.raises(ValueError, match="Unknown or expired"):
        other.read_items(first["bundle_id"], ("0",))
    second = json.loads(service.find("payment"))
    with pytest.raises(ValueError, match="Unknown or expired"):
        service.read_items(first["bundle_id"], ("0",))
    import time

    later = time.monotonic() + 11
    monkeypatch.setattr("selene.context.bundles.time.monotonic", lambda: later)
    with pytest.raises(ValueError, match="Unknown or expired"):
        service.read_items(second["bundle_id"], ("0",))


def test_root_replacement_and_cancellation_fail_without_reusing_a_selection(project, tmp_path):
    service = project.get_context_service()
    page = json.loads(service.find("checkout"))
    token = CancellationToken()
    token.cancel()
    with token.bind(), pytest.raises(CancelledError):
        service.find("checkout")
    moved = tmp_path.with_name(tmp_path.name + "-moved")
    tmp_path.rename(moved)
    tmp_path.mkdir()
    write_sources(tmp_path)
    with pytest.raises(SourceRootReplaced):
        service.read_items(page["bundle_id"], ("0",))


def test_mcp_schema_accepts_nested_anchor_and_returns_versioned_json(project, tmp_path):
    agent = MagicMock()
    agent.get_active_project_or_raise.return_value = project
    tool = McpTool.from_function(FindContextTool(agent).apply, name="find_context")
    raw = asyncio.run(tool.run({"anchors": [{"path": "checkout.py", "symbol": "checkout"}], "max_chars": 5000}))
    page = assert_page(raw, tmp_path, 5000)
    assert page["items"][0]["source"]["path"] == "checkout.py"
    assert "anchor" in page["items"][0]["roles"]


def test_overlapping_candidate_ranges_merge_across_multiple_matches():
    pool = ContextCandidatePool()
    for start, end in ((10, 15), (20, 25), (30, 35), (14, 31)):
        pool.add(
            ContextCandidate(
                SourceReference("code.py", "hash", start, end), "code.py", ("code",), (ContextEvidence("match", "lexical"),), 50
            )
        )
    items = pool.ordered()
    assert len(items) == 1
    assert (items[0].reference.start_line, items[0].reference.end_line) == (10, 35)


def test_identifier_positions_ignore_python_strings_and_use_utf16_columns():
    lines = ("def checkout():", "    marker = '😀'; capturePayment() # ignoredComment()", "    return 'fakeCall()'")
    document = ContextDocument("checkout.py", "checkout.py", "hash", lines)
    positions = IdentifierPositions.collect(document, document.reference())
    call = next(position for position in positions if position.name == "capturePayment")
    assert call.line == 1
    assert call.column == len(lines[1].split("capturePayment")[0].encode("utf-16-le")) // 2
    assert {position.name for position in positions} == {"checkout", "marker", "capturePayment"}


@pytest.mark.python
@pytest.mark.parametrize("project", [False, True], indirect=True)
def test_real_pyright_links_aliased_policy_types_and_tests_with_current_evidence(project, tmp_path):
    sources = {
        "checkout.py": "from policy import authorize as check_policy\nfrom models import Payment\n\ndef checkout(payment: Payment) -> bool:\n    return check_policy(payment)\n",
        "policy.py": "from models import Payment\n\ndef authorize(payment: Payment) -> bool:\n    return payment.amount < 100\n",
        "models.py": "from dataclasses import dataclass\n\n@dataclass\nclass Payment:\n    amount: int\n",
        "tests/test_checkout.py": "from checkout import checkout\nfrom models import Payment\n\ndef test_checkout():\n    assert checkout(Payment(50))\n",
        "unrelated.py": "def authorize(irrelevant):\n    return 'different policy'\n",
    }
    for path, content in sources.items():
        (tmp_path / path).write_text(content)
    project.create_language_server_manager()
    service = project.get_context_service()
    page = assert_page(service.find("checkout payment", (ContextAnchor("checkout.py", "checkout"),), max_chars=20000), tmp_path, 20000)
    semantic = [item for item in page["items"] if any(evidence["strength"] == "language_server" for evidence in item["evidence"])]
    assert {item["source"]["path"] for item in semantic} >= {"policy.py", "models.py", "tests/test_checkout.py"}
    assert all(item["source"]["path"] != "unrelated.py" for item in semantic)
    assert any("type" in item["roles"] and item["source"]["path"] == "models.py" for item in semantic)
    assert page["semantic_operations"] <= 40
    for item in semantic:
        for evidence in item["evidence"]:
            if evidence["strength"] == "language_server":
                assert evidence["origin"] is not None
                assert evidence["site"] is not None

    # add a previously unknown caller and require a fresh semantic relationship immediately
    (tmp_path / "tests/test_new.py").write_text(
        "from checkout import checkout\nfrom models import Payment\n\ndef test_new():\n    assert checkout(Payment(40))\n"
    )
    updated = assert_page(service.find("checkout payment", (ContextAnchor("checkout.py", "checkout"),)), tmp_path, 20000)
    assert any(
        item["source"]["path"] == "tests/test_new.py" and any(evidence["kind"] == "reference_to_symbol" for evidence in item["evidence"])
        for item in updated["items"]
    )
    with pytest.raises(StaleContextError):
        service.read_items(page["bundle_id"], (page["items"][0]["id"],))
