"""Normalización de títulos de canciones.

Se usa para tres cosas:
  · comparar canciones y no encolar duplicados (`GuildPlayer.find_duplicate`),
  · puntuar resultados de búsqueda de YouTube,
  · buscar letras en Genius con títulos «limpios».
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Ruido habitual en los títulos de YouTube
RUIDO = (
    "official", "oficial", "video", "audio", "lyric", "lyrics", "letra",
    "hd", "hq", "4k", "8k", "1080p", "720p", "480p", "remaster",
    "remastered", "remasterizado", "live", "en vivo", "mv", "m/v",
    "visualizer", "visualiser", "video oficial", "audio oficial",
    "slowed", "reverb", "sped up", "extended", "versión", "version",
    "upgrade", "full", "hdr", "explicit", "clean", "topic", "audio oficial",
)

_PARENTESIS = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_FEAT = re.compile(r"(?i)\s+(?:feat|ft|featuring)\.?\s+.*$")
_SUFIJO_TOPIC = re.compile(r"(?i)\s*-\s*topic\s*$")
_ESPACIOS = re.compile(r"\s{2,}")
_PUNTUACION = re.compile(r"[^\w\s]", re.UNICODE)

# Verbos imperativos con los que se pide música («pon», «reproduce»...).
VERBOS_MUSICA = frozenset(
    {
        "reproduce", "reproducir", "reproduceme", "reproduseme", "pon", "ponme",
        "pone", "poner", "ponla", "ponlo", "ponle", "toca", "tocame", "tocale",
        "dale", "dame", "play", "suene", "mete", "metele", "agrega", "anade",
        "anadele", "encola", "busca", "reproducelo",
    }
)

# Palabras que pueden ir antes del verbo sin cambiar la intención.
SALTABLES = frozenset({"oye", "hey", "ey", "hola", "ok", "okay", "okey", "mango", "por", "favor"})

# Muletillas que sobran delante del título.
MULETILLAS = frozenset(
    {
        "algo", "de", "del", "un", "una", "unos", "unas", "la", "el", "los", "las",
        "musica", "cancion", "canciones", "tema", "temas", "favor", "por", "esa",
        "ese", "esta", "este", "otra", "vez", "mas", "me", "mi",
    }
)


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación y con espacios simples."""
    plano = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(caracter for caracter in plano if not unicodedata.combining(caracter))
    return " ".join(_PUNTUACION.sub(" ", sin_tildes.lower()).split())


def limpiar_titulo(texto: str) -> str:
    """Quita «(Official Music Video)», «[HD]», «feat. X», «- Topic»…"""

    def _grupo(match: re.Match[str]) -> str:
        interior = match.group(1).lower()
        # Solo se quita si es claramente ruido: «(I Can't Get No)» se respeta.
        return " " if any(palabra in interior for palabra in RUIDO) else match.group(0)

    limpio = _PARENTESIS.sub(_grupo, texto or "")
    limpio = _FEAT.sub("", limpio)
    limpio = _SUFIJO_TOPIC.sub("", limpio)
    limpio = limpio.replace("_", " ")
    return _ESPACIOS.sub(" ", limpio).strip(" -–—|:,")


def titulo_normalizado(texto: str) -> str:
    """Clave para comparar canciones: sin ruido, sin acentos, en minúsculas."""
    return normalizar(limpiar_titulo(texto))


def es_peticion_musica(texto: str) -> bool:
    """¿La frase empieza pidiendo música? Sirve para prebuscar en paralelo.

    Solo mira las primeras palabras: «oye Mango, reproduce...» sí;
    «que buena canción» no.
    """
    for palabra in normalizar(texto).split()[:4]:
        limpia = palabra.strip(".,!?")
        if limpia in VERBOS_MUSICA:
            return True
        if limpia not in SALTABLES:
            return False
    return False


