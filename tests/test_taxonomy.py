import typing

import pytest

from app import taxonomy
from app.models import Domain


def test_los_12_dominios_del_contrato_con_etiqueta():
    assert set(taxonomy.DOMAINS) == set(typing.get_args(Domain))
    assert taxonomy.label("motor") == "Movimiento"
    assert taxonomy.label("neuropsiquiatrico") == "Alucinaciones y confusión"
    assert taxonomy.label("inventado") == "Otro"


def test_cada_sintoma_apunta_a_un_dominio_valido():
    assert set(taxonomy.SYMPTOMS.values()) == set(typing.get_args(Domain))
    assert taxonomy.SYMPTOMS["alucinaciones"] == "neuropsiquiatrico"
    assert taxonomy.SYMPTOMS["otro"] == "otro"


def test_los_sinonimos_apuntan_a_claves_existentes():
    assert set(taxonomy._SYNONYMS) <= set(taxonomy.SYMPTOMS)


@pytest.mark.parametrize("raw, key", [
    ("despertares_nocturnos", "despertares_nocturnos"),
    ("Despertares nocturnos", "despertares_nocturnos"),
    ("se despertó", "despertares_nocturnos"),
    ("despertares", "despertares_nocturnos"),
    ("estaba duro", "rigidez"),
    ("veía gente", "alucinaciones"),
    ("anoche hablaba con alguien que no estaba", "alucinaciones"),
    ("CONFUSIÓN", "confusion"),
    ("Apatía", "apatia"),
    ("casi se cae", "casi_caida"),
    ("se cayó en el baño", "caida"),
    ("se marea al pararse", "mareo_al_pararse"),
    ("me sentí trabado", "rigidez"),
    ("mareo-al-pararse", "mareo_al_pararse"),
])
def test_normalize(raw, key):
    assert taxonomy.normalize(raw) == key


@pytest.mark.parametrize("raw", ["", "   ", "algo que no tiene nada que ver", "xyz"])
def test_lo_que_no_se_reconoce_es_otro(raw):
    assert taxonomy.normalize(raw) == "otro"


def test_domain_of():
    assert taxonomy.domain_of("veía gente") == "neuropsiquiatrico"
    assert taxonomy.domain_of("cualquier cosa") == "otro"
