"""Detección de la palabra de activación («oye Mango»).

La comparación es tolerante a tildes, mayúsculas y puntuación, porque el
transcriptor a veces devuelve "Oye, Mango", "oye mango" o "hoy mango".
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES_RE = re.compile(r"\s+")
VOCATIVES = {
    "oye",
    "hoy",
    "oy",
    "hey",
    "hola",
    "oiga",
    "escucha",
    "ey",
    "mira",
    "eh",
    "holaa",
}

# Palabras que el transcriptor suele colar antes del nombre ("o la mango",
# "el mango", "un mango"...). Si TODO lo que precede a "mango" está aquí,
# se considera que el usuario está llamando al bot.
FILLERS = VOCATIVES | {
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "o",
    "a",
    "em",
    "mm",
    "mmm",
    "e",
    "y",
}

MAX_FILLER_TOKENS = 3
FUZZY_DISTANCE = 2


def _distance(a: str, b: str) -> int:
    """Distancia de Levenshtein simple (palabras cortas)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def _looks_like(token: str, options: set[str], max_distance: int = FUZZY_DISTANCE) -> bool:
    return any(_distance(token, option) <= max_distance for option in options)


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin puntuación y con espacios simples."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SPACES_RE.sub(" ", _PUNCT_RE.sub(" ", plain.lower())).strip()


def contains_wake_word(text: str, wake_words: tuple[str, ...]) -> bool:
    """True si la frase contiene alguna palabra de activación.

    Tolera los fallos típicos del transcriptor: «o la mango», «oy mango»,
    «oyemango», «hola mangoo»…
    """
    normalized = normalize(text)
    if not normalized:
        return False

    for word in wake_words:
        candidate = normalize(word)
        if candidate and candidate in normalized:
            return True

    tokens = normalized.split()
    for index, token in enumerate(tokens):
        if "mango" not in token:
            continue

        previous = tokens[:index]
        # "Mango" al principio: llamada directa.
        if not previous:
            return True

        # "oyemango" / "omango": todo pegado en un token.
        if index == 0:
            return True

        # Todos los tokens previos deben ser muletillas/artículos ("o la mango").
        if len(previous) <= MAX_FILLER_TOKENS and all(
            _looks_like(token, FILLERS) for token in previous
        ):
            return True
    return False


def strip_wake_word(text: str, wake_words: tuple[str, ...]) -> str:
    """Quita el «oye Mango» inicial para quedarse con la petición."""
    if not text:
        return ""

    cleaned = text.strip()
    words = cleaned.split()
    for index, word in enumerate(words):
        if "mango" in normalize(word):
            remainder = " ".join(words[index + 1 :]).strip(" ,.;:¡!¿?")
            return remainder or cleaned

    for word in wake_words:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        if pattern.search(cleaned):
            return pattern.sub("", cleaned, count=1).strip(" ,.;:¡!¿?") or cleaned
    return cleaned
