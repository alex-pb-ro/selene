"""Controller-owned synthetic tasks, independent checks and reference repairs.

Only ``TaskSpec.visible_files`` and ``TaskSpec.prompt`` belong in an agent workspace.
The remaining fields must stay outside the agent's filesystem boundary.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str


@dataclass(frozen=True)
class TaskSpec:
    identifier: str
    language: Literal["python", "typescript"]
    prompt: str
    visible_files: tuple[SourceFile, ...]
    editable_prefixes: tuple[str, ...]
    protected_paths: tuple[str, ...]
    check_source: str
    expected_checks: tuple[str, ...]
    reference_repair: tuple[SourceFile, ...]
    regression_mutant: SourceFile


class TaskCatalog:
    @classmethod
    def all(cls) -> tuple[TaskSpec, ...]:
        return cls._boundary(), cls._currency(), cls._interface()

    @classmethod
    def get(cls, identifier: str) -> TaskSpec:
        return next(task for task in cls.all() if task.identifier == identifier)

    @staticmethod
    def _boundary() -> TaskSpec:
        return TaskSpec(
            "python_authorization_boundary",
            "python",
            "A checkout for an active account is rejected when its amount equals the configured limit. "
            "Repair the authorization boundary according to docs/authorization.md. Follow the checkout call path, "
            "preserve suspended-account behavior and the unrelated shipping configuration, and add a regression test. "
            "The limit remains configurable; do not hardcode the examples. You may use any available local tools. "
            "Run the relevant tests and describe the change.",
            (
                SourceFile("shop/__init__.py", ""),
                SourceFile(
                    "shop/models.py", "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Account:\n    active: bool\n"
                ),
                SourceFile("shop/settings.py", "PAYMENT_LIMIT = 100\n"),
                SourceFile(
                    "shop/policy.py",
                    "from shop.models import Account\n\ndef authorize(account: Account, amount: int, limit: int) -> bool:\n    return account.active and 0 <= amount < limit\n",
                ),
                SourceFile(
                    "shop/checkout.py",
                    "from shop import settings\nfrom shop.models import Account\nfrom shop.policy import authorize as check_policy\n\ndef checkout(account: Account, amount: int) -> bool:\n    return check_policy(account, amount, settings.PAYMENT_LIMIT)\n",
                ),
                SourceFile("shop/examples.py", "def checkout_payment_example(amount):\n    return 'demonstration only'\n"),
                SourceFile(
                    "docs/authorization.md",
                    "# Checkout authorization\nActive accounts may use nonnegative integer amounts up to and including PAYMENT_LIMIT. Suspended accounts and negative amounts are rejected. The configured limit is read for each checkout.\n",
                ),
                SourceFile("shipping/config.txt", "zone = domestic\ncarrier = unchanged\n"),
                SourceFile(
                    "tests/test_smoke.py",
                    "from shop.checkout import checkout\nfrom shop.models import Account\n\ndef test_small_checkout():\n    assert checkout(Account(True), 5)\n",
                ),
            ),
            ("shop/", "tests/"),
            ("shipping/config.txt", "shop/examples.py"),
            """from shop import settings
from shop.checkout import checkout
from shop.models import Account
from shop.policy import authorize

def test_inclusive_boundaries():
    for limit in (0, 1, 37, 100, 217):
        assert authorize(Account(True), limit, limit) is True
        assert authorize(Account(True), limit + 1, limit) is False

def test_negative_and_suspended():
    for amount in (-100, -1, 0, 5, 100):
        assert authorize(Account(False), amount, 100) is False
    assert authorize(Account(True), -1, 100) is False

def test_configuration_is_observed_per_checkout():
    previous = settings.PAYMENT_LIMIT
    try:
        for limit in (7, 31, 200):
            settings.PAYMENT_LIMIT = limit
            assert checkout(Account(True), limit) is True
            assert checkout(Account(True), limit + 1) is False
    finally:
        settings.PAYMENT_LIMIT = previous

def test_lower_amounts_still_work():
    for amount in (0, 1, 5, 99):
        assert authorize(Account(True), amount, 100) is True