def limpiar_peticion(texto: str) -> str:
    """Quita muletillas y el verbo: «oye Mango, reproduce tren al sur» → «tren al sur»."""
    palabras = [p for p in (texto or "").replace("¡", " ").replace("¿", " ").split() if p]

    while palabras and normalizar(palabras[0]).strip(".,!?") in SALTABLES:
        palabras.pop(0)
    while palabras and normalizar(palabras[0]).strip(".,!?") in VERBOS_MUSICA:
        palabras.pop(0)
    while palabras and normalizar(palabras[0]).strip(".,!?") in MULETILLAS:
        palabras.pop(0)

    return " ".join(palabras).strip(" ,.;:!?¡¿")


def peticion_compatible(pedida: str, sugerida: str, minimo: float = 0.6) -> bool:
    """¿Ambas frases piden lo mismo? (para reutilizar una prebúsqueda)."""
    actuales = set(normalizar(pedida).split())
    otras = set(normalizar(sugerida).split())
    if not actuales or not otras:
        return False
    return len(actuales & otras) / len(actuales) >= minimo


# --- «di <texto>»: hablar en voz alta -----------------------------------
# Verbos con los que se pide que Mango diga algo.
DIRECTIVAS_DECIR = frozenset(
    {
        "di", "dí", "decir", "dile", "dila", "dilo", "repite", "repetir",
        "say", "anuncia", "lee", "leele",
    }
)

# Si lo que piden es genérico («di algo divertido»), lo inventa la IA en vez de
# leerlo literalmente.
PEDIDOS_GENERICOS = (
    "algo",
    "una frase",
    "un chiste",
    "una historia",
    "lo que sea",
    "cualquier cosa",
    "lo que quieras",
    "una anecdota",
    "un piropo",
    "una adivinanza",
)


def _sin_comillas(texto: str) -> str:
    """Quita las comillas que envuelven todo el texto («"hola"» → «hola»)."""
    limpio = (texto or "").strip()
    if len(limpio) > 2:
        for izquierda, derecha in (('"', '"'), ("'", "'"), ("«", "»"), ("“", "”")):
            if limpio.startswith(izquierda) and limpio.endswith(derecha):
                return limpio[1:-1].strip()
    return limpio


def texto_a_decir(frase: str) -> Optional[str]:
    """«di hola a todos» → «hola a todos»; «di algo divertido» → None (lo crea la IA).

    Con comillas siempre es literal: `!mango di "texto exacto"`.
    """
    limpio = (frase or "").strip()
    if not limpio:
        return None

    # Toda la frase entre comillas: se dice tal cual.
    entre_comillas = _sin_comillas(limpio)
    if entre_comillas != limpio:
        return entre_comillas or None

    palabras = limpio.split()
    primera = normalizar(palabras[0]).strip(".,!?:;")
    if primera not in DIRECTIVAS_DECIR:
        return None

    resto = _sin_comillas(" ".join(palabras[1:]).strip(" :,-"))
    if not resto:
        return None
    plano = normalizar(resto)
    if any(plano.startswith(generico) for generico in PEDIDOS_GENERICOS):
        return None  # que lo inventa la IA
    if plano.startswith("que "):
        resto = resto.split(" ", 1)[1].strip()
    return resto or None


# --- «ven»: entrar al canal de voz --------------------------------------
DIRECTIVAS_ENTRAR = frozenset(
    {
        "ven", "venir", "vente", "entra", "entrate", "unete", "conectate",
        "aparece", "acercate", "metete", "join", "sube",
    }
)

# Palabras que pueden acompañar al verbo sin cambiar la intención.
RELLENO_ENTRAR = frozenset(
    {
        "a", "al", "el", "la", "los", "las", "un", "una", "canal", "voz", "de",
        "del", "aca", "aqui", "por", "favor", "mango", "oye", "hey", "hola",
        "ya", "tu", "mi", "conmigo", "nos", "nuestro", "chat", "y", "porfa",
    }
)


def es_directiva_entrar(frase: str) -> bool:
    """¿Piden que el bot entre al canal de voz? («ven», «entra al canal»…)"""
    limpio = (frase or "").strip()
    if not limpio or "?" in limpio or "¿" in limpio:
        return False

    palabras = normalizar(limpio).split()
    # Se saltan los vocativos iniciales: «mango ven», «oye ven».
    while palabras and palabras[0] in {"mango", "oye", "hey", "hola", "ey", "ok"}:
        palabras.pop(0)
    if not palabras or palabras[0] not in DIRECTIVAS_ENTRAR:
        return False

    resto = [palabra for palabra in palabras[1:] if palabra not in RELLENO_ENTRAR]
    return not resto


