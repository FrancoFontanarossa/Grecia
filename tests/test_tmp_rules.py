from app._tmp_rules import verify_stub
from app.models import Report


def test_verify_stub_no_borra_nada():
    rep = Report(summary="x", topics=[], removed_count=5)
    assert verify_stub(rep, {}, []) == Report(summary="x", topics=[], removed_count=0)
