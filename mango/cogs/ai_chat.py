"""Mango AI en texto: comando ``!mango`` (en cualquier canal) y canal dedicado."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Optional

import discord
from discord.ext import commands

from mango import personality
from mango.services.llm import MUSIC_TOOLS, LLMError
from mango.services.texto import es_directiva_entrar, texto_a_decir
from mango.services.tools import MangoTools

log = logging.getLogger(__name__)

MAX_MESSAGE = 1900
# Límites de tasa: cada petición cuesta tokens (dinero) y rate limit de Discord.
# Un usuario no puede pedir más de una respuesta cada AI_USER_COOLDOWN segundos,
# ni más de AI_USER_MAX en AI_USER_WINDOW segundos.
AI_USER_COOLDOWN = 4.0
AI_USER_MAX = 6
AI_USER_WINDOW = 60.0
# Tope de texto que se acepta del usuario (el resto se descarta).
MAX_INPUT = 2000


class AIChat(commands.Cog):
    """Conversación con Mango AI por texto, con memoria y control de música."""

    def __init__(self, bot) -> None:
        self.bot = bot
        # Control de tasa del canal de IA: última petición y ventana deslizante.
        self._ultimo: dict[int, float] = {}
        self._historial: dict[int, list[float]] = {}
        # Una respuesta simultánea por canal (evita ráfagas y prompts gigantes).
        self._candados: dict[int, asyncio.Lock] = {}

    # ---------------------------------------------------------
    # Control de tasa
    # ---------------------------------------------------------
    def _puede_hablar(self, user_id: int) -> bool:
        """True si este usuario puede pedir otra respuesta ahora mismo."""
        ahora = time.monotonic()

        if ahora - self._ultimo.get(user_id, 0.0) < AI_USER_COOLDOWN:
            return False

        ventana = [t for t in self._historial.get(user_id, []) if ahora - t < AI_USER_WINDOW]
        if len(ventana) >= AI_USER_MAX:
            self._historial[user_id] = ventana
            return False

        ventana.append(ahora)
        self._historial[user_id] = ventana
        self._ultimo[user_id] = ahora

        # Poda: el diccionario no debe crecer sin fin en un servidor grande.
        if len(self._ultimo) > 5000:
            self._ultimo.clear()
            self._historial.clear()

        return True

    # ---------------------------------------------------------
    # Comandos
    # ---------------------------------------------------------
    @commands.command(name="mango", aliases=["mangoai"])
    @commands.guild_only()
    @commands.cooldown(2, 10, commands.BucketType.user)
    @commands.max_concurrency(2, commands.BucketType.channel, wait=True)
    async def mango(
        self, ctx: commands.Context, *, question: Optional[str] = None
    ) -> None:
        """``!mango`` muestra el manual; ``!mango <pregunta>`` habla con Mango AI.

        Funciona en CUALQUIER canal de texto del servidor.
        """
        if not question or not question.strip():
            # Mostrar la ayuda no debería gastar el cooldown.
            ctx.command.reset_cooldown(ctx)
            is_owner = await self.bot.is_owner(ctx.author)
            await ctx.send(
                embed=personality.help_embed(
                    self.bot.config.command_prefix, is_owner=is_owner
                )
            )
            return

        # «!mango di <texto>» → lo dice en voz alta (igual que «!ai say»).
        # Con comillas es literal; «di algo divertido» lo inventa la IA.
        dicho = texto_a_decir(question)
        if dicho is not None:
            await self._decir(ctx, dicho)
            return

        # «!mango ven» / «!mango entra al canal» → entra al canal de voz,
        # exactamente igual que `!hi`.
        if es_directiva_entrar(question):
            musica = self.bot.get_cog("Music")
            if musica is not None and hasattr(musica, "hi"):
                await ctx.invoke(musica.hi)
                return
            await ctx.send(
                embed=personality.warn_embed(
                    "No pude entrar al canal; prueba con `!hi`."
                )
            )
            return

        await self._reply(ctx.channel, ctx.author, question.strip())

    async def _decir(self, ctx: commands.Context, texto: str) -> None:
        """Hace que Mango diga un texto por el canal de voz."""
        cog = self.bot.get_cog("AIVoice")
        player = self.bot.players.get(ctx.guild.id)
        if cog is None or player is None or not player.connected:
            await ctx.send(
                embed=personality.warn_embed(
                    "No estoy en un canal de voz. Entra con `!hi` o pídeme música "
                    "y luego repítemelo."
                )
            )
            return

        # Permisos: el dueño siempre; los demás solo si se abre con
        # VOICE_SAY_PUBLIC y están escuchando.
        es_dueno = await self.bot.is_owner(ctx.author)
        if not es_dueno and not self.bot.config.voice_say_public:
            await ctx.send(
                embed=personality.warn_embed(
                    "Que yo hable en voz alta solo lo puede pedir el dueño. "
                    "(`VOICE_SAY_PUBLIC=true` para abrirlo a quien esté escuchando.)"
                )
            )
            return
        if not es_dueno:
            canal_autor = getattr(getattr(ctx.author, "voice", None), "channel", None)
            if canal_autor != player.channel:
                await ctx.send(
                    embed=personality.warn_embed(
                        "Para pedirme que hable, entra a mi canal de voz."
                    )
                )
                return

        if not await cog.speak_text(player, texto):
            await ctx.send(
                embed=personality.warn_embed("No me salió la voz; prueba otra vez.")
            )
            return
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.add_reaction("🔊")

    @commands.command(name="ask", aliases=["ia", "pregunta", "mangoia"])
    @commands.guild_only()
    @commands.cooldown(3, 20, commands.BucketType.user)
    @commands.max_concurrency(2, commands.BucketType.channel, wait=True)
    async def ask(self, ctx: commands.Context, *, question: str) -> None:
        """Pregúntale algo a Mango AI."""
        await self._reply(ctx.channel, ctx.author, question)

    @commands.command(name="forget", aliases=["olvida"])
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def forget(self, ctx: commands.Context) -> None:
        """Borra la memoria de la conversación de este canal."""
        removed = await self.bot.memory.clear(self._scope(ctx.channel.id))
        await ctx.send(
            embed=personality.success_embed(
                f"Memoria borrada ({removed} mensajes). Empezamos de cero."
            )
        )

    # ---------------------------------------------------------
    # Canal dedicado
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        channel_id = self.bot.config.ai_channel_id
        if channel_id is None or message.channel.id != channel_id:
            return

        text = message.content.strip()
        if not text or text.startswith(self.bot.config.command_prefix):
            return

        if len(text) > MAX_INPUT:
            await message.reply(
                embed=personality.warn_embed(
                    f"Eso es demasiado largo ({len(text)} caracteres). "
                    f"Máximo {MAX_INPUT}."
                ),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        # Límite de tasa: sin esto, cualquiera podía inundar el canal y
        # disparar cientos de llamadas al modelo (dinero y rate limit).
        if not self._puede_hablar(message.author.id):
            log.info("Petición ignorada por límite de tasa: %s", message.author)
            return

        candado = self._candados.setdefault(channel_id, asyncio.Lock())
        if candado.locked():
            log.info("Ya hay una respuesta en curso en el canal %s", channel_id)
            return

        async with candado:
            await self._reply(message.channel, message.author, text)

    # ---------------------------------------------------------
    # Lógica
    # ---------------------------------------------------------
    async def _reply(
        self,
        channel: discord.abc.Messageable,
        author: discord.abc.User,
        text: str,
    ) -> None:
        if self.bot.llm is None:
            await channel.send(
                embed=personality.ai_disabled_embed(
                    "Falta configurar el modelo en el `.env`.",
                    self.bot.config.command_prefix,
                )
            )
            return

        scope = self._scope(channel.id)
        history = await self.bot.memory.history(scope, self.bot.config.ai_history_limit)
        guild = getattr(channel, "guild", None)
        autor_miembro = getattr(author, "member", author)
        tools = MangoTools(
            self.bot,
            guild,
            autor_miembro,
            channel,
            voice_channel=getattr(getattr(autor_miembro, "voice", None), "channel", None),
            request_hint=text,
        )
        user_entry = f"{author.display_name}: {text[:1500]}"

        try:
            async with channel.typing():
                reply = await self.bot.llm.reply(
                    history=[*history, {"role": "user", "content": user_entry}],
                    tools=MUSIC_TOOLS,
                    tool_runner=tools.run,
                    max_chars=self.bot.config.ai_max_reply_chars,
                )
        except LLMError as exc:
            await channel.send(embed=personality.ai_error_embed(str(exc)))
            return
        except Exception:
            log.exception("Fallo inesperado en Mango AI (texto)")
            await channel.send(
                embed=personality.ai_error_embed("Algo se enredó por dentro. Prueba otra vez.")
            )
            return

        await self.bot.memory.add(scope, "user", user_entry)
        await self.bot.memory.add(scope, "assistant", reply)

        for chunk in self._chunks(reply):
            await channel.send(
                content=chunk, allowed_mentions=discord.AllowedMentions.none()
            )

    @staticmethod
    def _scope(channel_id: int) -> str:
        """La memoria es por canal: en `#mango-ai` todos comparten contexto."""
        return f"text:{channel_id}"

    @staticmethod
    def _chunks(text: str) -> list[str]:
        chunks: list[str] = []
        current = ""

        for paragraph in text.split("\n"):
            while len(paragraph) > MAX_MESSAGE:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(paragraph[:MAX_MESSAGE])
                paragraph = paragraph[MAX_MESSAGE:]

            if len(current) + len(paragraph) + 1 > MAX_MESSAGE:
                if current:
                    chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n{paragraph}".strip()

        if current:
            chunks.append(current)
        return chunks or [text[:MAX_MESSAGE]]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChat(bot))