# --- Saludos ------------------------------------------------------------
# Palabras que, solas, son un saludo (no una petición).
PALABRAS_SALUDO = frozenset(
    {
        "hola", "holaa", "holas", "buenas", "buenos", "dias", "tardes", "noches",
        "hey", "ey", "hello", "hi", "saludos", "quetal", "tal", "que",
    }
)
# Vocativos que se ignoran al analizar un saludo.
IGNORAR_EN_SALUDO = frozenset({"mango", "mangobot", "oye", "ai", "por", "favor", "che"})


def es_saludo(frase: str) -> bool:
    """¿Es solo un saludo? («hola Mango», «buenas», «hey Mango»)

    En ese caso se saluda de vuelta y **no** se pone música: la frase no pide
    nada. «hola Mango, ¿me escuchas?» no cuenta (lleva una pregunta).
    """
    plano = normalizar(frase).strip(" .,!¡¿?")
    if not plano:
        return False

    palabras = [p for p in plano.split() if p not in IGNORAR_EN_SALUDO]
    if not palabras or len(palabras) > 3:
        return False
    return all(palabra in PALABRAS_SALUDO for palabra in palabras)


# --- ¿Piden música? -----------------------------------------------------
# Nombres de cosas musicales: si aparecen, la frase va de música.
NOUNS_MUSICA = frozenset(
    {
        "cancion", "canciones", "tema", "temas", "musica", "playlist", "lista",
        "album", "disco", "artista", "grupo", "banda", "cola", "volumen",
        "letra", "letras", "pista",
    }
)
# Palabras con las que empieza una pregunta o charla social (no una orden).
INICIO_SOCIAL = frozenset(
    {
        "que", "qué", "cual", "cuál", "como", "cómo", "cuando", "cuándo",
        "donde", "dónde", "quien", "quién", "cuanto", "cuánto", "por",
        "gracias", "ok", "vale", "genial", "jaja",
    }
)


def pide_musica(frase: str) -> bool:
    """¿El usuario ha pedido música **en esta misma frase**?

    Es la barrera que impide que Mango ponga (o repita) música por su cuenta al
    saludar o al hablar de otra cosa. Una canción suelta dicha a secas
    («tren al sur») sí cuenta; un saludo o una pregunta, no.
    """
    if es_peticion_musica(frase):
        return True

    palabras = normalizar(frase).split()
    if not palabras:
        return False
    if any(palabra in NOUNS_MUSICA for palabra in palabras):
        return True
    if es_saludo(frase):
        return False
    # Frase suelta («tren al sur») sí; pregunta o charla social, no.
    return palabras[0].strip(".,!?") not in INICIO_SOCIAL


# Ruido que suele colarse en los títulos de YouTube y no aporta nada al hablar.
RUIDO_HABLA = (
    "lyrics", "lyric", "letra", "letras", "가사", "歌詞", "paroles",
    "color coded", "color coded lyrics", "coded", "eng", "engsub", "eng sub",
    "sub", "subs", "subtitulado", "subtitulada", "español", "espanol",
    "traducido", "traduccion", "traducción", "romanizacion", "romanización",
    "han", "rom", "kor", "easy lyrics", "official", "oficial", "video",
    "audio", "mv", "m/v", "hd", "hq", "4k", "8k", "1080p", "720p",
    "visualizer", "visualiser", "performance", "en vivo", "live", "topic",
    "shadow", "release", "premiere",
)
_GRUPOS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_COMILLAS = "\"'“”‘’«»"
_SEPARADORES = (" - ", " – ", " — ", " —", " // ", " / ")
_ARTISTA_ENTRE_COMILLAS = re.compile(
    r"^(?P<artista>[^|\-\[\]\(\)]+?)\s*['\"“”‘’«»](?P<titulo>[^'\"“”‘’«»]{2,})['\"“”‘’«»]"
)


