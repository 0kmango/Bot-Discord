from discord.ext import commands
import discord
import yt_dlp
import asyncio
import lyricsgenius
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ===============================
# CONFIGURACIÓN
# ===============================
DISCORD_TOKEN = "TOKEN DISCORD"
GENIUS_TOKEN = "TOKEN GENIUS"

SPOTIFY_CLIENT_ID = "ID SPOTIFY"
SPOTIFY_CLIENT_SECRET = "ID SECRET SPOTIFY"

COMMAND_PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents
)

# ===============================
# APIs
# ===============================
genius = lyricsgenius.Genius(GENIUS_TOKEN)

spotify = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
)

# ===============================
# VARIABLES
# ===============================
music_queue = []
current_voice = None
is_playing = False
current_title = None
current_url = None
inactive_task = None

# ===============================
# CONFIG YTDLP (FIX)
# ===============================
YDL_OPTIONS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "extractor_retries": 3,
    "socket_timeout": 15,
    "default_search": "ytsearch1",
    "extract_flat": False,
    "skip_download": True,
    "geo_bypass": True,
    "nocheckcertificate": True,

    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios"]
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options':
    '-reconnect 1 '
    '-reconnect_streamed 1 '
    '-reconnect_delay_max 5',

    'options': '-vn -bufsize 64k'
}

# ===============================
# PLAY NEXT
# ===============================
async def play_next(ctx):

    global is_playing
    global current_voice
    global current_title
    global inactive_task
    inactive_task = None

    # SI NO HAY MÁS CANCIONES
    if len(music_queue) == 0:

        is_playing = False
        current_title = None

        if inactive_task is None:

            inactive_task = asyncio.create_task(
                auto_disconnect(
                    ctx.guild
                )
            )

        await ctx.send(
            "✅ La cola terminó. Me suicidare en 10 minutos si nadie reproduce música."
        )

        return

    # EVITA DOBLE REPRODUCCIÓN
    if current_voice.is_playing():
        return

    is_playing = True

    url = music_queue.pop(0)

    try:

        def extract():

            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:

                return ydl.extract_info(
                    url,
                    download=False
                )

        info = await asyncio.to_thread(
            extract
        )

        if not info:

            await ctx.send(
                "❌ No se pudo obtener información."
            )

            is_playing = False

            await play_next(ctx)

            return

        if 'entries' in info:

            if not info['entries']:

                is_playing = False

                await play_next(ctx)

                return

            info = info['entries'][0]

        audio_url = info['url']

        current_title = info.get(
            'title',
            'Desconocido'
        )

        source = discord.FFmpegPCMAudio(
            audio_url,
            **FFMPEG_OPTIONS
        )

        def after_playing(error):

            global is_playing

            is_playing = False

            if error:
                print(error)

            fut = asyncio.run_coroutine_threadsafe(
                play_next(ctx),
                bot.loop
            )

            try:
                fut.result()
            except:
                pass

        current_voice.play(
            source,
            after=after_playing
        )

        await ctx.send(
            f"🎵 Reproduciendo ahora: **{current_title}**"
        )

    except Exception as e:

        print("ERROR PLAY_NEXT:", e)

        is_playing = False

        await ctx.send(
            "❌ Error reproduciendo la canción."
        )

        await play_next(ctx)

# ===============================
# AUTO DESCONECTAR POR INACTIVIDAD
# ===============================
async def auto_disconnect(guild):

    global current_voice
    global inactive_task

    await asyncio.sleep(600)  # 10 minutos

    if guild.voice_client:

        if not guild.voice_client.is_playing():

            await guild.voice_client.disconnect()

            current_voice = None

            print(
                "🔌 Desconectado por 10 minutos de inactividad."
            )

    inactive_task = None

