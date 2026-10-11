"""Routes de l'analyste : décision sur un package en quarantaine, puis règles apprises."""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from common.rules import RuleStore
from packages.learning import PackageLearning
from packages.review import NotPending, PackageReviewer, ReplacementRefused, UnknownReview


logger = logging.getLogger(__name__)


class AnalystAuth(Protocol):
    async def user_id(self, access_token: str) -> str | None:
        """Identifiant Supabase Auth du porteur du jeton, ou None si le jeton est invalide."""
        ...


class SupabaseAuth:
    """Fait valider le jeton de session par Supabase Auth : aucune clé de signature côté backend."""

    def __init__(self, client: httpx.AsyncClient, supabase_url: str, api_key: str) -> None:
        self._client = client
        self._url = supabase_url.rstrip("/") + "/auth/v1/user"
        self._api_key = api_key

    async def user_id(self, access_token: str) -> str | None:
        response = await self._client.get(
            self._url, headers={"apikey": self._api_key, "authorization": f"Bearer {access_token}"})
        if response.status_code != 200:
            return None
        user = response.json().get("id")
        return user if isinstance(user, str) and user else None


class Replacement(BaseModel):
    name: str = Field(min_length=1, max_length=214)
    version: str | None = None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "replace"]
    note: str | None = Field(default=None, max_length=1000)
    replacement: Replacement | None = None

    @model_validator(mode="after")
    def _replacement_matches_decision(self) -> "DecisionIn":
        if (self.decision == "replace") != (self.replacement is not None):
            raise ValueError("« replacement » est requis pour remplacer, et seulement dans ce cas")
        return self


async def _analyst(request: Request) -> str:
    """Identité de l'analyste : jeton Supabase Auth valide et droit d'approuver les packages."""
    auth: AnalystAuth | None = request.app.state.analyst_auth
    if auth is None:
        raise HTTPException(status_code=503, detail="Authentification des analystes non configurée.")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Jeton de session manquant.")
    try:
        user_id = await auth.user_id(token)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Supabase Auth injoignable.") from None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Jeton de session invalide.")
    reviewer: PackageReviewer = request.app.state.packages
    analyst = await reviewer.store.analyst(user_id)
    if analyst is None or not analyst["can_approve_packages"]:
        raise HTTPException(status_code=403, detail="Ce compte ne peut pas décider sur les packages.")
    return user_id


router = APIRouter()


@router.post("/packages/{review_id}/decision")
async def decide(
    review_id: UUID, body: DecisionIn, request: Request, analyst: str = Depends(_analyst)
) -> dict[str, Any]:
    reviewer: PackageReviewer = request.app.state.packages
    try:
        result = await reviewer.decide(
            review_id, body.decision, decided_by=analyst, note=body.note,
            replacement_name=body.replacement.name if body.replacement else None,
            replacement_version=body.replacement.version if body.replacement else None,
        )
    except UnknownReview:
        raise HTTPException(status_code=404, detail="Revue de package inconnue.") from None
    except NotPending:
        raise HTTPException(status_code=409, detail="Ce package n'attend plus de décision.") from None
    except ReplacementRefused as exc:
        raise HTTPException(status_code=422, detail=f"Remplacement refusé : {exc}") from None

    # La décision est enregistrée : on en tire des propositions, qui ne changent rien
    # tant qu'un analyste ne les applique pas. Un échec ici n'annule pas la décision.
    learning: PackageLearning | None = getattr(request.app.state, "learning", None)
    if learning is not None:
        try:
            result["rule_proposals"] = [_rule(r) for r in await learning.propose(review_id)]
        except Exception:
            logger.exception("proposition de règles en échec")
            result["rule_proposals"] = []
    return result


# --- règles apprises : rien ne s'applique sans le clic d'un analyste authentifié ---

def _learning(request: Request) -> PackageLearning:
    learning: PackageLearning | None = getattr(request.app.state, "learning", None)
    if learning is None:
        raise HTTPException(status_code=503, detail="Boucle d'apprentissage non branchée.")
    return learning


def _rule(rule: dict[str, Any], rule_list: str = "package") -> dict[str, Any]:
    return {**rule, "list": rule_list,
            "source_decision_id": str(rule["source_decision_id"]),
            "decided_by": str(rule["decided_by"]) if rule["decided_by"] else None}


def _stores(request: Request) -> dict[str, RuleStore]:
    """Listes de règles branchées, par nom : « package », et « decoy » pour les leurres."""
    stores = {"package": _learning(request).rules}
    decoys = getattr(request.app.state, "decoy_learning", None)
    if decoys is not None:
        stores["decoy"] = decoys.rules
    return stores


@router.get("/rules/proposals")
async def proposals(request: Request, analyst: str = Depends(_analyst)) -> dict[str, Any]:
    """Toutes les règles par statut : à appliquer (proposed), annulables (active), historique."""
    stores = _stores(request)
    rows = [_rule(r, name) for name, store in stores.items() for r in await store.rows()]
    return {"current_version": await stores["package"].current_version(),
            **{status: [r for r in rows if r["status"] == status]
               for status in ("proposed", "active", "rolled_back")}}


@router.post("/rules/{rule_list}/{rule_id}/{action}")
async def decide_rule(
    rule_list: Literal["package", "decoy"], rule_id: int, action: Literal["apply", "rollback"],
    request: Request, analyst: str = Depends(_analyst),
) -> dict[str, Any]:
    """apply : proposed → active. rollback : active → rolled_back. Chacun incrémente la version."""
    rules = _stores(request).get(rule_list)
    if rules is None:
        raise HTTPException(status_code=503, detail="Cette liste de règles n'est pas branchée.")
    rule = await (rules.apply if action == "apply" else rules.rollback)(rule_id, analyst)
    if rule is None:
        if await rules.get(rule_id) is None:
            raise HTTPException(status_code=404, detail="Règle inconnue.")
        expected = "proposée" if action == "apply" else "active"
        raise HTTPException(status_code=409, detail=f"Cette règle n'est pas {expected}.")
    return {"rule": _rule(rule, rule_list), "current_version": await rules.current_version()}
