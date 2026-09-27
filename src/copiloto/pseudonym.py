"""Pseudônimo de exibição C-XXXX (HMAC do customer_id).

É pseudonimização, NÃO anonimização: quem tem o segredo e a base consegue reverter.
Serve para que a tela, o vídeo e o LLM não exibam o identificador interno do cliente."""
from __future__ import annotations

import hashlib
import hmac


class Pseudonymizer:
    def __init__(self, secret: bytes):
        if not secret:
            raise ValueError("Segredo de pseudonimização vazio")
        self._secret = secret

    def ref(self, customer_id: str) -> str:
        digest = hmac.new(self._secret, customer_id.encode(), hashlib.sha256).hexdigest().upper()
        return f"C-{digest[:4]}"
