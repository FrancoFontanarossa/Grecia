"""Genera las claves VAPID UNA sola vez e imprime las tres variables para Railway (y tu .env local).
No escribe nada en disco. Si se regeneran, todas las suscripciones push dejan de servir.

    .venv/bin/python scripts/gen_vapid.py mailto:tu@correo
"""
import sys

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from py_vapid.utils import b64urlencode


def main() -> None:
    subject = sys.argv[1] if len(sys.argv) > 1 else "mailto:equipo@entrecasa.uy"
    if not subject.startswith(("mailto:", "https://")):
        sys.exit("VAPID_SUBJECT tiene que empezar con mailto: o https:// (Apple rechaza otros)")
    vapid = Vapid()
    vapid.generate_keys()
    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
    print(f"VAPID_PUBLIC_KEY={b64urlencode(public_raw)}")
    print(f"VAPID_PRIVATE_KEY={b64urlencode(private_raw)}")
    print(f"VAPID_SUBJECT={subject}")


if __name__ == "__main__":
    main()
