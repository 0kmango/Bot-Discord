"""Comandos de utilidad e información."""

from __future__ import annotations

import contextlib
import logging

import discord
from discord.ext import commands

from mango import personality

log = logging.getLogger(__name__)

# Cogs que `!reload` puede tocar (lista cerrada: evita cargar módulos ajenos).
COGS_VALIDOS = frozenset(
    {"events", "music", "utility", "ai_chat", "ai_voice", "slash"}
)


class Utility(commands.Cog):
    """Ayuda, latencia y comandos privados del dueño."""

    def __init__(self, bot) -> None:
        self.bot = bot

    # ---------------------------------------------------------
    # Públicos
    # ---------------------------------------------------------
    @commands.command(name="ping", aliases=["latencia"])
    async def ping(self, ctx: commands.Context) -> None:
        latency = round(self.bot.latency * 1000)
        if latency < 80:
            mood = "afinado al milímetro."
        elif latency < 200:
            mood = "dentro de lo razonable."
        elif latency < 400:
            mood = "algo desafinado, pero se aguanta."
        else:
            mood = "el servidor va lento; culpa no es mía."
        await ctx.send(
            embed=personality.info_embed(
                f"**{latency} ms** de latencia: {mood}", title="🏓 Pong"
            )
        )

    @commands.command(name="help", aliases=["ayuda", "comandos", "manual"])
    async def help_command(self, ctx: commands.Context) -> None:
        is_owner = await self.bot.is_owner(ctx.author)
        await ctx.send(
            embed=personality.help_embed(
                self.bot.config.command_prefix, is_owner=is_owner
            )
        )

    # ---------------------------------------------------------
    # Privados del dueño
    # ---------------------------------------------------------
    @commands.command(name="embed", hidden=True)
    @commands.is_owner()
    async def embed(self, ctx: commands.Context, *, texto: str) -> None:
        """Publica un embed con la firma de Mango. Comando privado.

        Uso:  !embed Título opcional | Texto del mensaje
        """
        # Se borra la invocación para que el comando pase desapercibido.
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        title = None
        body = texto.strip()
        if "|" in body:
            head, _, rest = body.partition("|")
            head, rest = head.strip(), rest.strip()
            if head and len(head) <= 80:
                title, body = head, rest

        if not body:
            await ctx.send(embed=personality.warn_embed("El embed necesita texto."))
            return
        if len(body) > 4000:
            await ctx.send(
                embed=personality.warn_embed(
                    f"El texto es demasiado largo ({len(body)} caracteres). Máximo: 4000."
                )
            )
            return

        await ctx.send(embed=personality.base_embed(title=title, description=body))

    @commands.command(name="diag", hidden=True)
    @commands.is_owner()
    async def diag(self, ctx: commands.Context) -> None:
        """Diagnóstico de audio y voz (solo dueño)."""
        lines: list[str] = []
        voice = ctx.guild.voice_client
        me_voice = getattr(ctx.guild.me, "voice", None)

        if voice is None:
            lines.append("**Canal de voz:** no conectado (usa `!play` o `!ai join`)")
        else:
            raw_listening = getattr(voice, "is_listening", lambda: False)()
            escuchando = raw_listening is True  # voice_recv devuelve MISSING (Ellipsis)
            lines.append(f"**Canal de voz:** {voice.channel.mention}")
            lines.append(
                f"**Cliente:** `{type(voice).__name__}` · conectado={voice.is_connected()} "
                f"· sonando={voice.is_playing()} · escuchando={escuchando}"
            )
            try:
                privacy = getattr(voice, "voice_privacy_code", None)
            except Exception:
                privacy = "n/d"
            from mango.services.dave import dave_status
            from mango.services.dave import stats as dave_stats

            dave = dave_status(voice)
            if dave.get("supported"):
                lines.append(
                    f"**DAVE/E2EE:** protocolo={dave['protocol']} · sesión={dave['session']} "
                    f"· lista={dave['ready']} · **cifra_salida={dave['can_encrypt']}** "
                    f"· degradado={dave['downgraded']}"
                )
                lines.append(
                    f"**Descifrado entrante:** {dave_stats['decrypted']} cifrados "
                    f"· {dave_stats.get('plain_frames', 0)} en claro "
                    f"· {dave_stats['failed']} fallos"
                )
                if dave["protocol"] > 0 and not dave["can_encrypt"]:
                    lines.append(
                        "⚠️ **DAVE no está listo**: Discord puede descartar mi audio y la voz "
                        "entrante no se descifra. Prueba con otra persona en el canal "
                        "(la sesión DAVE se activa en grupo) o usa un canal sin E2EE."
                    )
            else:
                lines.append(f"**DAVE/E2EE:** no disponible (privacy_code={privacy or 'no'})")
            lines.append(
                "**Permisos de voz:** mute="
                f"{getattr(me_voice, 'mute', None)} · deaf={getattr(me_voice, 'deaf', None)} "
                f"· self_mute={getattr(me_voice, 'self_mute', None)} "
                f"· self_deaf={getattr(me_voice, 'self_deaf', None)}"
            )

        player = self.bot.players.get(ctx.guild.id)
        if player is None:
            lines.append("**Reproductor:** sin inicializar")
        else:
            stats = player.audio_stats
            if not stats:
                lines.append("**Mezclador:** sin inicializar (usa `!play`)")
            else:
                lines.append(
                    f"**Mezclador:** frames={stats.get('frames_served', 0):.0f} "
                    f"· volumen={stats.get('volume', 0):.2f} "
                    f"· voz=x{stats.get('tts_gain', 1):.1f} "
                    f"· música={bool(stats.get('music_active'))} "
                    f"· hablando={bool(stats.get('speaking'))}"
                )
                lines.append(
                    f"**Voz:** música baja solo cuando habla Mango"
                    f" · umbral voz={self.bot.config.voice_energy:.3f}"
                    f" · con música={self.bot.config.voice_energy_music:.3f}"
                )
                segundos = float(stats.get("track_seconds") or 0)
                pico = float(stats.get("track_peak") or 0)
                lines.append(f"**Pista actual:** {segundos:.1f} s · pico={pico:.4f}")
                if stats.get("music_active") and segundos < 0.5:
                    lines.append("⚠️ La música no está entregando audio (mira `mango.log`)")
                if segundos > 3 and pico < 0.01:
                    lines.append("⚠️ Pista silenciosa (intro sin audio o stream roto)")
            if player.current is not None:
                lines.append(f"**Suena:** {player.current.title}")

        cog = self.bot.get_cog("AIVoice")
        if cog is None:
            lines.append("**IA de voz:** cog no cargado")
        else:
            report = cog.diag_report(ctx.guild)
            lines.append(
                f"**IA de voz:** sesión={report['session']} · escuchando={report['listening']} "
                f"· apagada={report['disabled']} · conversando={report['conversando']}"
            )
            lines.append(
                f"**Audio recibido:** {report['frames']} frames de 20 ms "
                f"({report['frames'] * 20 / 1000:.0f} s) · {report['utterances']} frases"
            )
            if report["last_text"]:
                lines.append(f"**Último que oí:** «{report['last_text'][:80]}»")
            if not report["frames"]:
                lines.append(
                    "⚠️ No llega audio: revisa que **no me tengan ensordecido** "
                    "y que alguien esté hablando en el canal."
                )

        embed = personality.info_embed("\n".join(lines)[:3900], title="🩺 Diagnóstico de Mango")
        embed.set_footer(text="Si algo falla aquí, pega este embed y el final de mango.log")
        await ctx.send(embed=embed)

    @commands.command(name="sync", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def sync(self, ctx: commands.Context) -> None:
        """Publica los comandos de barra en este servidor al instante (dueño)."""
        try:
            self.bot.tree.copy_global_to(guild=ctx.guild)
            comandos = await self.bot.tree.sync(guild=ctx.guild)
        except Exception as exc:
            await ctx.send(
                embed=personality.error_embed(f"No pude sincronizar: `{exc}`")
            )
            return

        nombres = ", ".join(f"/{c.name}" for c in comandos) or "ninguno"
        await ctx.send(
            embed=personality.success_embed(
                f"Comandos de barra actualizados (**{len(comandos)}**): {nombres}.\n"
                "Si no los ves, cierra y abre Discord (Ctrl+R)."
            )
        )

    @commands.command(name="reload", hidden=True)
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, extension: str) -> None:
        """Recarga un cog en caliente (útil mientras se desarrolla)."""
        name = extension.strip()
        if not name.startswith("mango.cogs."):
            name = f"mango.cogs.{name}"

        # Solo los cogs del proyecto: nada de cargar módulos arbitrarios.
        if name.rsplit(".", 1)[-1] not in COGS_VALIDOS:
            await ctx.send(
                embed=personality.warn_embed(
                    f"Ese cog no existe. Válidos: {', '.join(sorted(COGS_VALIDOS))}."
                )
            )
            return

        try:
            await self.bot.reload_extension(name)
        except commands.ExtensionNotLoaded:
            try:
                await self.bot.load_extension(name)
            except Exception as exc:
                await ctx.send(
                    embed=personality.error_embed(f"No pude cargar `{name}`: `{exc}`")
                )
                return
        except Exception as exc:
            await ctx.send(
                embed=personality.error_embed(f"No pude recargar `{name}`: `{exc}`")
            )
            return

        await ctx.send(embed=personality.success_embed(f"Recargado `{name}` sin reiniciar."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
