import json
from pathlib import Path

from app import taxonomy
from app.rules import red

EVAL = Path(__file__).parents[1] / "eval"
TIMES = {"anoche", "hoy", "ayer", "vago", "ninguna"}


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


RELATOS = jsonl(EVAL / "sets/relatos.jsonl")
LABELS = {r["id"]: r for r in jsonl(EVAL / "labels/franco.jsonl")}


def test_30_relatos_with_labels():
    assert len(RELATOS) == 30
    assert [r["id"] for r in RELATOS] == list(LABELS)
    assert {r["speaker_role"] for r in RELATOS} == {"paciente", "cuidador", "familiar"}


def test_labels_use_the_taxonomy_and_valid_values():
    roles = {r["id"]: r["speaker_role"] for r in RELATOS}
    for rid, label in LABELS.items():
        for e in label["events"]:
            assert e["domain"] in taxonomy.DOMAINS, rid
            assert e["time"] in TIMES, rid
            assert e["speaker_role"] == roles[rid], rid
            assert isinstance(e["negated"], bool), rid


def test_set_has_what_section_13_asks_for():
    events = [e for label in LABELS.values() for e in label["events"]]
    assert sum(e["negated"] for e in events) >= 3
    assert sum(e["foreign_attribution"] is not None for e in events) >= 4
    assert sum(e["time"] == "vago" for e in events) >= 4
    assert sum(len(label["events"]) == 0 for label in LABELS.values()) >= 2
    assert sum(len(label["events"]) >= 2 for label in LABELS.values()) >= 2


def test_no_relato_is_a_red():
    for r in RELATOS:
        assert red.evaluate(r["text"], ["levodopa/carbidopa", "pramipexol"]) is None, r["id"]


def test_juanpe_file_is_instructions_only_until_he_labels():
    rows = jsonl(EVAL / "labels/juanpe.jsonl")
    assert all("_instrucciones" in r or "events" in r for r in rows)