# ===============================
# PLAY
# ===============================
@bot.command()
async def play(ctx, *, query: str):

    global current_voice
    global is_playing
    global inactive_task

    if inactive_task:

        inactive_task.cancel()
        inactive_task = None
    

    if ctx.author.voice is None:
        await ctx.send("❌ Debes estar en un canal de voz.")
        return

    if ctx.guild.voice_client is None:
        current_voice = await ctx.author.voice.channel.connect()
    else:
        current_voice = ctx.guild.voice_client

    # ===============================
    # SPOTIFY TRACK
    # ===============================
    if "spotify.com/track/" in query:

        try:

            track_id = query.split("/")[-1].split("?")[0]

            track = spotify.track(track_id)

            nombre = track['name']
            artista = track['artists'][0]['name']

            busqueda = (
                f"ytsearch1:{nombre} "
                f"{artista} official audio"
            )

            def buscar_youtube():

                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:

                    return ydl.extract_info(
                        busqueda,
                        download=False
                    )

            info = await asyncio.to_thread(
                buscar_youtube
            )

            if not info:

                await ctx.send(
                    "❌ No se encontró información."
                )

                return

            if 'entries' not in info:

                await ctx.send(
                    "❌ No hubo resultados."
                )

                return

            video = next(
                (
                    e for e in info['entries']
                    if e and e.get('webpage_url')
                ),
                None
            )

            if not video:

                await ctx.send(
                    "❌ No encontré videos válidos."
                )

                return

            url = video['webpage_url']

            music_queue.append(url)

            await ctx.send(
                f"✅ Añadido: {nombre} - {artista}"
            )

            if not is_playing:
                await play_next(ctx)

        except Exception as e:

            print("ERROR SPOTIFY TRACK:", e)

            await ctx.send(
                "❌ Error procesando Spotify."
            )

            return


    # ===============================
    # SPOTIFY PLAYLIST
    # ===============================
    elif "spotify.com/playlist/" in query:

        playlist = spotify.playlist_tracks(query)

        cantidad = 0

        for item in playlist['items']:

            track = item['track']

            if track is None:
                continue

            try:

                nombre = track['name']
                artista = track['artists'][0]['name']

                busqueda = (
                    f"ytsearch1:{nombre} "
                    f"{artista} official audio"
                )

                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:

                    info = await asyncio.to_thread(
                        ydl.extract_info,
                        busqueda,
                        False
                    )

                if not info or 'entries' not in info:
                    continue

                video = next(
                    (
                        e for e in info['entries']
                        if e and e.get('webpage_url')
                    ),
                    None
                )

                if not video:
                    continue

                url = video['webpage_url']

                music_queue.append(url)

                cantidad += 1

                await ctx.send(
                    f"✅ Añadido: {nombre} - {artista}"
                )

                # SI NO ESTÁ REPRODUCIENDO
                # EMPIEZA ALTIRO
                if not is_playing:

                    await play_next(ctx)

            except Exception as e:

                print("ERROR PLAYLIST:", e)

        await ctx.send(
            f"🎶 Playlist agregada.\nCanciones: {cantidad}"
        )


    # ===============================
    # LINK YOUTUBE
    # ===============================
    elif "youtube.com" in query or "youtu.be" in query:

        music_queue.append(query)

        await ctx.send(
            "✅ Canción añadida."
        )

        if not is_playing:

            await play_next(ctx)

    # ===============================
    # BÚSQUEDA NORMAL
    # ===============================
    else:

        try:

            def buscar():

                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:

                    return ydl.extract_info(
                        f"ytsearch1:{query} audio",
                        download=False
                    )

            info = await asyncio.to_thread(
                buscar
            )

            if not info or 'entries' not in info:

                await ctx.send(
                    "❌ No encontré resultados."
                )

                return

            video = next(
                (
                    e for e in info['entries']
                    if e and e.get('webpage_url')
                ),
                None
            )

            if not video:

                await ctx.send(
                    "❌ No encontré videos válidos."
                )

                return

            url = video['webpage_url']

            music_queue.append(url)

            await ctx.send(
                f"✅ Añadido: {query}"
            )

            if not is_playing:

                await play_next(ctx)

        except Exception as e:

            print("ERROR BUSQUEDA:", e)

            await ctx.send(
                "❌ Error obteniendo el audio."
            )

# ===============================
# COMANDO STOP
# ===============================
@bot.command()
async def stop(ctx):
    global music_queue, current_voice, is_playing

    if current_voice and current_voice.is_playing():
        current_voice.stop()
    music_queue = []
    is_playing = False
    await ctx.send("⏹️ Música detenida y cola vaciada.")

# ===============================
# COMANDO SKIP
# ===============================
@bot.command()
async def skip(ctx):
    global current_voice

    if current_voice and current_voice.is_playing():
        current_voice.stop()
        await ctx.send("⏭️ Canción saltada.")
    else:
        await ctx.send("❌ No hay música reproduciéndose.")

# ===============================
# COMANDO PAUSE
# ===============================
@bot.command()
async def pause(ctx):
    global current_voice

    if current_voice and current_voice.is_playing():
        current_voice.pause()
        await ctx.send("⏸️ Música pausada.")
    else:
        await ctx.send("❌ No hay música reproduciéndose.")

# ===============================
# COMANDO RESUME
# ===============================
@bot.command()
async def resume(ctx):
    global current_voice

    if current_voice and current_voice.is_paused():
        current_voice.resume()
        await ctx.send("▶️ Música reanudada.")
    else:
        await ctx.send("❌ No hay música pausada.")
        
