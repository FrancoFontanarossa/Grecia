"""Rutas de Juanpe: la API que sirve a las pantallas y las páginas de la app, la neuróloga y el admin.
app/main.py incluye solo `router` de este módulo."""
from fastapi import APIRouter

from app.api import _dev_entries, consents, hoy, notifications, people, push, questions, report, tests
from app.web import routes as web_routes
from app.web import routes_neuro

router = APIRouter()
for module in (people, hoy, push, notifications, questions, tests, consents, report, _dev_entries, web_routes,
               routes_neuro):
    router.include_router(module.router)