""",
            (
                "test_inclusive_boundaries",
                "test_negative_and_suspended",
                "test_configuration_is_observed_per_checkout",
                "test_lower_amounts_still_work",
            ),
            (
                SourceFile(
                    "shop/policy.py",
                    "from shop.models import Account\n\ndef authorize(account: Account, amount: int, limit: int) -> bool:\n    return account.active and 0 <= amount <= limit\n",
                ),
                SourceFile(
                    "tests/test_boundary.py",
                    "from shop.models import Account\nfrom shop.policy import authorize\n\ndef test_inclusive_configurable_limit():\n    for limit in (0, 7, 100):\n        assert authorize(Account(True), limit, limit)\n        assert not authorize(Account(True), limit + 1, limit)\n        assert not authorize(Account(False), limit, limit)\n",
                ),
            ),
            SourceFile(
                "shop/policy.py",
                "from shop.models import Account\n\ndef authorize(account: Account, amount: int, limit: int) -> bool:\n    return account.active and 0 <= amount <= 100\n",
            ),
        )

    @staticmethod
    def _currency() -> TaskSpec:
        return TaskSpec(
            "python_required_currency_migration",
            "python",
            "Migrate billing.money.render_amount to render_amount(amount_minor, *, currency), with currency required. "
            "It must produce 'USD 1.23' or 'EUR 1.23' from a nonnegative integer number of minor units, including "
            "arbitrarily large integers without float rounding. Unsupported currencies and negative amounts raise ValueError. "
            "Update invoices, refunds and exported rows to use each row's currency, including indirect formatter lookup. "
            "Keep billing/display.py unchanged, update the API documentation and add regression coverage. "
            "Use any available local tools; report the affected paths and checks.",
            (
                SourceFile("billing/__init__.py", ""),
                SourceFile(
                    "billing/money.py", "def render_amount(amount_minor: int) -> str:\n    return f'USD {amount_minor / 100:.2f}'\n"
                ),
                SourceFile(
                    "billing/invoices.py",
                    "from billing.money import render_amount as display_total\n\ndef invoice_line(row):\n    return display_total(row['amount_minor'])\n",
                ),
                SourceFile(
                    "billing/refunds.py",
                    "from billing import money\n\ndef refund_line(row):\n    return money.render_amount(row['amount_minor'])\n",
                ),
                SourceFile(
                    "billing/export.py",
                    "import importlib\n\ndef export_rows(rows):\n    formatter = getattr(importlib.import_module('billing.money'), 'render_' + 'amount')\n    return [formatter(row['amount_minor']) for row in rows]\n",
                ),
                SourceFile("billing/display.py", "def render_amount(count):\n    return f'{count} items'\n"),
                SourceFile("docs/api.md", "# Amount rendering\nrender_amount(amount_minor) returns a USD display string.\n"),
                SourceFile(
                    "tests/test_smoke.py",
                    "from billing.invoices import invoice_line\n\ndef test_usd_invoice():\n    assert invoice_line({'amount_minor': 125, 'currency': 'USD'}) == 'USD 1.25'\n",
                ),
            ),
            ("billing/", "tests/", "docs/api.md"),
            ("billing/display.py",),
            """import inspect
import pytest
from billing.money import render_amount
from billing.invoices import invoice_line
from billing.refunds import refund_line
from billing.export import export_rows
from billing.display import render_amount as render_count

def test_required_keyword_currency_contract():
    with pytest.raises(TypeError):
        render_amount(125)
    with pytest.raises(TypeError):
        render_amount(125, 'EUR')
    parameter = inspect.signature(render_amount).parameters['currency']
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty

def test_exact_minor_unit_formatting():
    for value in (0, 1, 99, 123, 10**20 + 37):
        for currency in ('USD', 'EUR'):
            assert render_amount(value, currency=currency) == f'{currency} {value // 100}.{value % 100:02d}'

def test_invalid_currency_and_negative_amount():
    for value, currency in ((1, 'GBP'), (-1, 'USD'), (0, '')):
        with pytest.raises(ValueError):
            render_amount(value, currency=currency)

def test_alias_module_and_reflective_callers():
    rows = [{'amount_minor': 129, 'currency': 'EUR'}, {'amount_minor': 205, 'currency': 'USD'}]
    assert [invoice_line(row) for row in rows] == ['EUR 1.29', 'USD 2.05']
    assert [refund_line(row) for row in rows] == ['EUR 1.29', 'USD 2.05']
    assert export_rows(rows) == ['EUR 1.29', 'USD 2.05']

