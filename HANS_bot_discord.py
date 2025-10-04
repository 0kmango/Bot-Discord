
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import lyricsgenius 
from dotenv import load_dotenv

# ===============================
# CONFIGURACIÓN
# ===============================
TOKEN = "TOKEN_DISCORD"
COMMAND_PREFIX = "!"

# ===============================
# INTENTS
# ===============================
load_dotenv()
intents = discord.Intents.default()
intents.message_content = True

# ===============================
# BOT
# ===============================
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
genius = lyricsgenius.Genius("TOKEN_GENIUS_LYRICS")
GENIUS_TOKEN="TOKEN_GENIUS"
# ===============================
# HISTORIAL DE CONVERSACIÓN
# ===============================
canal_historial = {}
MAX_MENSAJES = 1000

# ===============================
# MÚSICA
# ===============================
music_queue = []
audio_source = None  
current_title = None   

# ===============================
# FUNCIONES AUXILIARES
# ===============================

@bot.command()
async def lyrics(ctx, *, query: str = None):
    """Muestra la letra de la canción actual o de la buscada."""
    global current_title

    # Si no pasan nombre, usa la canción en reproducción
    song_name = query if query else current_title
    if not song_name:
        await ctx.send("❌ No hay canción reproduciéndose ni me diste un nombre.")
        return

    try:
        song = genius.search_song(song_name)
        if song and song.lyrics:
            lyrics_parts = [song.lyrics[i:i+1900] for i in range(0, len(song.lyrics), 1900)]
            for part in lyrics_parts:
                await ctx.send(f"📖 Letra de **{song.title}**:\n{part}")
        else:
            await ctx.send("❌ No encontré la letra de esa canción.")
    except Exception as e:
        await ctx.send(f"⚠️ Error al buscar la letra: {e}")
        
def play_next(ctx):
    global audio_source
    voice_client = ctx.guild.voice_client
    if not voice_client:
        return

    if music_queue:
        next_query = music_queue.pop(0)
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch',
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(next_query, download=False)
                if 'entries' in info:
                    info = info['entries'][0]
                audio_url = info.get('url')
                title = info.get('title', 'Desconocido')
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                ctx.send(f"❌ No se pudo reproducir la canción: {e}"),
                bot.loop
            )
            return

        FFMPEG_OPTIONS = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }

        audio_source = discord.FFmpegPCMAudio(
            audio_url,
            executable=r"C:\ffmpeg-2025-08-25-git-1b62f9d3ae-essentials_build\bin\ffmpeg.exe",
            **FFMPEG_OPTIONS
        )

        def after_play(error):
            if error:
                print(f"Error en after_play: {error}")
            fut = asyncio.run_coroutine_threadsafe(
                play_next_async(ctx), bot.loop
            )
            try:
                fut.result()
            except:
                pass

        voice_client.play(audio_source, after=after_play)
        asyncio.run_coroutine_threadsafe(ctx.send(f"🎵 Reproduciendo: {title}"), bot.loop)


async def play_next_async(ctx):
    play_next(ctx)

# ===============================
# EVENTOS
# ===============================
@bot.event
async def on_ready():
    print(f"✅ El bot se conectó como {bot.user}")


# ===============================
# COMANDOS EXTRA
# ===============================
@bot.command()
async def hola(ctx):
    await ctx.send("Te odio, los odio a todos chupenlo.")

@bot.command()
async def chao(ctx):
    await ctx.send("Andate a la chucha maricon, chao.")

@bot.command()
async def comoestas(ctx):
    await ctx.send("Yo nunca estoy bien.")

@bot.command()
async def chupalo(ctx):
    await ctx.send("Aahh Chupalo maricon.")

@bot.command()
async def jazmin(ctx):
    await ctx.send("Tay rica washita, mira teango los medios brasos... ")

@bot.command()
async def hans(ctx):
    await ctx.send("Basta, basta porfavor, basta, voy a explotar, dejenme porfavor.")

# ===============================
# COMANDOS DE MÚSICA
# ===============================
@bot.command()
async def play(ctx, *, query):
    global audio_source
    if ctx.author.voice is None:
        await ctx.send("Tienes que estar en un canal de voz primero.")
        return

    channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client

    if voice_client is None:
        voice_client = await channel.connect()
    elif voice_client.channel != channel:
        await voice_client.move_to(channel)

    if "open.spotify.com" in query:
        await ctx.send("❌ No puedo reproducir música de Spotify, solo de YouTube.")
        return

    if voice_client.is_playing():
        music_queue.append(query)
        await ctx.send(f"Ya estoy reproduciendo música. Agregada a la cola: {query}")
        return

    music_queue.insert(0, query)
    play_next(ctx)

@bot.command()
async def queue(ctx, *, query=None):
    if not query:
        await ctx.send("Debes escribir el nombre de la canción o artista después de !queue.")
        return
    if "open.spotify.com" in query:
        await ctx.send("❌ No puedo reproducir música de Spotify, solo de YouTube.")
        return
    music_queue.append(query)
    await ctx.send(f"✅ Canción agregada a la cola: {query}")

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭ Canción saltada.")
    elif music_queue:
        play_next(ctx)
        await ctx.send("⏭ Saltando a la siguiente canción de la cola.")
    else:
        await ctx.send("❌ No hay música reproduciéndose ni canciones en la cola.")

@bot.command()
async def stop(ctx):
    global music_queue
    music_queue.clear()

    voice_client = ctx.guild.voice_client  # Obtenemos el cliente de voz del guild
    if voice_client and voice_client.is_connected():
        voice_client.stop()
        await voice_client.disconnect()
        await ctx.send("⏹ Música detenida y bot desconectado del canal de voz.")
    else:
        await ctx.send("❌ No estoy en ningún canal de voz.")

# ===============================
# MANEJO DE ERRORES
# ===============================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Ese comando no existe, aweonao.")
    else:
        await ctx.send(f"Nopuedo hacer esa wea perdon: {error}")

# ===============================
# EJECUTAR BOT
# ===============================
bot.run(TOKEN)
