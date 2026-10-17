from app.pipeline import knowledge


def test_knowledge_sin_comentario_y_estable():
    k = knowledge.knowledge()
    assert k.startswith("# Parkinson") and "<!--" not in k[:10] and knowledge.knowledge() == k
    for rojo in ("R1", "R2", "R3", "R4"):
        assert rojo in k


def test_system_blocks_cachea_el_ultimo():
    blocks = knowledge.system_blocks("PROMPT")
    assert [b["text"] for b in blocks] == [knowledge.knowledge(), "PROMPT"]
    assert "cache_control" not in blocks[0] and blocks[1]["cache_control"] == {"type": "ephemeral"}