# --- Controles por voz (sin pasar por el modelo) -------------------------
# Patrones cortos: se ejecutan al instante y el bot confirma con una frase
# cacheada. Así nunca se «pierde» pidiendo datos al modelo.
CONTROLES_VOZ: dict[str, tuple[str, ...]] = {
    "skip": (
        "salta", "salta esta", "salta la cancion", "salta esta cancion",
        "siguiente", "la siguiente", "pasa", "pasa esta", "cambia", "cambiala",
        "cambia la cancion", "next", "skip", "otra", "pon otra", "siguiente cancion",
    ),
    "stop": (
        "para", "parala", "para la musica", "para todo", "deten", "detente",
        "deten la musica", "stop", "corta", "corta la musica", "silencio",
    ),
    "pause": ("pausa", "pausala", "pausa la musica", "pause", "pon pausa"),
    "resume": (
        "reanuda", "reanuda la musica", "continua", "sigue", "resume", "dale",
        "seguimos", "play",
    ),
}


def control_de_voz(frase: str) -> Optional[str]:
    """¿Es una orden corta de control? Devuelve skip/stop/pause/resume o None."""
    limpio = (frase or "").strip()
    if not limpio or "?" in limpio or "¿" in limpio:
        return None

    plano = normalizar(limpio).strip(" .,!¡¿?")
    for accion, patrones in CONTROLES_VOZ.items():
        if plano in {normalizar(p) for p in patrones}:
            return accion
    return None


def separar_titulo_artista(texto: str) -> tuple[str, str]:
    """Devuelve (título, artista) **limpios para hablar**.

    Los títulos de YouTube llevan basura que no se debe leer en voz alta:
    «BTS 'Like Animals' Lyrics (방탄소년단 Like Animals 가사) [Color Coded_Eng]
    | ShadowByYoongi» → título «Like Animals», artista «BTS».

    Solo se usa para la confirmación por voz: el título original sigue
    guardándose para la búsqueda y las letras.
    """
    original = (texto or "").strip()
    if not original:
        return "", ""

    artista = ""
    titulo = original

    # 1) «Artista 'Título'» o «Artista "Título"» (muy habitual en K-pop)
    entre_comillas = _ARTISTA_ENTRE_COMILLAS.match(original)
    if entre_comillas:
        posible = entre_comillas.group("artista").strip(" -–—|:")
        if posible and not any(ruido in posible.lower() for ruido in RUIDO_HABLA):
            artista = posible
            titulo = entre_comillas.group("titulo")

    # 2) Fuera lo que va tras «|» (nombre del canal que subió el vídeo)
    titulo = titulo.split("|")[0]

    # 3) Fuera todos los paréntesis y corchetes: casi siempre son ruido
    titulo = _GRUPOS.sub(" ", titulo)

    # 4) Fuera comillas (al hablar no se dicen) y símbolos que no se pronuncian
    titulo = titulo.translate({ord(c): None for c in _COMILLAS})
    titulo = titulo.replace("$", "").replace("_", " ")

    # 4b) Fuera artistas invitados: «… ft. Pharrell Williams»
    titulo = _FEAT.sub("", titulo)

    # 5) «Artista - Título»
    if not artista:
        for separador in _SEPARADORES:
            if separador in titulo:
                izquierda, _, derecha = titulo.partition(separador)
                izquierda, derecha = izquierda.strip(), derecha.strip()
                if izquierda and derecha:
                    artista, titulo = izquierda, derecha
                    break

    # 6) Palabras sueltas de ruido al final («… Lyrics», «… 가사»)
    titulo = " ".join(titulo.split())
    for _ in range(4):
        bajo = titulo.lower()
        recortado = False
        for ruido in RUIDO_HABLA:
            if bajo.endswith(" " + ruido):
                titulo = titulo[: -len(ruido)].strip(" -–—|:,.")
                recortado = True
                break
            if bajo.startswith(ruido + " "):
                titulo = titulo[len(ruido) :].strip(" -–—|:,.")
                recortado = True
                break
        if not recortado:
            break

    titulo = titulo.strip(" -–—|:,.()[]{}")
    artista = artista.strip(" -–—|:,.()[]{}")
    artista = artista.replace("$", "").replace("_", " ").strip()
    if not titulo:
        titulo, artista = limpiar_titulo(original), ""
    return titulo, artista
