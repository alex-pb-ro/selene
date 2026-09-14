"""Compare bounded local retrieval workflows on synthetic Python and TypeScript projects."""

import argparse
import hashlib
import json
import platform
import random
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.context.bundles import ContextPageRenderer, ContextPlan
from selene.context.model import ContextAnchor, ContextCandidate, ContextEvidence
from selene.context.sources import ContextFileRoles, ContextSources
from selene.project import Project
from selene.symbol import LanguageServerSymbol, LanguageServerSymbolRetriever
from solidlsp.ls_config import LanguageServerId


@dataclass(frozen=True)
class ExpectedSymbol:
    path: str
    name: str
    first: int
    last: int


@dataclass(frozen=True)
class Fixture:
    name: str
    language: LanguageServerId
    anchor: ContextAnchor
    sources: dict[str, str]
    symbols: tuple[ExpectedSymbol, ...]
    relevant_paths: tuple[str, ...]
    query: str = "checkout payment"

    @classmethod
    def cases(cls) -> tuple["Fixture", ...]:
        python = {
            "checkout.py": "from policy import authorize as check_policy\nfrom models import Payment\n\ndef checkout(payment: Payment) -> bool:\n    return check_policy(payment)\n",
            "policy.py": "from models import Payment\n\ndef authorize(payment: Payment) -> bool:\n    return payment.amount < 100\n",
            "models.py": "from dataclasses import dataclass\n\n@dataclass\nclass Payment:\n    amount: int\n",
            "tests/test_checkout.py": "from checkout import checkout\nfrom models import Payment\n\ndef test_checkout():\n    assert checkout(Payment(50))\n",
            "docs/approval.md": "# Approval\nA payment must be approved before checkout.\n",
            "settings.toml": "payment_limit = 100\n",
            "unrelated.py": "def authorize(value):\n    return value\n",
        }
        typescript = {
            "client.ts": "import { PaymentGateway } from './gateway';\nexport function checkout(gateway: PaymentGateway): boolean {\n    return gateway.authorize(50);\n}\n",
            "gateway.ts": "export interface PaymentGateway {\n    authorize(amount: number): boolean;\n}\n",
            "real.ts": "import { PaymentGateway } from './gateway';\nexport class RealGateway implements PaymentGateway {\n    authorize(amount: number): boolean { return amount < 100; }\n}\n",
            "tests/checkout.test.ts": "import { checkout } from '../client';\nimport { RealGateway } from '../real';\nexport function test_checkout(): boolean { return checkout(new RealGateway()); }\n",
            "docs/approval.md": "# Approval\nCheckout payment authorization uses an injected gateway.\n",
            "settings.json": '{"payment_limit": 100}\n',
            "other.ts": "export class Other {\n    authorize(amount: number): boolean { return false; }\n}\n",
            "tsconfig.json": json.dumps(
                {"compilerOptions": {"strict": True, "target": "ES2020", "module": "commonjs"}, "include": ["**/*.ts"]}
            ),
        }
        return (
            cls(
                "python_import_alias",
                LanguageServerId.PYTHON,
                ContextAnchor("checkout.py", "checkout"),
                python,
                (
                    ExpectedSymbol("checkout.py", "checkout", 4, 5),
                    ExpectedSymbol("policy.py", "authorize", 3, 4),
                    ExpectedSymbol("models.py", "Payment", 4, 5),
                    ExpectedSymbol("tests/test_checkout.py", "test_checkout", 4, 5),
                ),
                tuple(path for path in python if path != "unrelated.py"),
            ),
            cls(
                "typescript_injected_interface",
                LanguageServerId.TYPESCRIPT,
                ContextAnchor("client.ts", "checkout"),
                typescript,
                (
                    ExpectedSymbol("client.ts", "checkout", 2, 4),
                    ExpectedSymbol("gateway.ts", "PaymentGateway", 1, 3),
                    ExpectedSymbol("real.ts", "RealGateway", 2, 4),
                    ExpectedSymbol("tests/checkout.test.ts", "test_checkout", 3, 3),
                ),
                tuple(path for path in typescript if path not in {"other.ts", "tsconfig.json"}),
            ),
        )

    def write(self, root: Path) -> None:
        for name, content in self.sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        extension = ".py" if self.language == LanguageServerId.PYTHON else ".ts"
        for number in range(32):
            body = (
                f"# Checkout payment example; unrelated to approval.\ndef checkoutPaymentExample{number}():\n    return 'example'\n"
                if extension == ".py"
                else f"// Checkout payment example; unrelated to approval.\nexport function checkoutPaymentExample{number}(): string {{ return 'example'; }}\n"
            )
            (root / f"noise_{number:02}{extension}").write_text(body)


