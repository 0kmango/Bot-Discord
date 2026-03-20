from discord.ext import commands
import yt_dlp
import asyncio
import lyricsgenius 
from dotenv import load_dotenv

# ===============================
# CONFIGURACIÓN
# ===============================
TOKEN = "TU_TOKEN_DISCORD_DEV"
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
@@ -32,12 +35,35 @@
# MÚSICA
# ===============================
music_queue = []
audio_source = None  # Referencia global para la canción actual
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
@@ -158,7 +184,6 @@ async def play(ctx, *, query):
await ctx.send(f"Ya estoy reproduciendo música. Agregada a la cola: {query}")
return

    # Reproducir la canción directamente y usar play_next después
music_queue.insert(0, query)
play_next(ctx)

@@ -211,4 +236,3 @@ async def on_command_error(ctx, error):
# EJECUTAR BOT
# ===============================
bot.run(TOKEN)
