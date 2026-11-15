"""Gestion centralisée des erreurs de l'API : réponses JSON homogènes et lisibles.

Format unique : ``{"detail": "<message en français>", ...}``. Les erreurs de validation
listent chaque champ fautif ; une erreur inattendue est journalisée avec sa trace complète
et renvoie un message neutre (aucune donnée interne exposée), sans arrêter l'application.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

log = logging.getLogger("astro.api")


def _champ(location: tuple) -> str:
    """Nom lisible du champ : on retire « body » / « query » en tête."""
    parts = [str(p) for p in location if p not in ("body", "query", "path")]
    return ".".join(parts) or "requête"


async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"champ": _champ(e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Données invalides", "erreurs": errors},
    )


async def integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
    log.warning("Contrainte de base de données violée : %s", exc.orig)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Opération refusée : elle viole une règle d'intégrité des données."},
    )


async def database_error(_request: Request, exc: OperationalError) -> JSONResponse:
    log.error("Base de données indisponible : %s", exc.orig)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Base de données momentanément indisponible, réessayez."},
    )


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Erreur inattendue sur %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erreur interne du serveur : l’incident est journalisé."},
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(IntegrityError, integrity_error)
    app.add_exception_handler(OperationalError, database_error)

    @app.middleware("http")
    async def catch_unexpected(request: Request, call_next):
        # Middleware plutôt qu'un gestionnaire Exception : en mode debug, Starlette afficherait
        # sinon la trace complète au client. La trace reste dans les journaux du serveur.
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - dernier filet de sécurité
            return await unexpected_error(request, exc)