def test_unrelated_display_stays_compatible():
    assert render_count(3) == '3 items'
""",
            (
                "test_required_keyword_currency_contract",
                "test_exact_minor_unit_formatting",
                "test_invalid_currency_and_negative_amount",
                "test_alias_module_and_reflective_callers",
                "test_unrelated_display_stays_compatible",
            ),
            (
                SourceFile(
                    "billing/money.py",
                    "def render_amount(amount_minor: int, *, currency: str) -> str:\n    if currency not in {'USD', 'EUR'} or amount_minor < 0:\n        raise ValueError('Unsupported currency or negative amount')\n    return f'{currency} {amount_minor // 100}.{amount_minor % 100:02d}'\n",
                ),
                SourceFile(
                    "billing/invoices.py",
                    "from billing.money import render_amount as display_total\n\ndef invoice_line(row):\n    return display_total(row['amount_minor'], currency=row['currency'])\n",
                ),
                SourceFile(
                    "billing/refunds.py",
                    "from billing import money\n\ndef refund_line(row):\n    return money.render_amount(row['amount_minor'], currency=row['currency'])\n",
                ),
                SourceFile(
                    "billing/export.py",
                    "import importlib\n\ndef export_rows(rows):\n    formatter = getattr(importlib.import_module('billing.money'), 'render_' + 'amount')\n    return [formatter(row['amount_minor'], currency=row['currency']) for row in rows]\n",
                ),
                SourceFile(
                    "docs/api.md",
                    "# Amount rendering\nrender_amount(amount_minor, *, currency) requires USD or EUR and returns an exact minor-unit display string. Invalid currencies and negative amounts raise ValueError.\n",
                ),
                SourceFile(
                    "tests/test_currencies.py",
                    "from billing.money import render_amount\nfrom billing.export import export_rows\n\ndef test_eur_and_large_amounts():\n    assert render_amount(10**20 + 37, currency='EUR') == 'EUR 1000000000000000000.37'\n    assert export_rows([{'amount_minor': 129, 'currency': 'EUR'}]) == ['EUR 1.29']\n",
                ),
            ),
            SourceFile(
                "billing/export.py",
                "from billing.money import render_amount\n\ndef export_rows(rows):\n    return [render_amount(row['amount_minor'], currency='USD') for row in rows]\n",
            ),
        )

    @staticmethod
    def _interface() -> TaskSpec:
        return TaskSpec(
            "typescript_gateway_request_migration",
            "typescript",
            "Replace the numeric PaymentGateway.authorize argument with a typed PaymentRequest containing amount and currency. "
            "Currencies are exactly USD or EUR. Update the real gateway, injected checkout and smoke test. "
            "The gateway accepts nonnegative amounts up to 100 USD or 90 EUR, inclusively. "
            "Checkout must forward the caller's request to the injected gateway unchanged in value. "
            "Keep src/other.ts unchanged and document the new API. Avoid weakening the declared request type. "
            "Use any available local tools and validate both type checking and behavior.",
            (
                SourceFile("src/gateway.ts", "export interface PaymentGateway {\n    authorize(amount: number): boolean;\n}\n"),
                SourceFile(
                    "src/real.ts",
                    "import { PaymentGateway } from './gateway';\nexport class RealGateway implements PaymentGateway {\n    authorize(amount: number): boolean { return amount >= 0 && amount <= 100; }\n}\n",
                ),
                SourceFile(
                    "src/client.ts",
                    "import { PaymentGateway } from './gateway';\nexport function checkout(gateway: PaymentGateway, amount: number): boolean {\n    return gateway.authorize(amount);\n}\n",
                ),
                SourceFile(
                    "src/other.ts", "export class Other {\n    authorize(name: string): boolean { return name === 'unchanged'; }\n}\n"
                ),
                SourceFile(
                    "tests/smoke.ts",
                    "import { checkout } from '../src/client';\nimport { RealGateway } from '../src/real';\nif (!checkout(new RealGateway(), 50)) throw new Error('smoke failed');\n",
                ),
                SourceFile(
                    "tsconfig.json",
                    '{"compilerOptions":{"strict":true,"target":"ES2020","module":"commonjs"},"include":["src/**/*.ts","tests/**/*.ts"]}\n',
                ),
                SourceFile("docs/api.md", "# Gateway\nPaymentGateway.authorize accepts a numeric USD amount.\n"),
            ),
            ("src/", "tests/", "docs/api.md"),
            ("src/other.ts",),
            """import { PaymentGateway, PaymentRequest } from './workspace/src/gateway';
