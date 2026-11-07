"""¿Esta frase va dirigida a Mango?

Con la ventana de conversación abierta el bot oye **todo** lo que se dice en el
canal, incluida la charla entre otras personas. Para no meterse donde no le
llaman, solo se responde cuando la frase parece dirigida a él:

* menciona «mango» o una palabra de activación,
* empieza por un verbo de mando («pon», «reproduce», «para»…),
* empieza por una palabra interrogativa («qué», «cuál», «cómo»…),
* o es una respuesta corta («sí», «no», «vale»).

Cualquier otra cosa (comentarios, exclamaciones, charla ajena) se ignora.
"""

from __future__ import annotations

from collections.abc import Iterable

from mango.services.texto import normalizar

# Verbos con los que se le pide algo al bot.
VERBOS_MANDO = frozenset(
    {
        "pon", "ponme", "ponle", "ponlo", "ponla", "pone", "poner", "reproduce",
        "reproducir", "reproduceme", "toca", "tocame", "tocala", "para", "parar",
        "detente", "deten", "pausa", "pausar", "pausalo", "resume", "reanuda",
        "continua", "salta", "saltar", "siguiente", "cambia", "cambiame", "sube",
        "baja", "quita", "quitame", "elimina", "borra", "olvida", "agrega",
        "anade", "encola", "busca", "buscame", "dime", "cuentame", "explicame",
        "ayudame", "hazme", "haz", "dame", "mete", "mezcla", "ordena", "repite",
        "vuelve", "silencio", "callate", "sal", "salte", "entra", "ven",
        "escucha", "mira", "sabes", "puedes", "podrias", "tienes", "quiero",
        "di", "dí", "dile", "dilo", "dila", "decir", "anuncia", "lee",
        "leele", "dale", "play",
        # entrar al canal de voz: «ven», «entra», «únete»...
        "venir", "vente", "unete", "conectate", "entrate", "acercate",
        "aparece", "metete",
    }
)

# Palabras que abren una pregunta dirigida al bot.
PREGUNTAS = frozenset(
    {
        "que", "qué", "cual", "cuál", "cuales", "cuáles", "como", "cómo",
        "cuando", "cuándo", "donde", "dónde", "quien", "quién", "quienes",
        "cuanto", "cuánto", "cuanta", "cuánta", "cuantos", "cuántos",
        "por", "para",
    }
)

# Respuestas cortas a algo que preguntó el bot.
CORTAS = frozenset({"si", "sí", "no", "vale", "ok", "okey", "claro", "nop", "yes"})


def es_para_mango(texto: str, wake_words: Iterable[str] = ()) -> bool:
    """True si la frase parece dirigida a Mango (y no charla ajena)."""
    plano = normalizar(texto)
    if not plano:
        return False

    palabras = plano.split()
    primera = palabras[0].strip(".,!?¡¿")

    # 1) Le llaman por su nombre
    if "mango" in palabras or "mangobot" in palabras:
        return True
    for clave in wake_words:
        if normalizar(clave) and normalizar(clave) in plano:
            return True

    # 2) Orden directa
    if primera in VERBOS_MANDO:
        return True

    # 3) Pregunta
    if primera in PREGUNTAS:
        return True

    # 4) Respuesta corta («sí», «no», «vale»)
    return len(palabras) <= 2 and primera in CORTAS
