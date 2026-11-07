"""Comandos de barra diagonal (``/mclear``…).

Los comandos de barra **no necesitan leer el contenido de los mensajes**, así
que funcionan aunque el bot no tenga el *Message Content Intent*.

Los nombres llevan prefijo ``m`` (``/mclear``) para no chocar con los comandos
de otros bots del servidor.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import discord
from discord import app_commands
from discord.ext import commands

from mango import personality

log = logging.getLogger(__name__)

MAX_BORRADO = 100        # límite de Discord para el borrado masivo
AVISO_SEGUNDOS = 6       # el aviso del bot se borra solo


class Slash(commands.Cog):
    """Comandos con barra diagonal."""

    def __init__(self, bot) -> None:
        self.bot = bot

    # ---------------------------------------------------------
    # /mclear
    # ---------------------------------------------------------
    @app_commands.command(
        name="mclear",
        description="Borra los últimos mensajes de este canal.",
    )
    @app_commands.describe(cantidad=f"Cuántos mensajes borrar (1-{MAX_BORRADO})")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        cantidad: app_commands.Range[int, 1, MAX_BORRADO] = 10,
    ) -> None:
        canal = interaction.channel
        if not isinstance(
            canal, (discord.TextChannel, discord.Thread, discord.VoiceChannel)
        ):
            await interaction.response.send_message(
                "Aquí no puedo borrar mensajes.", ephemeral=True
            )
            return

        guild = interaction.guild
        propio = guild.me if guild is not None else None
        permisos = canal.permissions_for(propio) if propio is not None else None
        if permisos is not None and not permisos.manage_messages:
            await interaction.response.send_message(
                embed=personality.warn_embed(
                    "Necesito el permiso **Gestionar mensajes** en este canal."
                ),
                ephemeral=True,
            )
            return

        # Se difiere (visible): así el aviso final puede verse en el canal.
        await interaction.response.defer(thinking=True)

        try:
            borrados = await canal.purge(limit=int(cantidad), bulk=True)
        except discord.Forbidden:
            await self._aviso(
                interaction, "Discord no me dejó borrar: me faltan permisos."
            )
            return
        except discord.HTTPException as exc:
            log.warning("[mclear] error borrando en %s: %s", canal, exc)
            await self._aviso(interaction, f"No pude borrar: `{exc}`")
            return

        total = len(borrados)
        plural = "s" if total != 1 else ""
        aviso = (
            f"🧹 **{total}** mensaje{plural} eliminado{plural} "
            f"en <#{canal.id}>."
        )
        log.info(
            "[mclear] %s borró %s mensajes en #%s",
            interaction.user,
            total,
            getattr(canal, "name", canal.id),
        )
        await self._aviso(interaction, aviso)
        # El aviso también se limpia solo: no queda basura en el canal.
        asyncio.create_task(self._autoborrar(interaction))

    @staticmethod
    async def _aviso(interaction: discord.Interaction, texto: str) -> None:
        with contextlib.suppress(discord.HTTPException):
            await interaction.edit_original_response(content=texto[:2000])

    @staticmethod
    async def _autoborrar(
        interaction: discord.Interaction, segundos: int = AVISO_SEGUNDOS
    ) -> None:
        await asyncio.sleep(segundos)
        with contextlib.suppress(discord.HTTPException):
            await interaction.delete_original_response()

    # ---------------------------------------------------------
    # Errores de los comandos de barra
    # ---------------------------------------------------------
    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            mensaje = "Necesitas el permiso **Gestionar mensajes** para eso."
        elif isinstance(error, app_commands.CommandOnCooldown):
            mensaje = f"Tranquilo, prueba en {error.retry_after:.1f} s."
        elif isinstance(error, app_commands.CheckFailure):
            mensaje = "No tienes permiso para eso."
        else:
            log.exception("[slash] error en /%s", getattr(interaction.command, "name", "?"))
            mensaje = "Algo se enredó por dentro. Prueba otra vez."

        enviar = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        with contextlib.suppress(discord.HTTPException):
            await enviar(mensaje, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Slash(bot))