import { RealGateway } from './workspace/src/real';
import { checkout } from './workspace/src/client';
import { Other } from './workspace/src/other';
declare const console: { log(value: string): void };

// @ts-expect-error unsupported currencies must not satisfy the public request contract
const badCurrency: PaymentRequest = { amount: 1, currency: 'GBP' };
// @ts-expect-error currency is required in the public request contract
const missingCurrency: PaymentRequest = { amount: 1 };
void badCurrency; void missingCurrency;
const results: { name: string; passed: boolean; detail?: string }[] = [];
function check(name: string, callback: () => void): void {
    try { callback(); results.push({name, passed:true}); }
    catch (error) { results.push({name, passed:false, detail:String(error)}); }
}
function expect(condition: boolean): void { if (!condition) throw new Error('expectation failed'); }
check('currency_specific_boundaries', () => {
    const gateway = new RealGateway();
    for (const [currency, limit] of [['USD',100], ['EUR',90]] as const) {
        for (const amount of [0,1,limit]) expect(gateway.authorize({amount,currency}));
        for (const amount of [-1,limit+1]) expect(!gateway.authorize({amount,currency}));
    }
});
check('checkout_preserves_injected_request', () => {
    let seen: PaymentRequest | undefined;
    const gateway: PaymentGateway = {authorize(request) { seen=request; return request.currency === 'EUR'; }};
    expect(checkout(gateway,{amount:31,currency:'EUR'}));
    expect(seen?.amount === 31 && seen.currency === 'EUR');
    expect(!checkout(gateway,{amount:32,currency:'USD'}));
});
check('independent_injected_denial', () => {
    const gateway: PaymentGateway = {authorize() { return false; }};
    expect(!checkout(gateway,{amount:1,currency:'USD'}));
});
check('unrelated_overload_unchanged', () => {
    expect(new Other().authorize('unchanged'));
    expect(!new Other().authorize('other'));
});
console.log('SELENE_TASK_CHECKS:' + JSON.stringify(results));
""",
            (
                "currency_specific_boundaries",
                "checkout_preserves_injected_request",
                "independent_injected_denial",
                "unrelated_overload_unchanged",
            ),
            (
                SourceFile(
                    "src/gateway.ts",
                    "export interface PaymentRequest {\n    amount: number;\n    currency: 'USD' | 'EUR';\n}\nexport interface PaymentGateway {\n    authorize(request: PaymentRequest): boolean;\n}\n",
                ),
                SourceFile(
                    "src/real.ts",
                    "import { PaymentGateway, PaymentRequest } from './gateway';\nexport class RealGateway implements PaymentGateway {\n    authorize(request: PaymentRequest): boolean {\n        const limit = request.currency === 'USD' ? 100 : 90;\n        return request.amount >= 0 && request.amount <= limit;\n    }\n}\n",
                ),
                SourceFile(
                    "src/client.ts",
                    "import { PaymentGateway, PaymentRequest } from './gateway';\nexport function checkout(gateway: PaymentGateway, request: PaymentRequest): boolean {\n    return gateway.authorize(request);\n}\n",
                ),
                SourceFile(
                    "tests/smoke.ts",
                    "import { checkout } from '../src/client';\nimport { RealGateway } from '../src/real';\nif (!checkout(new RealGateway(), {amount:50,currency:'USD'})) throw new Error('smoke failed');\n",
                ),
                SourceFile(
                    "docs/api.md",
                    "# Gateway\nPaymentGateway.authorize and checkout accept PaymentRequest with amount and USD/EUR currency. RealGateway uses inclusive limits of 100 USD and 90 EUR; negative amounts are denied.\n",
                ),
            ),
            SourceFile(
                "src/client.ts",
                "import { PaymentGateway, PaymentRequest } from './gateway';\nexport function checkout(gateway: PaymentGateway, request: PaymentRequest): boolean {\n    return gateway.authorize({...request, currency:'USD'});\n}\n",
            ),
        )
