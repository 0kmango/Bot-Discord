"""Servicios externos de Mango.

Nota: este ``__init__`` no importa los submódulos a propósito. Si lo hiciera,
``mango.state`` → ``mango.services.audio`` → ``mango.services`` provocaría un
import circular con ``ytdlp``/``spotify`` (que importan ``Track`` de ``state``).
Importa siempre desde el módulo concreto::

    from mango.services.ytdlp import YTDLPService
    from mango.services.audio import MixerSource
"""
