"""
Ré-identification d'un flux SSE de l'API Messages (stream=true).

Difficulté : un jeton PII_EMAIL_3f9a2b1c peut arriver découpé sur plusieurs
content_block_delta. On retient donc, pour chaque bloc, la fin du texte qui pourrait
être le début d'un jeton, et on la relâche au delta suivant ou au content_block_stop.

Les blocs tool_use arrivent en input_json_delta (fragments de JSON) : la valeur
ré-identifiée y est échappée JSON pour que le JSON final reste valide.
Les thinking_delta / signature_delta ne sont jamais touchés.
Les restrictions de RehydrationPolicy s'appliquent selon l'outil du bloc tool_use.
"""
from __future__ import annotations

import json
from typing import Optional

from .pii import Pseudonymizer, RehydrationPolicy, _map_strings, holdback_index

_DELTA_FIELDS = {"text_delta": "text", "input_json_delta": "partial_json"}


class StreamRehydrator:
    def __init__(self, p: Pseudonymizer, policy: Optional[RehydrationPolicy] = None):
        self.p = p
        self.policy = policy or RehydrationPolicy()
        self.pending: dict[int, tuple[str, str]] = {}  # index -> (delta_type, texte retenu)
        self.tools: dict[int, str] = {}  # index -> nom de l'outil (blocs tool_use)

    def _delta_event(self, index: int, delta_type: str, text: str) -> tuple[str, dict]:
        field = _DELTA_FIELDS[delta_type]
        return (
            "content_block_delta",
            {"type": "content_block_delta", "index": index, "delta": {"type": delta_type, field: text}},
        )

    def _rehydrate(self, index: int, delta_type: str, text: str) -> str:
        return self.p.rehydrate(text, json_escape=(delta_type == "input_json_delta"),
                                allow=self.policy.allow_for(self.tools.get(index)))

    def feed(self, event: Optional[str], data: dict) -> list[tuple[Optional[str], dict]]:
        t = data.get("type")

        if t == "content_block_start":
            block = data.get("content_block") or {}
            if block.get("type") == "text" and block.get("text"):
                block["text"] = self.p.rehydrate(block["text"])
            elif block.get("type") == "tool_use":
                self.tools[data.get("index", 0)] = block.get("name") or ""
                if block.get("input"):
                    allow = self.policy.allow_for(block.get("name") or "")
                    block["input"] = _map_strings(block["input"],
                                                  lambda x: self.p.rehydrate(x, allow=allow))
            return [(event, data)]

        if t == "content_block_delta":
            idx = data.get("index", 0)
            delta = data.get("delta") or {}
            dtype = delta.get("type")
            field = _DELTA_FIELDS.get(dtype)
            if field is None:
                return [(event, data)]
            _, held = self.pending.get(idx, (dtype, ""))
            combined = held + (delta.get(field) or "")
            cut = holdback_index(combined)
            safe, rest = combined[:cut], combined[cut:]
            self.pending[idx] = (dtype, rest)
            if not safe:
                return []
            delta[field] = self._rehydrate(idx, dtype, safe)
            return [(event, data)]

        if t == "content_block_stop":
            out: list[tuple[Optional[str], dict]] = []
            idx = data.get("index", 0)
            if idx in self.pending:
                dtype, rest = self.pending.pop(idx)
                if rest:
                    out.append(self._delta_event(idx, dtype, self._rehydrate(idx, dtype, rest)))
            out.append((event, data))
            return out

        if t == "message_stop":
            out = self.flush()
            out.append((event, data))
            return out

        return [(event, data)]

    def flush(self) -> list[tuple[Optional[str], dict]]:
        out = []
        for idx, (dtype, rest) in sorted(self.pending.items()):
            if rest:
                out.append(self._delta_event(idx, dtype, self._rehydrate(idx, dtype, rest)))
        self.pending.clear()
        return out


def _parse_frame(frame: str) -> tuple[Optional[str], Optional[str]]:
    event, data_lines = None, []
    for line in frame.split("\n"):
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    return event, ("\n".join(data_lines) if data_lines else None)


def _format(event: Optional[str], data: dict) -> str:
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


# Événements du protocole Messages. Certains serveurs compatibles ajoutent des doublons (thinking, signature, text…)
# issus des aides du SDK, et recopie les contenus complets dans les événements de fin :
# en mode strict, on ne garde que le protocole standard, sans ces copies (non ré-identifiées).
STANDARD_EVENTS = {"message_start", "content_block_start", "content_block_delta", "content_block_stop",
                   "message_delta", "message_stop", "ping", "error"}
_STRICT_FIELDS = {"content_block_stop": {"type", "index"}, "message_stop": {"type"}}


class SSEProcessor:
    """Reçoit des octets bruts SSE, renvoie des octets SSE ré-identifiés."""

    def __init__(self, p: Pseudonymizer, policy: Optional[RehydrationPolicy] = None, strict: bool = False):
        self.rehydrator = StreamRehydrator(p, policy)
        self.strict = strict
        self._buf = b""

    def _process_frame(self, raw: bytes) -> str:
        frame = raw.decode("utf-8")
        event, data = _parse_frame(frame)
        if data is None:
            return frame + "\n\n"
        try:
            obj = json.loads(data)
        except ValueError:
            return frame + "\n\n"
        if not isinstance(obj, dict):
            return frame + "\n\n"
        if self.strict:
            t = obj.get("type")
            if t not in STANDARD_EVENTS:
                return ""
            if t in _STRICT_FIELDS:
                obj = {k: v for k, v in obj.items() if k in _STRICT_FIELDS[t]}
        return "".join(_format(e, d) for e, d in self.rehydrator.feed(event, obj))

    def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk.replace(b"\r\n", b"\n")
        out: list[str] = []
        while b"\n\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n\n", 1)
            if raw.strip():
                out.append(self._process_frame(raw))
        return "".join(out).encode("utf-8")

    def close(self) -> bytes:
        out = ""
        if self._buf.strip():
            out += self._process_frame(self._buf)
            self._buf = b""
        out += "".join(_format(e, d) for e, d in self.rehydrator.flush())
        return out.encode("utf-8")
