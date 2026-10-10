"""Route de décision de l'analyste sur un package en quarantaine."""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from packages.review import NotPending, PackageReviewer, ReplacementRefused, UnknownReview


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
        return await reviewer.decide(
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
