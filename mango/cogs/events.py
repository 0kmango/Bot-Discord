"""Eventos globales: arranque, estado de voz y manejo de errores."""

from __future__ import annotations

import contextlib
import logging

import discord
from discord.ext import commands

from mango import personality

log = logging.getLogger(__name__)


class Events(commands.Cog):
    """Escucha eventos del gateway y centraliza los errores de comandos."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self._announced = False

    # ---------------------------------------------------------
    # Arranque
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._announced:
            log.info("Reconectado como %s", self.bot.user)
            return

        self._announced = True
        log.info(
            "Mango listo como %s (ID %s) | %s servidores | %s usuarios",
            self.bot.user,
            getattr(self.bot.user, "id", "?"),
            len(self.bot.guilds),
            sum(guild.member_count or 0 for guild in self.bot.guilds),
        )
        await self.bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"🥭 {self.bot.config.command_prefix}help",
            )
        )

    # ---------------------------------------------------------
    # Voz
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if self.bot.user is None:
            return

        # El propio bot se quedó sin canal (expulsado, movido o kick).
        if member.id == self.bot.user.id:
            if after.channel is None:
                player = self.bot.players.get(member.guild.id)
                if player is not None:
                    player.mark_disconnected()
                    log.info("El bot salió del canal de voz en %s", member.guild)
            return

        player = self.bot.players.get(member.guild.id)
        if player is None or not player.connected:
            return

        channel = player.channel
        if channel is None:
            return

        humans = [m for m in getattr(channel, "members", []) if not m.bot]
        if humans:
            player.cancel_alone_disconnect()
        else:
            player.schedule_alone_disconnect()

    # ---------------------------------------------------------
    # Menciones
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.bot.user is None:
            return
        if self.bot.user not in message.mentions:
            return

        content = message.content
        for mention in (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"):
            content = content.replace(mention, "")
        if content.strip():
            return

        await message.channel.send(
            embed=personality.bot_mention_embed(self.bot.config.command_prefix)
        )

    # ---------------------------------------------------------
    # Errores de comandos
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        # Comandos inexistentes: silencio (evita ruido y no da pistas).
        if isinstance(error, commands.CommandNotFound):
            return

        # Comando privado: se borra el mensaje y no se confirma nada.
        if isinstance(error, commands.NotOwner):
            log.warning(
                "Intento de usar comando privado '%s' por %s (%s)",
                getattr(ctx.command, "qualified_name", "?"),
                ctx.author,
                ctx.author.id,
            )
            await self._silent_delete(ctx.message)
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await self._reply(
                ctx,
                personality.warn_embed(
                    f"Me falta un dato: **{error.param.name}**.\n"
                    f"Ejemplo: `{ctx.prefix}{ctx.command} ...`"
                ),
            )
            return

        if isinstance(error, commands.BadArgument):
            await self._reply(
                ctx,
                personality.warn_embed(
                    "Ese valor no me encaja. Revisa el comando y pruébalo otra vez."
                ),
            )
            return

        if isinstance(error, commands.CommandOnCooldown):
            await self._reply(
                ctx,
                personality.warn_embed(
                    f"Tranquilo, que me quemo. Prueba en **{error.retry_after:.1f} s**."
                ),
            )
            return

        if isinstance(error, commands.MaxConcurrencyReached):
            await self._reply(
                ctx,
                personality.warn_embed(
                    "Ya estoy procesando algo en este servidor. Dame un segundo."
                ),
            )
            return

        if isinstance(error, commands.NoPrivateMessage):
            await self._reply(
                ctx, personality.warn_embed("Esto solo funciona dentro de un servidor.")
            )
            return

        if isinstance(error, commands.CheckFailure):
            await self._reply(ctx, personality.warn_embed("No tienes permiso para eso."))
            return

        if isinstance(error, commands.CommandInvokeError):
            log.exception(
                "Error ejecutando '%s' (invocado por %s)",
                getattr(ctx.command, "qualified_name", "?"),
                ctx.author,
                exc_info=error.original,
            )
            await self._reply(
                ctx,
                personality.error_embed(
                    f"{personality.pick(personality.ERROR_LINES)}\n"
                    "Ya quedó registrado en el log del bot."
                ),
            )
            return

        log.exception(
            "Error no controlado en '%s'",
            getattr(ctx.command, "qualified_name", "?"),
            exc_info=error,
        )

    # ---------------------------------------------------------
    # Utilidades
    # ---------------------------------------------------------
    async def _reply(self, ctx: commands.Context, embed: discord.Embed) -> None:
        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            log.debug("No pude responder en el canal %s", ctx.channel.id)

    @staticmethod
    async def _silent_delete(message: discord.Message) -> None:
        with contextlib.suppress(discord.HTTPException):
            await message.delete()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Events(bot))