class BaselineWorkflow:
    """Adapt predefined existing retrieval operations to one common output envelope."""

    def __init__(self, project: Project, fixture: Fixture, budget: int):
        self._project = project
        self._fixture = fixture
        self._budget = budget
        index = project.get_local_index()
        self._sources = ContextSources(index, index.refresh(), project.project_config.encoding, max_files=64)
        self._candidates: list[ContextCandidate] = []
        self._logical_operations = 0

    def _add(self, path: str, first: int = 1, last: int | None = None, symbol: str = "", *, method: str, priority: int = 20) -> None:
        if not self._sources.contains(path):
            return
        document = self._sources.read(path)
        reference = document.reference(first, last, symbol)
        strength = "language_server" if method in {"existing_symbols", "repository_map"} and symbol else "lexical"
        candidate = ContextCandidate(
            reference, document.canonical_path, (ContextFileRoles.classify(path),), (ContextEvidence(method, strength),), priority
        )
        remaining = []
        for existing in self._candidates:
            left, right = existing.reference, candidate.reference
            if existing.canonical_path == candidate.canonical_path and max(left.start_line, right.start_line) <= min(
                left.end_line, right.end_line
            ):
                candidate = replace(
                    candidate,
                    reference=replace(
                        reference,
                        start_line=min(left.start_line, right.start_line),
                        end_line=max(left.end_line, right.end_line),
                        symbol=left.symbol if left.symbol == right.symbol else "",
                    ),
                    priority=min(existing.priority, candidate.priority),
                )
            else:
                remaining.append(existing)
        self._candidates = remaining + [candidate]

    def _symbol(self, symbol: LanguageServerSymbol, method: str) -> None:
        path, first, last = symbol.relative_path, symbol.body_start_position, symbol.body_end_position
        if path is not None and first is not None and last is not None:
            self._add(
                path,
                first["line"] + 1,
                max(first["line"] + 1, last["line"] + int(last["character"] > 0)),
                symbol.get_name_path(),
                method=method,
                priority=0 if path == self._fixture.anchor.path else 20,
            )

    def _grep(self) -> None:
        paths = sorted(self._sources.observation.files)
        command = ["rg", "--json", "--sort", "path", "-i"]
        for word in self._fixture.query.split():
            command.extend(("-e", re.escape(word)))
        result = subprocess.run([*command, "--", *paths], cwd=self._project.project_root, capture_output=True, text=True, check=False)
        if result.returncode not in {0, 1}:
            raise RuntimeError(result.stderr)
        for line in result.stdout.splitlines():
            match = json.loads(line)
            if match["type"] != "match":
                continue
            path = match["data"]["path"]["text"]
            number = match["data"]["line_number"]
            document = self._sources.read(path)
            self._add(path, max(1, number - 3), min(len(document.lines), number + 3), method="grep")
        self._logical_operations = 1

    def _symbols(self) -> None:
        retriever = LanguageServerSymbolRetriever(self._project)
        anchor = self._fixture.anchor
        for symbol in retriever.find(anchor.symbol, within_relative_path=anchor.path):
            self._symbol(symbol, "existing_symbols")
        for reference in retriever.find_referencing_symbols(anchor.symbol, relative_file_path=anchor.path):
            self._symbol(reference.symbol, "existing_symbols")
        self._logical_operations = 2

    def _map(self) -> None:
        retriever = LanguageServerSymbolRetriever(self._project)
        for path in sorted(self._sources.observation.files):
            if retriever.can_analyze_file(path):
                server = retriever.get_language_server(path)
                symbols = server.request_document_symbols(path)
                self._logical_operations += 1
                for symbol in symbols.get_all_symbols_and_roots()[0]:
                    self._symbol(LanguageServerSymbol(symbol), "repository_map")
            else:
                self._add(path, method="repository_map")

    def run(self, method: str) -> str:
        self._add(self._fixture.anchor.path, method=method, priority=0)
        if method == "grep":
            self._grep()
        elif method == "existing_symbols":
            self._symbols()
        elif method == "repository_map":
            self._map()
        elif method == "anchored_lexical":
            matches = self._project.get_local_index().search(self._fixture.query, limit=50)
            self._logical_operations = 1
            for position, match in enumerate(matches.matches):
                self._add(match.path, method=method, priority=position + 1)
        else:
            raise ValueError(method)
        candidates = tuple(sorted(self._candidates, key=lambda item: (item.priority, item.reference.path, item.reference.start_line)))
        plan = ContextPlan(
            "baseline-" + method,
            time.monotonic(),
            self._sources.observation.status.generation,
            candidates,
            self._sources.versions(),
            ("predefined_nonadaptive_baseline",),
            self._logical_operations,
        )
        raw = ContextPageRenderer.render(plan, self._sources, offset=0, max_chars=self._budget, include_bodies=method != "repository_map")
        self._sources.validate()
        return raw


