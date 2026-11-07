"""Mango Bot: bot de música con personalidad propia.

Estructura:
    mango.config      -> carga y validación de variables de entorno
    mango.core        -> subclase de Bot y registro de cogs
    mango.state       -> estado por servidor (GuildPlayer, Track)
    mango.personality -> voz, estilo y embeds de Mango
    mango.services    -> integraciones externas (YouTube, Spotify, Genius)
    mango.cogs        -> comandos agrupados por dominio
"""

__version__ = "1.7.9"
