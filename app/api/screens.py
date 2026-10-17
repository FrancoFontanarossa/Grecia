"""Rutas de Juanpe: la API que sirve a las pantallas y las páginas de la app, la neuróloga y el admin.
app/main.py incluye solo `router` de este módulo."""
from fastapi import APIRouter

from app.api import hoy, notifications, people, push
from app.web import routes as web_routes

router = APIRouter()
for module in (people, hoy, push, notifications, web_routes):
    router.include_router(module.router)