# ===============================
# COMANDO QUEUE
# ===============================
@bot.command()
async def queue(ctx):
    global music_queue, current_title

    if not music_queue and not current_title:
        await ctx.send("❌ No hay música en la cola.")
        return

    chunks = []
    actual = "🎶 **Cola de música:**\n\n"

    if current_title:
        actual += f"▶️ Reproduciendo ahora: **{current_title}**\n\n"

    if music_queue:

        for i, song in enumerate(music_queue, start=1):

            linea = f"{i}. {song}\n"

            if len(actual) + len(linea) > 1900:
                chunks.append(actual)
                actual = linea
            else:
                actual += linea
    else:
        actual += "📭 No hay más canciones en la cola."

    chunks.append(actual)

    for c in chunks:
        await ctx.send(c)

# ===============================
# COMANDO PING
# ===============================
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong ctm! 🏓 Latencia: {round(bot.latency*1000)}ms")

# ===============================
# COMANDO LYRICS
# ===============================
@bot.command()
async def lyrics(ctx, *, query: str = None):
    global current_title

    song_name = query or current_title
    if not song_name:
        await ctx.send("❌ No hay canción reproduciéndose ni me diste un nombre.")
        return

    try:
        song = genius.search_song(song_name)
        if song and song.lyrics:
            chunks = [song.lyrics[i:i+1900] for i in range(0, len(song.lyrics), 1900)]
            for part in chunks:
                await ctx.send(f"📖 Letra de **{song.title}**:\n{part}")
        else:
            await ctx.send("❌ No encontré la letra de esa canción.")
    except Exception as e:
        await ctx.send(f"⚠️ Error al buscar la letra: {e}")

# ===============================
# COMANDO HI (CONECTARSE A VOZ)
# ===============================
@bot.command()
async def hi(ctx):
    global current_voice

    if ctx.author.voice is None:
        await ctx.send("❌ Debes estar en un canal de voz.")
        return

    if ctx.guild.voice_client is None:
        current_voice = await ctx.author.voice.channel.connect()
        await ctx.send("👋 Me uní al canal de voz.")
    else:
        await ctx.send("⚠️ Ya estoy conectado a un canal de voz.")
        
# ===============================
# COMANDO BYE
# ===============================
@bot.command()
async def bye(ctx):

    global current_voice
    global is_playing
    global inactive_task

    if inactive_task:

        inactive_task.cancel()
        inactive_task = None

    if ctx.guild.voice_client is not None:

        await ctx.guild.voice_client.disconnect()

        current_voice = None
        is_playing = False

        await ctx.send(
            "👋 Me fui del canal de voz."
        )

    else:

        await ctx.send(
            "❌ No estoy en ningún canal de voz."
        )

# ===============================
# COMANDO EMBED
# ===============================
@bot.command()
async def embed(ctx, *, mensaje):

    embed = discord.Embed(
        description=mensaje,
        color=discord.Color.blue()
    )

    await ctx.send(embed=embed)
    

# ===============================
# COMANDO HANS
# ===============================
@bot.command()
async def hans(ctx):

    embed = discord.Embed(
        title="🤖 Comandos de Hans Bot",
        description="Lista de comandos disponibles",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🎵 Música",
        value=
        "`!play <canción/link>` → Reproduce música\n"
        "`!skip` → Salta la canción\n"
        "`!pause` → Pausa la música\n"
        "`!again` → Reinicia la música actual\n"
        "`!resume` → Reanuda la música\n"
        "`!stop` → Detiene la música\n"
        "`!queue` → Muestra la cola\n"
        "`!lyrics <canción>` → Busca la letra",
        inline=False
    )

    embed.add_field(
        name="🔊 Voz",
        value=
        "`!hi` → Conecta el bot al canal\n"
        "`!bye` → Desconecta el bot",
        inline=False
    )

    await ctx.send(embed=embed)

# ===============================
# COMANDO MC
# ===============================
@bot.command()
async def mc(ctx):

    embed = discord.Embed(
        title="⛏️ Servidor de Minecraft",
        description="🌐 IP: 26.133.242.21",
        color=discord.Color.green()
    )

    embed.set_footer(text="Hans Bot Minecraft")

    await ctx.send(embed=embed)
    
# ===============================
# AUTO DESCONECTAR SI QUEDA SOLO
# ===============================
@bot.event
async def on_voice_state_update(member, before, after):

    global current_voice
    global is_playing

    voice_client = member.guild.voice_client

    if voice_client is None:
        return

    canal = voice_client.channel

    usuarios = [
        m for m in canal.members
        if not m.bot
    ]

    if len(usuarios) == 0:

        await voice_client.disconnect()

        current_voice = None
        is_playing = False

        print("🔌 Desconectado porque quedó solo en el canal.")

# ===============================
# READY
# ===============================
@bot.event
async def on_ready():
    print(f"✅ Bot iniciado como {bot.user}")

# ===============================
# RUN
# ===============================
bot.run(DISCORD_TOKEN)
