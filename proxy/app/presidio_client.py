"""Client du service Presidio Analyzer (NER : noms de personnes, lieux...)."""
from __future__ import annotations

import logging

import httpx

from .pii import Span, _sanitize_type

log = logging.getLogger("governance.presidio")


def is_ner_noise(value: str) -> bool:
    """Faux positifs typiques du NER : mots très courts ("OK" pris pour l'Oklahoma) et sigles
    (TJM, BPU, DQE, CCTP pris pour des lieux). Les sigles de clients relèvent du dictionnaire."""
    v = value.strip()
    if len(v) < 3 or (len(v) <= 4 and v.isupper()):
        return True
    # Identifiants, chemins, clés, jetons (VAR=/chemin, clé aléatoire) : faux positifs fréquents.
    # Aucun nom de personne ni de lieu ne contient ces caractères, ni de chiffre accolé à des lettres.
    if any(c in v for c in "=/\\_@:{}[]<>|"):
        return True
    return not any(c.isspace() for c in v) and any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


class PresidioUnavailable(RuntimeError):
    pass


class PresidioNER:
    def __init__(self, url: str, language: str, entities: list[str], score_threshold: float,
                 max_chars: int = 20000, required: bool = True, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self.language = language
        self.entities = entities
        self.score_threshold = score_threshold
        self.max_chars = max_chars
        self.required = required
        self._client = httpx.Client(timeout=timeout)

    def __call__(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for offset, chunk in self._chunks(text):
            spans += [Span(s.start + offset, s.end + offset, s.type, s.value, s.source, s.score)
                      for s in self._analyze(chunk)]
        return spans

    def _chunks(self, text: str):
        """Morceaux de max_chars au plus, coupés de préférence en fin de ligne (un nom n'est
        jamais coupé en deux tant qu'il tient sur une ligne)."""
        pos, n = 0, len(text)
        while pos < n:
            end = min(pos + self.max_chars, n)
            if end < n:
                cut = text.rfind("\n", pos + self.max_chars // 2, end)
                if cut == -1:
                    cut = text.rfind(" ", pos + self.max_chars // 2, end)
                if cut != -1:
                    end = cut + 1
            yield pos, text[pos:end]
            pos = end

    def _analyze(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        try:
            r = self._client.post(
                f"{self.url}/analyze",
                json={
                    "text": text,
                    "language": self.language,
                    "entities": self.entities,
                    "score_threshold": self.score_threshold,
                },
            )
            r.raise_for_status()
            results = r.json()
        except Exception as e:
            if self.required:
                raise PresidioUnavailable(f"Presidio injoignable ou en erreur : {e}") from e
            log.warning("presidio error (fail-open): %s", e)
            return []
        return [
            Span(
                start=x["start"],
                end=x["end"],
                type=_sanitize_type(x["entity_type"]),
                value=text[x["start"]:x["end"]],
                source="presidio",
                score=float(x.get("score", 0)),
            )
            for x in results
            if x["end"] > x["start"] and not is_ner_noise(text[x["start"]:x["end"]])
        ]

    def healthy(self) -> bool:
        try:
            return self._client.get(f"{self.url}/health").status_code == 200
        except Exception:
            return False
