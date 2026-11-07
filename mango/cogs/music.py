"""Comandos de música: YouTube, Spotify y control de reproducción."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

import discord
from discord.ext import commands

from mango import personality
from mango.services.lyrics import LyricsError, LyricsService
from mango.services.spotify import SpotifyError
from mango.services.ytdlp import (
    es_url_spotify,
    es_url_youtube,
    normalizar_url,
    parece_url,
)
from mango.state import LOOP_LABELS, GuildPlayer, Track, VoiceError

log = logging.getLogger(__name__)

# Búsquedas simultáneas al convertir una playlist de Spotify a YouTube.
SPOTIFY_SEARCH_CONCURRENCY = 3
MAX_LYRICS_PAGES = 5


class Music(commands.Cog):
    """Todo lo relacionado con la reproducción de audio."""

    def __init__(self, bot) -> None:
        self.bot = bot

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    async def _require_voice(
        self, ctx: commands.Context
    ) -> Optional[discord.VoiceChannel]:
        voice = getattr(ctx.author, "voice", None)
        if voice is None or voice.channel is None:
            await ctx.send(embed=personality.no_voice_embed())
            return None
        return voice.channel

    def _player(self, ctx: commands.Context) -> GuildPlayer:
        player = self.bot.get_player(ctx.guild)
        player.text_channel = ctx.channel
        return player

    async def _require_listening(
        self, ctx: commands.Context, player: GuildPlayer
    ) -> bool:
        """Solo quien está escuchando puede controlar la música.

        Cualquier miembro presente en el canal del bot puede usar skip,
        pause, resume, stop, volume, remove, shuffle, loop y again.
        """
        if not player.connected:
            await ctx.send(embed=personality.not_connected_embed())
            return False

        channel = player.channel
        voice = getattr(ctx.author, "voice", None)
        author_channel = voice.channel if voice is not None else None
        if channel is not None and author_channel != channel:
            await ctx.send(embed=personality.different_channel_embed(channel))
            return False
        return True

    # ---------------------------------------------------------
    # !play
    # ---------------------------------------------------------
    @commands.command(name="play", aliases=["p", "reproducir", "tocar"])
    @commands.guild_only()
    @commands.cooldown(4, 15, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Reproduce una canción, playlist o link (YouTube / Spotify)."""
        channel = await self._require_voice(ctx)
        if channel is None:
            return

        player = self._player(ctx)
        if (
            player.connected
            and player.channel is not None
            and player.channel != channel
            and player.is_active
        ):
            await ctx.send(embed=personality.different_channel_embed(player.channel))
            return

        try:
            await player.connect(channel)
        except VoiceError as exc:
            await ctx.send(embed=personality.voice_error_embed(str(exc)))
            return
        await self._add_query(ctx, player, query)

    async def _add_query(
        self, ctx: commands.Context, player: GuildPlayer, query: str
    ) -> None:
        query = query.strip()
        if not query:
            await ctx.send(
                embed=personality.warn_embed(
                    "Dime qué pongo. Ejemplo: `!play Daft Punk - One More Time`."
                )
            )
            return

        # Tope de longitud: una "canción" de 5000 caracteres es abuso.
        if len(query) > 300:
            await ctx.send(
                embed=personality.warn_embed(
                    f"Eso es demasiado largo ({len(query)} caracteres). "
                    "Máximo 300: el nombre del tema y el artista."
                )
            )
            return

        requester_id = ctx.author.id
        requester_name = ctx.author.display_name

        # Los enlaces que no son de YouTube ni Spotify se rechazan: sin esto,
        # yt-dlp intentaría descargar cualquier URL (SSRF contra la red local).
        if parece_url(query) and not (es_url_youtube(query) or es_url_spotify(query)):
            await ctx.send(
                embed=personality.error_embed(
                    "Solo acepto enlaces de **YouTube** o **Spotify**.\n"
                    "Pásame el nombre del tema y lo busco yo."
                )
            )
            return

        if es_url_spotify(query):
            if not self.bot.spotify.enabled:
                await ctx.send(
                    embed=personality.error_embed(
                        "Spotify no está configurado en este bot "
                        "(`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`).\n"
                        "Pásame un link de YouTube o el nombre del tema."
                    )
                )
                return
            spotify_ref = self.bot.spotify.parse(query)
            if spotify_ref is None:
                await ctx.send(
                    embed=personality.error_embed(
                        "Ese link de Spotify no lo reconozco. Copia el enlace "
                        "de un tema, playlist o álbum."
                    )
                )
                return
            await self._play_spotify(
                ctx, player, query, spotify_ref[0], requester_id, requester_name
            )
            return

        # Enlaces de YouTube sin `https://` (pegados a mano) se completan.
        query = normalizar_url(query)

        if self.bot.ytdlp.is_playlist_url(query):
            await self._play_youtube_playlist(
                ctx, player, query, requester_id, requester_name
            )
            return

        status = await ctx.send(
            embed=personality.working_embed("Buscando el tema… medio segundo.")
        )

        if self.bot.ytdlp.is_youtube_url(query):
            track: Optional[Track] = Track(
                title="Tema de YouTube",
                url=query,
                requester_id=requester_id,
                requester_name=requester_name,
                source="YouTube",
            )
        else:
            track = await self.bot.ytdlp.search(
                query, requester_id=requester_id, requester_name=requester_name
            )

        if track is None:
            await status.edit(
                embed=personality.error_embed(
                    f"No encontré nada que se parezca a **{query}**. "
                    "Prueba con el nombre del artista incluido."
                )
            )
            return

        await self._enqueue(ctx, player, [track], status=status)

    async def _enqueue(
        self,
        ctx: commands.Context,
        player: GuildPlayer,
        tracks: list[Track],
        *,
        status: Optional[discord.Message] = None,
        source: str = "YouTube",
        skipped: int = 0,
    ) -> None:
        """Mete las canciones en la cola y arranca si no hay nada sonando."""
        max_queue = self.bot.config.max_queue

        added: list[Track] = []
        positions: list[int] = []
        duplicadas: list[tuple[Track, int | None]] = []

        for track in tracks:
            # Si ya está sonando o en la cola, no se repite
            repetida = player.find_duplicate(track)
            if repetida is not None:
                duplicadas.append(repetida)
                continue

            position = player.enqueue(track, max_size=max_queue)
            if position is None:
                break
            added.append(track)
            positions.append(position)

        omitidas = len(tracks) - len(added) - len(duplicadas) + skipped

        if not added:
            if duplicadas:
                existente, posicion = duplicadas[0]
                embed = personality.duplicate_embed(existente, posicion)
            else:
                embed = personality.warn_embed(
                    f"La cola ya tiene {max_queue} canciones. "
                    "Espera a que avance o usa `!stop`."
                )
        elif len(added) == 1 and not duplicadas:
            embed = personality.added_embed(added[0], position=positions[0])
        else:
            embed = personality.playlist_loaded_embed(
                len(added), source, omitidas, len(duplicadas)
            )

        if status is not None:
            await self._safe_edit(status, embed)
        else:
            await ctx.send(embed=embed)

        if added and not (player.is_playing or player.is_paused):
            await player.play_next()

    async def _play_youtube_playlist(
        self,
        ctx: commands.Context,
        player: GuildPlayer,
        url: str,
        requester_id: int,
        requester_name: str,
    ) -> None:
        status = await ctx.send(
            embed=personality.working_embed("Leyendo la playlist de YouTube…")
        )
        try:
            tracks = await self.bot.ytdlp.playlist(
                url,
                limit=self.bot.config.max_playlist_tracks,
                requester_id=requester_id,
                requester_name=requester_name,
            )
        except Exception:
            log.exception("Fallo leyendo playlist de YouTube")
            await self._safe_edit(
                status,
                personality.error_embed(
                    "No pude leer esa playlist. Puede ser privada o estar caída."
                ),
            )
            return

        if not tracks:
            await self._safe_edit(
                status,
                personality.error_embed("La playlist vino vacía: ni un tema utilizable."),
            )
            return

        await self._enqueue(ctx, player, tracks, status=status, source="YouTube")

    async def _play_spotify(
        self,
        ctx: commands.Context,
        player: GuildPlayer,
        url: str,
        kind: str,
        requester_id: int,
        requester_name: str,
    ) -> None:
        status = await ctx.send(
            embed=personality.working_embed("Consultando Spotify…")
        )
        limit = self.bot.config.max_playlist_tracks
        who = {"requester_id": requester_id, "requester_name": requester_name}

        try:
            if kind == "track":
                tracks = [await self.bot.spotify.track(url, **who)]
            elif kind == "playlist":
                tracks = await self.bot.spotify.playlist(url, limit=limit, **who)
            else:
                tracks = await self.bot.spotify.album(url, limit=limit, **who)
        except SpotifyError as exc:
            await self._safe_edit(status, personality.error_embed(str(exc)))
            return
        except Exception:
            log.exception("Fallo consultando Spotify")
            await self._safe_edit(
                status,
                personality.error_embed(
                    "Spotify no respondió como esperaba. Prueba otra vez en un momento."
                ),
            )
            return

        if not tracks:
            await self._safe_edit(
                status,
                personality.error_embed("Esa lista de Spotify no tiene temas utilizables."),
            )
            return

        if len(tracks) == 1:
            await self._safe_edit(
                status, personality.working_embed("Buscando el audio en YouTube…")
            )
            found = await self.bot.ytdlp.search(
                tracks[0].query or tracks[0].title, **who
            )
            if found is None:
                await self._safe_edit(
                    status,
                    personality.error_embed(
                        f"No encontré **{tracks[0].title}** en YouTube."
                    ),
                )
                return
            found.source = "Spotify"
            await self._enqueue(ctx, player, [found], status=status, source="Spotify")
            return

        await self._safe_edit(
            status,
            personality.working_embed(
                f"Emparejando {len(tracks)} temas con YouTube… dame un momento."
            ),
        )
        semaphore = asyncio.Semaphore(SPOTIFY_SEARCH_CONCURRENCY)

        async def resolve(track: Track) -> Optional[Track]:
            async with semaphore:
                found = await self.bot.ytdlp.search(track.query or track.title)
            if found is None:
                return None
            found.source = "Spotify"
            found.requester_id = requester_id
            found.requester_name = requester_name
            return found

        results = await asyncio.gather(
            *(resolve(track) for track in tracks), return_exceptions=True
        )
        matched = [item for item in results if isinstance(item, Track)]
        if not matched:
            await self._safe_edit(
                status,
                personality.error_embed(
                    "No pude emparejar ningún tema de esa playlist con YouTube."
                ),
            )
            return

        await self._enqueue(
            ctx,
            player,
            matched,
            status=status,
            source="Spotify",
            skipped=len(tracks) - len(matched),
        )

    @staticmethod
    async def _safe_edit(message: discord.Message, embed: discord.Embed) -> None:
        try:
            await message.edit(embed=embed)
        except discord.HTTPException:
            log.debug("No pude editar el mensaje %s", message.id)

    # ---------------------------------------------------------
    # Controles: disponibles para cualquiera que esté escuchando
    # ---------------------------------------------------------
    @commands.command(name="skip", aliases=["s", "siguiente"])
    @commands.guild_only()
    @commands.cooldown(5, 10, commands.BucketType.user)
    async def skip(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        next_title = player.queue[0].title if player.queue else None
        if not await player.skip():
            await ctx.send(embed=personality.no_music_embed())
            return
        await ctx.send(embed=personality.skipped_embed(next_title))

    @commands.command(name="stop", aliases=["parar", "detener"])
    @commands.guild_only()
    @commands.cooldown(3, 15, commands.BucketType.user)
    async def stop(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        await player.stop()
        await ctx.send(embed=personality.stopped_embed())

    @commands.command(name="pause", aliases=["pausa", "pausar"])
    @commands.guild_only()
    @commands.cooldown(5, 10, commands.BucketType.user)
    async def pause(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        if not player.pause():
            await ctx.send(embed=personality.no_music_embed())
            return
        await ctx.send(embed=personality.paused_embed())

    @commands.command(name="resume", aliases=["reanudar", "continuar"])
    @commands.guild_only()
    @commands.cooldown(5, 10, commands.BucketType.user)
    async def resume(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        if not player.resume():
            await ctx.send(
                embed=personality.warn_embed("No hay nada en pausa que reanudar.")
            )
            return
        await ctx.send(embed=personality.resumed_embed())

    @commands.command(name="again", aliases=["replay", "repetir_actual"])
    @commands.guild_only()
    @commands.cooldown(3, 20, commands.BucketType.user)
    async def again(self, ctx: commands.Context) -> None:
        """Reinicia la canción que está sonando."""
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        if player.current is None or not await player.replay():
            await ctx.send(embed=personality.no_music_embed())
            return
        await ctx.send(embed=personality.replaying_embed(player.current))

    # ---------------------------------------------------------
    # Información
    # ---------------------------------------------------------
    @commands.command(name="queue", aliases=["q", "cola"])
    @commands.guild_only()
    @commands.cooldown(3, 10, commands.BucketType.user)
    async def queue(self, ctx: commands.Context) -> None:
        player = self.bot.players.get(ctx.guild.id)
        if player is None or (player.current is None and not player.queue):
            await ctx.send(embed=personality.no_music_embed())
            return
        await ctx.send(embed=personality.queue_embed(player))

    @commands.command(name="nowplaying", aliases=["np", "sonando"])
    @commands.guild_only()
    @commands.cooldown(3, 10, commands.BucketType.user)
    async def nowplaying(self, ctx: commands.Context) -> None:
        player = self.bot.players.get(ctx.guild.id)
        if player is None or player.current is None:
            await ctx.send(embed=personality.no_music_embed())
            return
        await ctx.send(embed=personality.now_playing_embed(player.current))

    @commands.command(name="lyrics", aliases=["letra", "letras"])
    @commands.guild_only()
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def lyrics(
        self, ctx: commands.Context, *, query: Optional[str] = None
    ) -> None:
        """Busca la letra del tema actual o del que le indiques."""
        if query is not None and len(query.strip()) > 200:
            await ctx.send(
                embed=personality.warn_embed(
                    "El título es demasiado largo (máximo 200 caracteres)."
                )
            )
            return
        player = self.bot.players.get(ctx.guild.id)
        song = query
        if not song and player is not None and player.current is not None:
            song = player.current.title
        if not song:
            await ctx.send(
                embed=personality.warn_embed(
                    "Dime de qué tema quieres la letra (`!lyrics <tema>`) "
                    "o pon algo primero."
                )
            )
            return

        if not self.bot.lyrics.enabled:
            await ctx.send(
                embed=personality.warn_embed(
                    "El módulo de letras está apagado: falta `GENIUS_TOKEN` en el `.env`."
                )
            )
            return

        status = await ctx.send(
            embed=personality.working_embed(f"Buscando la letra de **{song}**…")
        )
        try:
            result = await self.bot.lyrics.fetch(song)
        except LyricsError as exc:
            await self._safe_edit(status, personality.error_embed(str(exc)))
            return

        if result is None:
            await self._safe_edit(
                status,
                personality.error_embed(
                    f"No encontré la letra de **{song}**. "
                    "Genius no la tiene o hay que afinar la búsqueda."
                ),
            )
            return

        title, text = result
        chunks = LyricsService.chunk(text)
        if not chunks:
            await self._safe_edit(
                status, personality.error_embed("La letra llegó vacía.")
            )
            return

        with contextlib.suppress(discord.HTTPException):
            await status.delete()

        shown = chunks[:MAX_LYRICS_PAGES]
        for index, chunk in enumerate(shown, start=1):
            await ctx.send(
                embed=personality.lyrics_embed(title, chunk, index, len(shown))
            )
        if len(chunks) > len(shown):
            await ctx.send(
                embed=personality.warn_embed(
                    "Corté la letra para no inundar el canal. "
                    "Si falta algo, pídeme el tema con nombre y artista exactos."
                )
            )

    # ---------------------------------------------------------
    # Ajustes de la cola
    # ---------------------------------------------------------
    @commands.command(name="volume", aliases=["vol", "volumen"])
    @commands.guild_only()
    @commands.cooldown(6, 10, commands.BucketType.user)
    async def volume(
        self, ctx: commands.Context, value: Optional[int] = None
    ) -> None:
        player = self._player(ctx)
        if value is None:
            await ctx.send(embed=personality.volume_embed(round(player.volume * 100)))
            return
        if not await self._require_listening(ctx, player):
            return
        clamped = max(0, min(200, value))
        applied = player.set_volume(clamped / 100)
        await ctx.send(embed=personality.volume_embed(round(applied * 100)))

    @commands.command(name="remove", aliases=["quitar", "del"])
    @commands.guild_only()
    @commands.cooldown(5, 10, commands.BucketType.user)
    async def remove(self, ctx: commands.Context, index: int) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        removed = player.remove_index(index)
        if removed is None:
            await ctx.send(
                embed=personality.warn_embed(
                    f"No hay ninguna canción en la posición **{index}**. "
                    "Usa `!queue` para revisar la cola."
                )
            )
            return
        await ctx.send(embed=personality.removed_embed(removed))

    @commands.command(name="shuffle", aliases=["mezclar"])
    @commands.guild_only()
    @commands.cooldown(2, 20, commands.BucketType.user)
    async def shuffle(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        if len(player.queue) < 2:
            await ctx.send(
                embed=personality.warn_embed(
                    "Necesito al menos dos canciones en la cola para mezclar algo."
                )
            )
            return
        count = player.shuffle()
        await ctx.send(embed=personality.shuffled_embed(count))

    @commands.command(name="loop", aliases=["repetir", "bucle"])
    @commands.guild_only()
    @commands.cooldown(4, 15, commands.BucketType.user)
    async def loop(
        self, ctx: commands.Context, mode: Optional[str] = None
    ) -> None:
        player = self._player(ctx)
        if mode is None:
            await ctx.send(embed=personality.loop_embed(player.loop_label))
            return
        if not await self._require_listening(ctx, player):
            return
        try:
            resolved = player.set_loop(mode)
        except ValueError:
            await ctx.send(
                embed=personality.warn_embed("Modos válidos: `off`, `track` o `queue`.")
            )
            return
        await ctx.send(embed=personality.loop_embed(LOOP_LABELS[resolved]))

    # ---------------------------------------------------------
    # Canal de voz
    # ---------------------------------------------------------
    @commands.command(name="hi", aliases=["join", "entrar"])
    @commands.guild_only()
    @commands.cooldown(3, 30, commands.BucketType.user)
    async def hi(self, ctx: commands.Context) -> None:
        channel = await self._require_voice(ctx)
        if channel is None:
            return
        player = self._player(ctx)
        if player.channel is not None and player.channel != channel and player.is_active:
            await ctx.send(embed=personality.different_channel_embed(player.channel))
            return
        already = player.connected
        try:
            await player.connect(channel)
        except VoiceError as exc:
            await ctx.send(embed=personality.voice_error_embed(str(exc)))
            return
        if already:
            await ctx.send(
                embed=personality.already_connected_embed(channel)
            )
            return
        await ctx.send(
            embed=personality.joined_embed(
                channel, listening=self._ai_listening(ctx.guild)
            )
        )

    def _ai_listening(self, guild: discord.Guild) -> bool:
        """¿La IA de voz quedó escuchando tras conectar?"""
        cog = self.bot.get_cog("AIVoice")
        if cog is None:
            return False
        try:
            return bool(cog.diag_report(guild)["listening"])
        except Exception:
            return False

    @commands.command(name="test", aliases=["prueba", "tono", "soundtest"], hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def test_audio(self, ctx: commands.Context) -> None:
        """Tono de prueba para aislar problemas de audio (solo dueño)."""
        channel = await self._require_voice(ctx)
        if channel is None:
            return

        player = self._player(ctx)
        try:
            await player.connect(channel)
        except VoiceError as exc:
            await ctx.send(embed=personality.voice_error_embed(str(exc)))
            return

        original_volume = player.volume
        player.set_volume(1.0)

        source = discord.FFmpegPCMAudio(
            "sine=frequency=440:duration=4",
            before_options="-f lavfi",
            options="-vn -af volume=10",
        )
        if not player.play_source(source):
            player.set_volume(original_volume)
            await ctx.send(
                embed=personality.warn_embed("No pude iniciar el tono de prueba.")
            )
            return

        await ctx.send(embed=personality.sound_test_embed())
        asyncio.create_task(self._restore_volume(player, original_volume))

    @staticmethod
    async def _restore_volume(player: GuildPlayer, volume: float) -> None:
        await asyncio.sleep(6)
        player.set_volume(volume)

    @commands.command(name="bye", aliases=["leave", "salir", "desconectar"])
    @commands.guild_only()
    @commands.cooldown(3, 15, commands.BucketType.user)
    async def bye(self, ctx: commands.Context) -> None:
        player = self._player(ctx)
        if not await self._require_listening(ctx, player):
            return
        await player.disconnect()
        await ctx.send(embed=personality.disconnected_embed())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
