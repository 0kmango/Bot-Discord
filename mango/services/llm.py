"""Cliente LLM compatible con OpenAI (OpenAI, Groq, Ollama, OpenRouter…).

Incluye el bucle de *function calling* para que Mango AI pueda controlar la
música del servidor con lenguaje natural.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, Optional

from mango import personality

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3
MAX_TOKENS = 500

ToolRunner = Callable[[str, dict[str, Any]], Awaitable[str]]

MUSIC_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": (
                "Reproduce o encola música en el canal de voz del usuario. "
                "Úsala SIEMPRE que pidan poner, reproducir, escuchar o añadir una "
                "canción, artista, género o playlist. Pasa la petición COMPLETA tal "
                "como la dijeron, con el artista si lo mencionaron (p. ej. «avalon "
                "suicideboys»); nunca la recortes a una sola palabra. Si el texto "
                "parece mal transcrito por voz, deduce la canción real y escribe el "
                "nombre y el artista correctos (p. ej. «Pomp Get Lucky» → «Daft Punk "
                "Get Lucky», «Avelan» → «AVALON $uicideboy$»). "
                "NO la uses para saludar, para responder a una charla ni para "
                "repetir la canción anterior: solo si en ESA misma frase te piden "
                "música. No pidas el artista como condición ni respondas que no "
                "puedes reproducir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Canción, artista, género o enlace a reproducir",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skip_music",
            "description": "Salta la canción que está sonando ahora mismo.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_music",
            "description": "Detiene la música y vacía la cola.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "now_playing",
            "description": "Consulta qué canción está sonando y el estado de la reproducción.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_info",
            "description": "Consulta cuántas canciones hay en la cola y cuáles son las siguientes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_voice",
            "description": (
                "Desconecta a Mango del canal de voz. Úsala SOLO si el usuario "
                "pide explícitamente que se salga o que se desconecte del canal."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "join_voice",
            "description": (
                "Entra (o se cambia) al canal de voz del usuario. Úsala cuando "
                "pidan que venga, entre, se una o se conecte al canal («ven», "
                "«entra al canal», «únete», «conéctate»)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "say_text",
            "description": (
                "Dice en voz ALTA por el canal de voz el texto indicado, como un "
                "locutor. Úsala cuando pidan que digas algo en voz alta («di…», "
                "«di que…», «anuncia…», «léelo en voz alta»). Si piden algo "
                "inventado («di algo divertido»), crea tú el texto y pásalo aquí. "
                "No la uses para responder una charla normal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {
                        "type": "string",
                        "description": "El texto exacto que debe decir en voz alta.",
                    }
                },
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_lyrics",
            "description": "Busca la letra de una canción.",
            "parameters": {
                "type": "object",
                "properties": {
                    "song": {
                        "type": "string",
                        "description": "Título y artista de la canción",
                    }
                },
                "required": ["song"],
            },
        },
    },
]


class LLMError(RuntimeError):
    """Fallo al hablar con el modelo."""


class LLMService:
    """Envoltorio asíncrono del endpoint de chat con soporte de herramientas."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        reasoning_effort: str = "",
    ) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self.temperature = temperature
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self._client = AsyncOpenAI(
            base_url=base_url or None,
            api_key=api_key,
            timeout=60.0,
            max_retries=1,
        )

    async def reply(
        self,
        *,
        history: Sequence[dict[str, str]],
        system: str = personality.MANGO_AI_PERSONA,
        tools: Optional[Sequence[dict[str, Any]]] = None,
        tool_runner: Optional[ToolRunner] = None,
        max_chars: int = 1500,
    ) -> str:
        """Devuelve la respuesta del modelo, resolviendo herramientas si las hay."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *history,
        ]
        use_tools = bool(tools and tool_runner)
        extra: dict[str, Any] = {}
        if self.reasoning_effort in {"low", "medium", "high"}:
            extra["reasoning_effort"] = self.reasoning_effort

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": MAX_TOKENS,
            **extra,
        }
        if use_tools and tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"

        for _round in range(MAX_TOOL_ROUNDS + 1):
            try:
                completion = await self._client.chat.completions.create(**request)
            except Exception as exc:
                log.exception("Error llamando al LLM (%s)", self.model)
                raise LLMError(
                    "El modelo no respondió. Revisa `LLM_API_KEY`, `LLM_MODEL` y "
                    "`LLM_BASE_URL` en el `.env`."
                ) from exc

            if not completion.choices:
                raise LLMError("El modelo devolvió una respuesta vacía.")

            message = completion.choices[0].message
            calls = getattr(message, "tool_calls", None)

            if calls and tool_runner is not None:
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            call.model_dump() if hasattr(call, "model_dump") else call
                            for call in calls
                        ],
                    }
                )
                for call in calls:
                    name = getattr(call.function, "name", "")
                    arguments = self._parse_arguments(call)
                    log.info("Herramienta solicitada: %s(%s)", name, arguments)
                    try:
                        result = await tool_runner(name, arguments)
                    except Exception:
                        log.exception("La herramienta %s falló", name)
                        result = f"Error ejecutando {name}."
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": getattr(call, "id", ""),
                            "content": str(result)[:1000],
                        }
                    )
                continue

            text = (message.content or "").strip()
            if not text:
                raise LLMError("El modelo devolvió una respuesta vacía.")
            return text[:max_chars]

        return "Me quedé dándole vueltas. ¿Me lo repites?"

    async def stream(
        self,
        *,
        history: Sequence[dict[str, str]],
        system: str = personality.MANGO_AI_PERSONA,
        tools: Optional[Sequence[dict[str, Any]]] = None,
        tool_runner: Optional[ToolRunner] = None,
        max_chars: int = 1500,
    ) -> AsyncIterator[str]:
        """Como :meth:`reply` pero entregando el texto por trozos.

        Permite empezar a hablar antes de que el modelo termine, lo que baja
        mucho la latencia percibida en la voz.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *history,
        ]
        use_tools = bool(tools and tool_runner)
        extra: dict[str, Any] = {}
        if self.reasoning_effort in {"low", "medium", "high"}:
            extra["reasoning_effort"] = self.reasoning_effort

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": MAX_TOKENS,
            "stream": True,
            **extra,
        }
        # Solo se añaden si hay herramientas: enviar "tool_choice": null da 400
        # en algunos proveedores (Groq).
        if use_tools and tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"

        emitidos = 0
        for _round in range(MAX_TOOL_ROUNDS + 1):
            try:
                flujo = await self._client.chat.completions.create(**request)
            except Exception as exc:
                log.exception("Error llamando al LLM en streaming (%s)", self.model)
                raise LLMError(
                    "El modelo no respondió. Revisa `LLM_API_KEY`, `LLM_MODEL` y "
                    "`LLM_BASE_URL` en el `.env`."
                ) from exc

            contenido = ""
            llamadas: dict[int, dict[str, str]] = {}

            async for trozo in flujo:
                if not trozo.choices:
                    continue
                delta = trozo.choices[0].delta
                texto = getattr(delta, "content", None)
                if texto:
                    contenido += texto
                    emitidos += len(texto)
                    yield texto
                    if emitidos >= max_chars:
                        return

                for llamada in getattr(delta, "tool_calls", None) or []:
                    slot = llamadas.setdefault(
                        getattr(llamada, "index", 0),
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if getattr(llamada, "id", None):
                        slot["id"] = llamada.id
                    funcion = getattr(llamada, "function", None)
                    if funcion is not None:
                        if getattr(funcion, "name", None):
                            slot["name"] += funcion.name
                        if getattr(funcion, "arguments", None):
                            slot["arguments"] += funcion.arguments

            if llamadas and tool_runner is not None:
                messages.append(
                    {
                        "role": "assistant",
                        "content": contenido,
                        "tool_calls": [
                            {
                                "id": slot["id"],
                                "type": "function",
                                "function": {
                                    "name": slot["name"],
                                    "arguments": slot["arguments"] or "{}",
                                },
                            }
                            for slot in llamadas.values()
                        ],
                    }
                )
                for slot in llamadas.values():
                    log.info(
                        "Herramienta solicitada: %s(%s)", slot["name"], slot["arguments"]
                    )
                    try:
                        argumentos = json.loads(slot["arguments"] or "{}")
                    except json.JSONDecodeError:
                        argumentos = {}
                    if not isinstance(argumentos, dict):
                        argumentos = {}
                    try:
                        resultado = await tool_runner(slot["name"], argumentos)
                    except Exception:
                        log.exception("La herramienta %s falló", slot["name"])
                        resultado = f"Error ejecutando {slot['name']}."
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": slot["id"],
                            "content": str(resultado)[:1000],
                        }
                    )
                # Si la herramienta ya le respondió al usuario (p. ej. confirmó
                # la canción hablando), no se pide otra vuelta al modelo: menos
                # latencia y sin repetir el título.
                if getattr(getattr(tool_runner, "__self__", None), "handled_reply", False):
                    log.debug("La herramienta ya respondió; no se consulta otra vez al modelo")
                    return
                continue
            return

        return

    @staticmethod
    def _parse_arguments(call: Any) -> dict[str, Any]:
        raw = getattr(call.function, "arguments", "") or "{}"
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            log.warning("Argumentos de herramienta inválidos: %r", raw)
            return {}
        return parsed if isinstance(parsed, dict) else {}


class LLMRouter:
    """Cadena de proveedores: si el primero falla, prueba el siguiente.

    Permite tener un LLM principal (rápido) y un respaldo por si agota
    cuota, se cae o rechaza el modelo. Ambos exponen el mismo ``reply()``.
    """

    def __init__(self, services: Sequence[LLMService]) -> None:
        if not services:
            raise ValueError("LLMRouter necesita al menos un proveedor")
        self._services = list(services)

    @property
    def model(self) -> str:
        return self._services[0].model

    @property
    def chain(self) -> list[str]:
        return [service.model for service in self._services]

    async def reply(self, **kwargs: Any) -> str:
        last_error: Exception | None = None
        for index, service in enumerate(self._services):
            try:
                return await service.reply(**kwargs)
            except LLMError as exc:
                last_error = exc
                if index + 1 < len(self._services):
                    log.warning(
                        "El proveedor %s falló (%s); pruebo con %s",
                        service.model,
                        str(exc)[:120],
                        self._services[index + 1].model,
                    )
        raise last_error or LLMError("Ningún proveedor de LLM respondió.")