class ContextAcceptance:
    _METHODS = ("grep", "existing_symbols", "repository_map", "anchored_lexical", "context_bundle")

    def __init__(self, typescript_server: Path, budget: int, rounds: int):
        self._typescript_server = typescript_server.resolve(strict=True)
        self._budget = budget
        self._rounds = rounds

    def _metrics(self, raw: str, fixture: Fixture) -> dict:
        page = json.loads(raw)
        assert page["budget"]["used"] == len(raw) <= self._budget
        items = page["items"]
        located, supplied = [], []
        for expected in fixture.symbols:
            digest = hashlib.sha256(fixture.sources[expected.path].encode()).hexdigest()
            matches = [
                item
                for item in items
                if item["source"]["path"] == expected.path
                and item["source"]["sha256"] == digest
                and item["source"]["start_line"] <= expected.first
                and item["source"]["end_line"] >= expected.last
            ]
            name = expected.path + ":" + expected.name
            if matches:
                located.append(name)
            if any(item["content"] is not None and (item["shown_end_line"] or 0) >= expected.last for item in matches):
                supplied.append(name)
        overlaps = 0
        for index, item in enumerate(items):
            for previous in items[:index]:
                a, b = item["source"], previous["source"]
                overlaps += int(
                    item["canonical_path"] == previous["canonical_path"]
                    and max(a["start_line"], b["start_line"]) <= min(a["end_line"], b["end_line"])
                )
        paths = {item["source"]["path"] for item in items}
        return {
            "json_characters": len(raw),
            "located_symbols": located,
            "complete_symbol_bodies": supplied,
            "expected_symbol_count": len(fixture.symbols),
            "symbol_location_recall": len(located) / len(fixture.symbols),
            "symbol_body_recall": len(supplied) / len(fixture.symbols),
            "relevant_files_returned": sorted(paths & set(fixture.relevant_paths)),
            "relevant_file_recall": len(paths & set(fixture.relevant_paths)) / len(fixture.relevant_paths),
            "returned_paths": sorted(paths),
            "overlapping_range_pairs": overlaps,
            "has_continuation": page["continuation"] is not None,
            "limitations": page["limitations"],
            "logical_operations": page["semantic_operations"],
        }

    def run(self) -> dict:
        observations = []
        randomizer = random.Random(20260914)
        for fixture in Fixture.cases():
            for round_number in range(self._rounds):
                methods = list(self._METHODS)
                randomizer.shuffle(methods)
                for method in methods:
                    with tempfile.TemporaryDirectory(prefix="selene-context-acceptance-") as temporary:
                        root = Path(temporary)
                        fixture.write(root)
                        started = time.perf_counter()
                        configuration = SeleneConfig(
                            ls_specific_settings={"typescript": {"ls_path": str(self._typescript_server)}}
                        ).with_headless_mode_overrides()
                        project = Project(
                            project_root=str(root),
                            project_config=ProjectConfig(project_name="synthetic-context", language_servers=[fixture.language]),
                            selene_config=configuration,
                        )
                        try:
                            if method in {"context_bundle", "existing_symbols", "repository_map"}:
                                project.create_language_server_manager()
                            project.get_local_index().refresh()
                            startup = time.perf_counter() - started
                            for phase in ("first_request", "warm_repeat"):
                                start = time.perf_counter()
                                raw = (
                                    project.get_context_service().find(fixture.query, (fixture.anchor,), max_chars=self._budget)
                                    if method == "context_bundle"
                                    else BaselineWorkflow(project, fixture, self._budget).run(method)
                                )
                                elapsed = time.perf_counter() - start
                                observations.append(
                                    {
                                        "fixture": fixture.name,
                                        "round": round_number,
                                        "method": method,
                                        "phase": phase,
                                        "startup_ms": round(startup * 1000, 3),
                                        "request_ms": round(elapsed * 1000, 3),
                                        "first_result_from_project_start_ms": round((startup + elapsed) * 1000, 3)
                                        if phase == "first_request"
                                        else None,
                                        **self._metrics(raw, fixture),
                                    }
                                )
                                print(
                                    f"{fixture.name} {round_number} {method} {phase}: {observations[-1]['symbol_location_recall']} recall",
                                    flush=True,
                                )
                        except Exception as error:
                            observations.append(
                                {
                                    "fixture": fixture.name,
                                    "round": round_number,
                                    "method": method,
                                    "error": type(error).__name__ + ": " + str(error),
                                }
                            )
                        finally:
                            project.shutdown()
        repo = Path(__file__).resolve().parents[2]
        sources = [
            *sorted((repo / "src/selene/context").glob("*.py")),
            *sorted((repo / "src/selene/indexing").glob("*.py")),
            repo / "src/selene/project.py",
            repo / "src/selene/symbol.py",
            repo / "src/solidlsp/ls.py",
            Path(__file__),
        ]
        return {
            "method": {
                "synthetic_only": True,
                "model_calls": 0,
                "budget_json_characters": self._budget,
                "rounds": self._rounds,
                "ordering": "seeded shuffle; separate fresh project/backend per method and round; same-process warm repeat",
                "envelope": "same ContextPageRenderer for all methods; map supplies locations without bodies; all other methods may supply bodies",
                "grep": "anchor then case-insensitive query-word rg matches with three context lines, merged overlapping ranges",
                "existing_symbols": "find the explicit anchor and its direct referencing symbols using the existing retriever; no adaptive follow-up",
                "repository_map": "anchor then all admitted document symbols and non-code file locations, deterministic path order; no bodies",
                "anchored_lexical": "anchor then up to 50 ranked local-index matches (the public search limit); no twelve-match cutoff",
                "limits": "Two authored fixtures, four labelled symbols and 32 distractors each; this is not an optimized human/agent workflow or a paired task-success test. JSON characters are not provider tokens. Page return is the measured first-result boundary; no streaming time is claimed. Filesystem/dependency caches are not flushed.",
                "platform": platform.platform(),
                "typescript_server": self._typescript_server.name,
                "source_sha256": {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
            },
            "fixtures": [
                {
                    "name": fixture.name,
                    "query": fixture.query,
                    "anchor": asdict(fixture.anchor),
                    "expected_symbols": [asdict(symbol) for symbol in fixture.symbols],
                    "relevant_paths": fixture.relevant_paths,
                    "source_sha256": {path: hashlib.sha256(content.encode()).hexdigest() for path, content in fixture.sources.items()},
                }
                for fixture in Fixture.cases()
            ],
            "observations": observations,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--typescript-server", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=15000)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = ContextAcceptance(arguments.typescript_server, arguments.budget, arguments.rounds).run()
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    if any("error" in observation for observation in result["observations"]):
        raise SystemExit("At least one workflow failed; retained in the result artifact")
