"""Langzeitgedächtnis mit semantischer Suche.

Standardmäßig wird ein vollständig lokaler, abhängigkeitsfreier Embedder verwendet
(gehashte Wort- und Zeichen-n-Gramme mit einfacher deutsch/englischer Stammformbildung).
Er erkennt Wortvarianten ("Projekte" ~ "Projekt", "Python-Skript" ~ "Pythonskripte"),
ist aber kein neuronales Modell. Die ``Embedder``-Schnittstelle erlaubt später den
Austausch gegen z. B. Ollama- oder OpenAI-Embeddings.

Jarvis ruft Erinnerungen bei Bedarf gezielt ab (``recall``), statt alles in den
Modellkontext zu laden. Erinnerungen werden nur aus tatsächlichen Nutzerangaben angelegt.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata

from ..database import Database

DIM = 1024
_SUFFIXES = sorted(["ungen", "ung", "heit", "keit", "lich", "isch", "en", "er", "es", "em", "e", "n", "s",
                    "ing", "ed", "ly", "ies"], key=len, reverse=True)
_STOP = set(["der", "die", "das", "ein", "eine", "einer", "eines", "einem", "einen", "und", "oder", "aber", "ich", "du", "er", "sie", "es", "wir", "ihr", "mein", "meine", "meinen", "meiner", "dein", "deine", "ist", "sind", "war", "bin", "hat", "habe", "haben", "zu", "im", "in", "am", "an", "auf", "aus", "bei", "mit", "von", "vom", "zum", "zur", "für", "nicht", "noch", "auch", "nur", "so", "wie", "was", "wer", "wo", "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "my", "your", "i", "me", "it", "this", "that"])


def _normalize(text: str) -> str:
    text = text.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return [_stem(w) for w in words if w not in _STOP and len(w) > 1]


def _h(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=4).digest(), "little") % DIM


class HashEmbedder:
    name = "local-hash-v1"

    def embed(self, text: str) -> dict[int, float]:
        vec: dict[int, float] = {}
        toks = tokens(text)
        for t in toks:
            vec[_h("w:" + t)] = vec.get(_h("w:" + t), 0.0) + 1.0
            padded = f"^{t}$"
            for i in range(len(padded) - 2):
                k = _h("c:" + padded[i:i + 3])
                vec[k] = vec.get(k, 0.0) + 0.35
        for a, b in zip(toks, toks[1:], strict=False):
            k = _h(f"b:{a}_{b}")
            vec[k] = vec.get(k, 0.0) + 0.5
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


CATEGORIES = ["allgemein", "praeferenz", "projekt", "ziel", "person", "interesse", "aufgabe", "fakt"]


class MemoryStore:
    def __init__(self, db: Database, embedder: HashEmbedder | None = None):
        self.db = db
        self.embedder = embedder or HashEmbedder()

    def _row(self, r: dict) -> dict:
        r = dict(r)
        r.pop("vector", None)
        return r

    def add(self, content: str, category: str = "allgemein", importance: float = 0.5,
            source: str = "user") -> dict:
        content = content.strip()
        if not content:
            raise ValueError("Leere Erinnerung")
        if category not in CATEGORIES:
            category = "allgemein"
        vec = self.embedder.embed(content)
        # Doppelte Erinnerungen zusammenführen statt duplizieren
        for existing in self.db.all("SELECT * FROM memories"):
            if cosine(vec, {int(k): v for k, v in json.loads(existing["vector"]).items()}) > 0.93:
                self.db.update("memories", "id", existing["id"], {
                    "content": content, "updated_at": time.time(),
                    "importance": max(existing["importance"], importance),
                    "vector": json.dumps(vec)})
                return self.get(existing["id"]) | {"merged": True}
        now = time.time()
        mid = self.db.insert("memories", {
            "content": content, "category": category, "importance": max(0.0, min(1.0, importance)),
            "source": source, "vector": json.dumps(vec), "created_at": now, "updated_at": now})
        return self.get(mid)

    def get(self, mid: int) -> dict | None:
        r = self.db.one("SELECT * FROM memories WHERE id = ?", (mid,))
        return self._row(r) if r else None

    def list(self, category: str | None = None, limit: int = 200) -> list[dict]:
        if category:
            rows = self.db.all("SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                               (category, limit))
        else:
            rows = self.db.all("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def update(self, mid: int, content: str | None = None, category: str | None = None,
               importance: float | None = None) -> dict | None:
        cur = self.db.one("SELECT * FROM memories WHERE id = ?", (mid,))
        if not cur:
            return None
        values: dict = {"updated_at": time.time()}
        if content is not None and content.strip():
            values["content"] = content.strip()
            values["vector"] = json.dumps(self.embedder.embed(content))
        if category is not None and category in CATEGORIES:
            values["category"] = category
        if importance is not None:
            values["importance"] = max(0.0, min(1.0, importance))
        self.db.update("memories", "id", mid, values)
        return self.get(mid)

    def delete(self, mid: int) -> bool:
        return self.db.execute("DELETE FROM memories WHERE id = ?", (mid,)).rowcount > 0

    def clear(self) -> int:
        return self.db.execute("DELETE FROM memories").rowcount

    def search(self, query: str, limit: int = 5, min_score: float = 0.12) -> list[dict]:
        qv = self.embedder.embed(query)
        if not qv:
            return []
        now = time.time()
        scored = []
        for r in self.db.all("SELECT * FROM memories"):
            sim = cosine(qv, {int(k): v for k, v in json.loads(r["vector"]).items()})
            if sim <= 0:
                continue
            age_days = (now - r["updated_at"]) / 86400
            recency = math.exp(-age_days / 90)
            score = 0.8 * sim + 0.12 * r["importance"] * sim + 0.08 * recency * sim
            if score >= min_score:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, r in scored[:limit]:
            self.db.update("memories", "id", r["id"], {"last_used": now})
            out.append(self._row(r) | {"score": round(score, 3)})
        return out
