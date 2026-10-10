import json
import secrets

import httpx
import pytest

from tests import fakes
from vault import MemoryTokenStore, Pseudonymizer, Scanner, VaultError
from vault.audit import PromptAudit
from vault.gitguardian import GitGuardianClient
from vault.scanner import TOKEN_RE

pytestmark = pytest.mark.anyio

NAMES = ["Eli Laurent", "Lou Dubois"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def scanner():
    return Scanner(NAMES)


@pytest.fixture
def store():
    return MemoryTokenStore()


@pytest.fixture
def pseudonymizer(store, scanner):
    return Pseudonymizer(store, scanner)


@pytest.mark.parametrize(
    "make, prefix",
    [
        (fakes.aws_key, "SECRET_AWS"),
        (fakes.openai_key, "SECRET_OPENAI"),
        (fakes.github_token, "SECRET_GITHUB"),
        (fakes.postgres_url, "SECRET_PG"),
        (fakes.jwt, "SECRET_JWT"),
        (fakes.private_key, "SECRET_PRIVKEY"),
    ],
)
def test_known_formats(scanner, make, prefix):
    value = make()
    found = scanner.scan_secrets(f"voici la valeur : {value} à ne pas diffuser")
    assert [(d.prefix, d.value) for d in found] == [(prefix, value)]


def test_assignment_and_prose(scanner):
    found = scanner.scan_secrets("config: password = hunter2xyz ; fin")
    assert [(d.prefix, d.value) for d in found] == [("SECRET_GENERIC", "hunter2xyz")]
    assert scanner.scan_secrets("le secret : personne ne doit le savoir") == []
    assert scanner.scan_secrets("Pensez à renouveler votre mot de passe et votre clé API.") == []


def test_entropy_rule(scanner):
    hits = sum(bool(scanner.scan_secrets("clé " + secrets.token_urlsafe(30))) for _ in range(300))
    assert hits >= 295
    hooks = [secrets.token_urlsafe(30) for _ in range(300)]
    exact = sum(
        [d.value for d in scanner.scan_secrets(f"https://hooks.example.com/services/{h}/send")] == [h]
        for h in hooks
    )
    assert exact >= 295
    for benign in (
        "3f2b8c1e-9a4d-4e7b-8c2a-1b2c3d4e5f60",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "/usr/local/lib/python3.11/site-packages/requests",
        "https://example.com/docs/GettingStarted2024/Install",
        "getUserAuthenticationToken2",
    ):
        assert scanner.scan(benign) == [], benign


def test_pii(scanner):
    text = "Contact : Eli.Laurent4@demo-devco.example, 06 12 34 56 78 ou +33 6 12 34 56 78, vu avec eli  LAURENT."
    found = {(d.prefix, d.value) for d in scanner.scan_pii(text)}
    assert found == {
        ("EMAIL", "eli.laurent4@demo-devco.example"),
        ("TELEPHONE", "0612345678"),
        ("TELEPHONE", "+33612345678"),
        ("PERSONNE", "Eli Laurent"),
    }
    assert scanner.scan_pii("Version 3.11.4 publiée le 2026-10-10, ticket 12345678.") == []
    assert scanner.scan_pii("npm install lodash@4.17.21 requests@2.32.0 @scope/pkg@1.0.0") == []
    assert [d.prefix for d in scanner.scan_pii("IBAN FR76 3000 6000 0112 3456 7890 189")] == ["IBAN"]


async def test_tokens_are_typed_and_stable(pseudonymizer, store):
    key = fakes.aws_key()
    first = await pseudonymizer.pseudonymize({"body": f"clé {key}", "copy": [key, {"again": key}]})
    token = first.tokens[0]
    assert TOKEN_RE.fullmatch(token) and token.startswith("SECRET_AWS_")
    assert first.value == {"body": f"clé {token}", "copy": [token, {"again": token}]}
    assert first.tokens == (token,)
    second = await pseudonymizer.pseudonymize(f"encore {key}")
    assert second.value == f"encore {token}"
    assert store.reveal(token) == key
    # Un autre pseudonymiseur sur le même coffre retrouve le même jeton (pas seulement le cache).
    other = await Pseudonymizer(store, Scanner()).pseudonymize(key)
    assert other.value == token


async def test_no_plaintext_left(pseudonymizer):
    values = [fakes.aws_key(), fakes.openai_key(), fakes.github_token(), fakes.postgres_url(), fakes.jwt()]
    obj = {
        "to": "lou.dubois2@demo-devco.example",
        "body": "Bonjour Lou Dubois, " + " / ".join(values) + " tel 01.23.45.67.89",
        "api_key": "abc",
        "headers": {"Authorization": "Bearer " + secrets.token_urlsafe(8)},
        "count": 3,
        "ok": True,
        "none": None,
    }
    result = await pseudonymizer.pseudonymize(obj)
    dumped = json.dumps(result.value, ensure_ascii=False)
    for clear in values + ["lou.dubois2", "Lou Dubois", "01.23.45.67.89", "Bearer", '"abc"']:
        assert clear not in dumped
    assert result.value["count"] == 3 and result.value["ok"] is True and result.value["none"] is None
    assert result.value["api_key"].startswith("SECRET_GENERIC_")
    assert result.value["to"].startswith("EMAIL_")
    assert set(result.value) == set(obj)


async def test_idempotent(pseudonymizer):
    obj = {"note": f"password={secrets.token_urlsafe(9)}1 pour Eli Laurent", "token": fakes.github_token()}
    once = await pseudonymizer.pseudonymize(obj)
    twice = await pseudonymizer.pseudonymize(once.value)
    assert twice.value == once.value and twice.tokens == ()


async def test_keys_and_exotic_types(pseudonymizer):
    class Opaque:
        def __str__(self):
            return "contact eli laurent"

    result = await pseudonymizer.pseudonymize(
        {"eli.laurent4@demo-devco.example": (1, 2), "raw": b"Lou Dubois", "obj": Opaque()}
    )
    (key,) = [k for k in result.value if k.startswith("EMAIL_")]
    assert result.value[key] == [1, 2]
    assert result.value["raw"].startswith("PERSONNE_")
    assert result.value["obj"].startswith("contact PERSONNE_")


async def test_vault_failure_is_fatal(scanner):
    class Down:
        async def tokens_for(self, items):
            raise ConnectionError("base injoignable")

    with pytest.raises(VaultError):
        await Pseudonymizer(Down(), scanner).pseudonymize("écrire à eli.laurent4@demo-devco.example")
    # Rien à pseudonymiser : le coffre n'est pas sollicité.
    assert (await Pseudonymizer(Down(), scanner).pseudonymize("bonjour")).value == "bonjour"


async def test_gitguardian_complements_local_rules(store, scanner):
    odd = "zz-" + "interne-" + "motdepasse-maison"  # invisible pour les règles locales
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["document"] = json.loads(request.content)["document"]
        return httpx.Response(200, json={"policy_breaks": [
            {"type": "Generic Password 2", "matches": [{"type": "password", "match": odd}, {"match": "5432"}]}
        ]})

    client = GitGuardianClient("cle-de-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await Pseudonymizer(store, scanner, client).pseudonymize({"a": f"valeur {odd} ici", "b": "port 5432"})
    assert seen["auth"] == "Token cle-de-test" and odd in seen["document"]
    assert result.value["a"].startswith("valeur SECRET_GENERIC_PASSWORD_") and odd not in result.value["a"]
    assert result.value["b"] == "port 5432"


async def test_gitguardian_outage_falls_back(store, scanner):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = GitGuardianClient("k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    key = fakes.aws_key()
    result = await Pseudonymizer(store, scanner, client).pseudonymize(f"clé {key}")
    assert key not in result.value and result.tokens


async def test_prompt_audit(pseudonymizer, scanner):
    audit = PromptAudit(scanner)
    raw = f"Analyse : {fakes.aws_key()} envoyé à lou.dubois2@demo-devco.example"
    leaked = audit.check(raw, agent="enqueteur")
    assert (leaked.secrets, leaked.pii, leaked.clean) == (1, 1, False)
    assert leaked.kinds == ("EMAIL", "SECRET_AWS")
    safe = (await pseudonymizer.pseudonymize(raw)).value
    assert audit.check(safe, agent="enqueteur").clean
    assert (audit.prompts_checked, audit.secrets_seen, audit.pii_seen) == (2, 1, 1)
