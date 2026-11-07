# 🥭 Mango Bot

Bot de Discord con **música, personalidad propia y Mango AI** (asistente en
texto y por voz). Funciona en **Linux**, **Windows** y **macOS**.

Mango no es un reproductor más: es un mango melómano, con criterio y algo
de mala leche bien entendida. Sabe de música, responde rápido y no deja
que el canal se quede en silencio sin opinar.

> Estado actual: **v1.7.9** — refactor a cogs, estado por servidor, seguridad
> endurecida, Mango AI en texto y voz («oye Mango»), voz local gratis y
> respuestas por voz en **~1 s**. Instalación en
> [Linux/macOS](#linux--macos) · [Windows](#windows-powershell-o-cmd).

---

## Características

- 🎵 **Música** desde YouTube (links, playlists y búsquedas) y Spotify
  (temas, playlists y álbumes; Spotify se convierte automáticamente a
  YouTube porque su API no entrega audio).
- 🥭 **Personalidad propia**: todos los textos viven en un solo módulo
  (`mango/personality.py`), con frases variadas y tono consistente.
- 🏠 **Estado por servidor**: cada guild tiene su cola, su volumen y su
  canal de voz. Dos servidores pueden escuchar cosas distintas a la vez.
- 🔊 **Controles abiertos a quien escucha**: cualquiera que esté en el
  canal del bot puede usar `skip`, `pause`, `resume`, `stop`, `volume`,
  `remove`, `shuffle`, `loop` y `again`.
- ⌛ **Autolimpieza**: se desconecta si se queda **solo** en el canal (con
  margen de cortesía) o si se lo pides con `!bye` / hablando. La desconexión
  por inactividad está desactivada por defecto (`IDLE_TIMEOUT=0`).
- 🔐 **Seguridad primero**: tokens en `.env`, comandos privados solo para
  el dueño, menciones masivas bloqueadas y límites de cola.
- ⚡ **Sin bloqueos**: búsquedas, playlists y letras se ejecutan en hilos;
  el bot nunca congela el resto de comandos.
- 🔁 **Precarga del siguiente tema** y caché de búsquedas: menos silencio
  entre canciones y menos riesgo de bloqueo de YouTube.
- 🤖 **Mango AI en texto**: responde en un canal dedicado (`AI_CHANNEL_ID`)
  sin prefijo, con memoria por canal y comandos `!ask` / `!forget`.
- 🎙️ **Mango AI por voz**: entra al canal, escucha y se activa cuando dices
  **«oye Mango»**; transcribe, piensa y responde hablando.
- 🎚️ **Música y voz a la vez**: un mezclador PCM baja la música al 18 %
  mientras Mango habla, en lugar de cortarla.
- 🛠️ **La IA controla la música**: «oye Mango, pon algo de Daft Punk»,
  «salta esta», «qué está sonando» (function calling real).

---

## Requisitos

Funciona igual en **Linux**, **Windows 10/11** y **macOS**.

| Necesitas | Detalle |
|---|---|
| **Python 3.11 – 3.13** | Recomendado **3.12**. En 3.14 algunas dependencias de audio aún no publican wheels |
| **FFmpeg** en el `PATH` | `ffmpeg -version` debe responder |
| **Git** (opcional) | Solo para clonar el repositorio |
| Un bot de Discord | <https://discord.com/developers/applications> |

### Instalar Python y FFmpeg

| Sistema | Python | FFmpeg |
|---|---|---|
| **Windows** | `winget install Python.Python.3.12` o desde <https://www.python.org/downloads/> (marca *Add python.exe to PATH*) | `winget install Gyan.FFmpeg` (o `choco install ffmpeg`) |
| **Ubuntu / Debian** | `sudo apt install python3.12 python3.12-venv` | `sudo apt install ffmpeg` |
| **Fedora** | `sudo dnf install python3.12` | `sudo dnf install ffmpeg` |
| **Arch** | `sudo pacman -S python` | `sudo pacman -S ffmpeg` |
| **macOS** | `brew install python@3.12` | `brew install ffmpeg` |

> **Windows:** si acabas de instalar FFmpeg, **cierra y abre la terminal** para que
> tome el `PATH` nuevo. Comprueba con `ffmpeg -version` en CMD o PowerShell.

---

## Instalación

### Linux / macOS

```bash
git clone https://github.com/0kmango/Bot-Discord.git
cd Bot-Discord

python3.12 -m venv .venv
./run.sh                      # la primera vez avisa si falta algo
```

Si no tienes Git, descarga el ZIP:

```bash
curl -L https://github.com/0kmango/Bot-Discord/archive/refs/heads/main.zip -o mango.zip
unzip mango.zip && cd Bot-Discord-main
```

Si `./run.sh` no arranca (permisos o «bad interpreter»), dale permisos y repite:

```bash
chmod +x run.sh
./run.sh
```

O hazlo a mano:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env                     # rellena DISCORD_TOKEN y OWNER_IDS
python bot.py
```

### Windows (PowerShell o CMD)

```powershell
git clone https://github.com/0kmango/Bot-Discord.git
cd Bot-Discord

py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
notepad .env                  # rellena DISCORD_TOKEN y OWNER_IDS
run.bat
```

Equivalente paso a paso, si prefieres el entorno activado:

```powershell
.\.venv\Scripts\Activate.ps1  # CMD: .venv\Scripts\activate.bat
pip install -r requirements.txt
python bot.py
```

> **Si PowerShell bloquea `Activate.ps1`** («no se puede cargar porque la
> ejecución de scripts está deshabilitada»), ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> — o sáltate la activación y usa `run.bat`, que no la necesita.

> **Sin Git en Windows:** descarga el ZIP desde
> <https://github.com/0kmango/Bot-Discord> → *Code* → *Download ZIP*, descomprímelo
> y abre una terminal dentro de esa carpeta.

### Comprobar que todo está listo

```bash
./run.sh --check        # Linux / macOS
run.bat --check         # Windows
```

Revisa el `.env` variable por variable y prueba tus claves. Si algo falla, dice
exactamente qué línea mirar.

### Permisos que necesita el bot

En la URL de invitación (`OAuth2 → URL Generator`):

- Scopes: `bot`
- Permisos: `Ver canales`, `Enviar mensajes`, `Insertar enlaces`,
  `Leer historial de mensajes`, `Conectar`, `Hablar`.

Y en la pestaña **Bot** activa **MESSAGE CONTENT INTENT**
(sin eso Discord rechazará la conexión).

---

## Ejecutar el bot

`run.sh` (Linux/macOS) y `run.bat` (Windows) hacen lo mismo:

| Quiero… | Linux / macOS | Windows |
|---|---|---|
| Arrancar y ver los logs | `./run.sh` | `run.bat` |
| Dejarlo en segundo plano | `./run.sh --background` | `run.bat --background` |
| Pararlo | `./run.sh --stop` | `run.bat --stop` |
| Comprobar `.env` y APIs | `./run.sh --check` | `run.bat --check` |
| Descargar voces locales | `./run.sh --voices` | `run.bat --voices` |
| Auditar secretos antes de publicar | `./run.sh --security` | `run.bat --security` |
| Ver los logs | `tail -f mango.log` | `type mango.log` (o abrir el archivo) |

También puedes lanzarlo directamente: `python bot.py` (en Linux/macOS, si el
entorno está activado) o `py bot.py` (en Windows). Si usas el Python del sistema,
**el propio `bot.py` se relanza** con el intérprete del `.venv`.

> En **Windows**, `run.bat --background` usa `powershell` para lanzar el proceso
> oculto y guarda su PID en `mango.pid`; `run.bat --stop` lo lee y lo cierra.

---

## Configuración (`.env`)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Token del bot |
| `OWNER_IDS` | — | Tu ID de usuario (comandos privados). Si se omite se usa el dueño de la aplicación |
| `COMMAND_PREFIX` | — | Prefijo de comandos (por defecto `!`) |
| `IDLE_TIMEOUT` | — | Segundos sin actividad antes de desconectar (600) |
| `ALONE_GRACE` | — | Margen al quedarse solo en el canal (20 s) |
| `DEFAULT_VOLUME` | — | Volumen inicial 0.0–2.0 (0.5) |
| `MAX_QUEUE` | — | Canciones máximas en cola (100) |
| `MAX_PLAYLIST_TRACKS` | — | Canciones máximas por playlist (50) |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | — | Activan los links de Spotify |
| `GENIUS_TOKEN` | — | Activa `!lyrics` |
| `YTDLP_COOKIES` | — | Ruta a `cookies.txt` para vídeos restringidos |
| `AI_CHANNEL_ID` | — | Canal de texto donde Mango AI responde sin prefijo |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | Cerebro (compatible con OpenAI: **Token Harbor**, Ollama Cloud, OpenAI, Groq, Ollama local) |
| `LLM_REASONING_EFFORT` | — | `low` / `medium` / `high`: acelera modelos con razonamiento (`gpt-oss`, `nemotron`) |
| `LLM_FALLBACK_*` | — | Proveedor de respaldo: si el principal falla, Mango sigue respondiendo |
| `STT_PROVIDER` | — | `local` (faster-whisper) · `openai` · `groq` |
| `STT_API_KEY` | — | Solo si el STT no es `local` |
| `TTS_PROVIDER` / `TTS_VOICE` | — | `edge` (gratis) u `openai`, y la voz a usar |
| `WAKE_WORDS` | — | Palabras de activación separadas por comas |
| `AI_VOICE_CHANNEL_ID` | — | Si se define, Mango AI entra solo a ese canal al arrancar |
| `VOICE_ENERGY` | — | Umbral del VAD: súbelo si hay mucho ruido de fondo |
| `VOICE_SESSION_TIMEOUT` | — | `0` = cada petición necesita «oye Mango» (no responde a todo) |
| `VOICE_WAKE_MODEL` | — | Modelo rápido (`tiny`) solo para oír «oye mango» con STT local |
| `VOICE_WAKE_MAX_SECONDS` | — | Audios más largos no se transcriben si no hay conversación (6) |
| `VOICE_TRANSCRIBE_ALL` | — | `true` transcribe todo (más lento y menos privado) |
| `VOICE_SHOW_TRANSCRIPT` | — | Publicar en Discord el texto oído (por defecto `false`) |
| `VOICE_POST_REPLIES` | — | Publicar en el chat la respuesta dada por voz (por defecto `false`) |
| `TTS_RATE` | — | Velocidad de la voz (`+10%` por defecto) |
| `VOICE_DAVE` | — | `auto` (descifra E2EE con davey) u `off` (solo transporte, plan B) |

Si falta un valor obligatorio, el bot **no arranca** y explica exactamente
qué variable falta (mejor que un traceback críptico).

---

## Comandos

### 🎧 Música

| Comando | Qué hace |
|---|---|
| `!play <tema \| link>` (alias `!p`) | Reproduce o encola (YouTube, playlist, Spotify) |
| `!pause` / `!resume` | Pausa y reanuda |
| `!skip` (alias `!s`) | Salta la canción |
| `!again` | Reinicia la canción actual |
| `!stop` | Detiene y vacía la cola |
| `!queue` (alias `!q`) | Muestra la cola con duración total |
| `!nowplaying` (alias `!np`) | Qué suena ahora |
| `!remove <n>` | Quita el tema n de la cola |
| `!shuffle` | Mezcla la cola |
| `!loop <off\|track\|queue>` | Modo repetición |
| `!volume <0-200>` | Ajusta el volumen |
| `!lyrics [tema]` | Letra del tema actual o del indicado |

### 🔊 Canal de voz

| Comando | Qué hace |
|---|---|
| `!hi` (alias `!join`, `!mango ven`) | Entra a tu canal de voz **y queda escuchando «oye Mango»** |
| `!bye` (alias `!leave`) | Sale del canal y **deja de escuchar** |
| `!ping` | Latencia del bot |

#### 🎙️ Órdenes por voz (sin prefijo)

Di **«oye Mango»** (o «hola Mango») y luego:

| Dices | Qué pasa |
|---|---|
| «salta», «siguiente», «cambia», «pasa esta» | Salta al siguiente tema **al instante** |
| «para», «detente», «stop», «silencio» | Detiene y vacía la cola |
| «pausa» / «reanuda», «sigue», «continúa» | Pausa o reanuda |
| «¿qué está sonando?» | Te dice título, estado y cuántas quedan en cola |
| «pon <canción>», «reproduce <canción>» | La busca y la pone (confirma título y artista) |
| «di <texto>» | Lo dice en voz alta |
| «ven», «entra al canal» | Entra (o se cambia) a tu canal |
| «hola Mango» (sin pedir nada) | Te saluda y **no pone música** |

Los controles (salta, para, pausa, reanuda) se ejecutan **sin consultar al
modelo**: responden en ~1 s y se confirman con frases ya sintetizadas
(«¡Fuera!», «Parado.», «Pausado.»).

> **Solo música**: Mango descarta lo que no es una canción. Se apoya en la
> categoría de YouTube (`Music`), los canales de artista (`… - Topic`, VEVO), los
> metadatos musicales y la duración (45 s – 15 min). Si el mejor resultado es un
> gameplay, un trailer, un podcast, un tutorial o un directo, **prueba con los
> siguientes** y, si ninguno es música, no reproduce nada y te lo dice. Además,
> si la IA hubiera recortado el título, se usa **la petición completa** del
> usuario.

> **Sin duplicados**: si una canción ya está **sonando o en la cola**, Mango lo
> detecta (por URL del vídeo o por título normalizado, aunque venga de Spotify o
> con «(Official Video)» de más) y **no la añade otra vez**: te avisa con «ya la
> tengo puesta». En una playlist, añade las nuevas e indica cuántas omitió.

> **Búsqueda inteligente**: al pedir una canción, Mango examina los **5 primeros**
> resultados de YouTube y elige el mejor (audio del canal oficial del artista,
> duración de canción, y descarta covers/karaoke/shorts). **No hace falta decir el
> artista**: «tren al sur», «get lucky» o «despacito» encuentran la canción
> correcta. Si pides «karaoke», entonces sí prioriza el karaoke.

> **`!lyrics` sin argumentos** busca la letra de lo que está sonando y **limpia el
> título del vídeo** («(Official Music Video)», «ft. …», «Video
> Oficial»…) probando varias formas en Genius. Así funciona igual que si
> escribieras `!lyrics californication`. Las letras se guardan en caché 1 hora:
> la segunda vez es instantánea.

### 🤖 Mango AI

| Comando                  | Dónde funciona               | Qué hace                                       |
| ------------------------ | ---------------------------- | ---------------------------------------------- |
| `!mango <pregunta>`      | **Cualquier canal de texto** | Habla con Mango AI (memoria por canal)         |
| `!mango` (solo)          | Cualquier canal de texto     | Muestra este manual                            |
| `!ask <pregunta>`        | Cualquier canal de texto     | Igual que `!mango <pregunta>` (alias `!ia`)    |
| `!forget`                | Cualquier canal de texto     | Borra la memoria de ese canal                  |
| `!hi`                    | Cualquier canal de voz       | **Entra y escucha «oye Mango»** (lo principal) |
| `!bye`                   | Cualquier canal de texto     | Sale del canal y deja de escuchar              |
| `!ai join`               | Cualquier canal de texto     | Igual que `!hi`                                |
| `!ai leave`              | Cualquier canal de texto     | Igual que `!bye`                               |
| `!ai status`             | Cualquier canal de texto     | Estado de la conversación por voz              |
| `!ai sleep` / `!ai wake` | Cualquier canal de texto     | Cierra o abre la ventana de conversación       |


**La IA por voz funciona en cualquier canal de voz donde esté el bot**: entra
con `!play`, `!hi`, `!ai join`, lo invitas o lo mueves, y en todos los casos
queda escuchando «oye Mango» automáticamente. `AI_VOICE_CHANNEL_ID` solo sirve
para que entre **solo** a ese canal al arrancar.

En el canal configurado en `AI_CHANNEL_ID` además responde **sin prefijo** a
cualquier mensaje. Y `!ai leave` desactiva la escucha en ese servidor hasta que
vuelvas a activarla con `!ai join`.

### 🔒 Solo dueño (`OWNER_IDS`)

| Comando                    | Qué hace                                             |
| -------------------------- | ---------------------------------------------------- |
| `!embed [Título \|] texto` | Publica un embed con estilo Mango y borra tu mensaje |
| `!diag`                    | Diagnóstico de audio y voz (canal, DAVE, mezclador)   |
| `!test`                    | Pitido de 4 s a volumen máximo (probar el audio)     |
| `!reload <cog>`            | Recarga un módulo en caliente sin reiniciar          |
| `!sync`                    | Publica los comandos de barra en el servidor al instante |
| `!ai say <texto>`          | Prueba de voz                                        |


> Los comandos de control (`skip`, `pause`, `resume`, `stop`, `volume`,
> `remove`, `shuffle`, `loop`, `again`, `bye`) solo funcionan para miembros
> que estén **en el mismo canal de voz que el bot**. Así nadie desde otro
> canal puede cortar la música que otros están escuchando.

---

## Estructura del proyecto

```
Bot-Discord/
├── bot.py                    # punto de entrada (se relanza con el .venv)
├── run.sh                    # lanzador Linux / macOS
├── run.bat                   # lanzador Windows
├── requirements.txt
├── .env.example              # plantilla de configuración
├── mango/
│   ├── config.py             # carga y valida el entorno
│   ├── core.py               # MangoBot: cogs, servicios y estado
│   ├── state.py              # GuildPlayer y Track (estado por servidor)
│   ├── personality.py        # voz, embeds y frases de Mango
│   ├── db.py                 # memoria de conversación (SQLite, solo texto)
│   ├── logging_setup.py      # logging a consola + mango.log
│   ├── cogs/
│   │   ├── music.py          # comandos de música
│   │   ├── utility.py        # ayuda, ping y comandos privados
│   │   ├── events.py         # on_ready, voz, menciones y errores
│   │   ├── ai_chat.py        # Mango AI en texto (canal + !ask)
│   │   └── ai_voice.py       # «oye Mango»: STT → LLM → TTS
│   └── services/
│       ├── ytdlp.py          # búsquedas, playlists y streams
│       ├── spotify.py        # Spotify → YouTube
│       ├── lyrics.py         # Genius (opcional)
│       ├── llm.py            # chat + function calling
│       ├── stt.py            # reconocimiento de voz (local o API)
│       ├── tts.py            # voz sintética → PCM 48 kHz
│       ├── audio.py          # mixer música+voz, VAD y utilidades PCM
│       ├── wake.py           # detección de «oye Mango»
│       └── tools.py          # herramientas de música para la IA
└── tests/
    ├── smoke_test.py         # verifica cogs, mixer y wake word sin conexión
    └── check_apis.py         # comprueba tus claves de LLM/STT/TTS
```

### Ideas de diseño

- **`GuildPlayer`** encapsula cola, voz, volumen, loop y temporizadores. No
  hay variables globales: nada se pisa entre servidores.
- **Servicios** devuelven `Track` (dataclass) y nunca hablan con Discord.
  Se pueden testear y cambiar de proveedor sin tocar los comandos.
- **`personality.py`** centraliza el 100 % del texto visible. Cambiar el
  tono del bot es editar un archivo, no cincuenta strings dispersos.
- **Cogs** con `setup(bot)`: añadir `mango/cogs/ai_chat.py` más adelante es
  registrarlo en `INITIAL_EXTENSIONS` y nada más.

---

## Desarrollo

```bash
# Comprobar sintaxis y estilo (config en pyproject.toml)
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip install -r requirements-dev.txt
.venv/bin/ruff check .                             # Windows: .venv\Scripts\ruff check .

# Prueba de humo (no necesita token real ni conexión)
.venv/bin/python tests/smoke_test.py               # Windows: .venv\Scripts\python tests\smoke_test.py
```

Con el bot corriendo, `!reload music` recarga un cog al instante. Los logs
van a la consola y a `mango.log`.

### Comandos de barra (`/`)

Discord exige que las apps usen **comandos de barra** (o tener aprobado el
*Message Content Intent*). Mango ya los tiene:

```
/mclear [cantidad]    ← borra los últimos mensajes del canal
```

> Los comandos de barra llevan prefijo **`m`** (`/mclear`) para no chocar con
> los de otros bots del servidor.

- **Cantidad**: 1–100 (por defecto **10**).
- **Permisos**: quien lo usa necesita **Gestionar mensajes**; el bot también
  necesita ese permiso (y *Leer historial*) en el canal.
- **Aviso**: publica cuántos mensajes borró y **se borra solo a los 6 s**, así
  no queda basura en el canal. Cuenta los mensajes realmente eliminados.
- **Sin Message Content**: los comandos de barra no leen el contenido de los
  mensajes, así que funcionan incluso sin ese intent.

Los comandos se publican **globalmente** al arrancar (en el log verás
`Comandos de barra sincronizados: 1 (/mclear)`). Discord puede tardar en
mostrarlos; para que aparezcan **al instante** en tu servidor:

```
!sync        (solo el dueño)
```

> Nota: los comandos con prefijo (`!play`, `!mango`…) y la IA del canal siguen
> necesitando el *Message Content Intent*, que ya está activado en el portal.

---

## Seguridad

### Claves y secretos

- Los tokens y claves **nunca** viven en el código: se leen de `.env`, que está
  en `.gitignore` (junto con `models/`, `data/`, `*.log` y `mango.pid`).
- **Guardián de secretos**: antes de publicar, ejecuta

  ```bash
  ./run.sh --security      # Windows: run.bat --security
  ```

  Revisa todos los archivos que se subirían a git (y el historial) buscando
  patrones de claves reales (OpenAI, Groq, Token Harbor, Gemini, Discord,
  GitHub, AWS, Slack, ElevenLabs, claves privadas y `.env` pegados por error).
  Devuelve **código 1** si encuentra algo, así que sirve como paso previo a un
  `git push`:

  ```bash
  .venv/bin/python tests/check_secrets.py || exit 1
  ```

- Si alguna vez se sube una clave: **revócala en el proveedor** antes de nada
  (el historial de git es público y descargable), cámbiala en `.env` y después
  limpia el historial (`git filter-repo`).

### Comandos y permisos

- `!embed`, `!diag`, `!test`, `!reload` y `!ai say` son **solo del dueño**
  (`OWNER_IDS`). Además son invisibles en la ayuda y, si otro los intenta, se
  borra su mensaje y no se confirma que existan.
- `!reload` solo acepta cogs del proyecto (lista cerrada).
- Los comandos de música comprueban que quien manda está **en el canal de voz
  del bot**; la IA aplica la misma regla, así que desde el canal de texto no se
  puede saltar, parar ni echar al bot.
- `AllowedMentions` desactiva `@everyone` y menciones de rol: ni un embed ni un
  título de canción pueden pingar al servidor entero.

### Límites de tasa (anti-abuso)

Cada petición a la IA cuesta dinero real y cada comando consume rate limit de
Discord, así que todo tiene tope:

| Qué | Límite |
|---|---|
| `!play` | 4 usos / 15 s por usuario · 1 a la vez por servidor |
| `!skip`, `!pause`, `!resume`, `!volume`, `!remove` | 5–6 usos / 10 s |
| `!stop`, `!loop`, `!bye` | 3–4 usos / 15 s |
| `!queue`, `!np`, `!hi`, `!shuffle`, `!again`, `!lyrics` | 2–3 usos / 10–30 s |
| `!mango`, `!ask` | 2–3 usos / 10–20 s · 2 a la vez por canal |
| Canal de IA (sin prefijo) | 1 respuesta cada 4 s por usuario, máx. 6/min, y **una respuesta a la vez por canal** |
| Voz («oye Mango») | 1 petición cada 2,5 s por usuario |
| Entrada de texto | 300 caracteres (`!play`), 200 (`!lyrics`), 1500 (IA), 4000 (`!embed`) |

### Entradas del usuario

- **Enlaces**: solo se aceptan URLs de **YouTube** (`youtube.com`, `youtu.be`,
  `youtube-nocookie.com` y subdominios) y **Spotify**. La comprobación es por
  *host* con `urllib.parse`, no por substring: así `http://192.168.1.1/youtube.com`
  o `https://evil.com/?x=youtube.com` se rechazan (evita **SSRF** contra la red
  interna y los metadatos de la nube). Como segunda barrera, `stream_url`
  también valida el enlace antes de dárselo a yt-dlp.
- **Números**: `!volume` se recorta a 0–200; `!remove` valida el índice; `!loop`
  solo admite `off`/`track`/`queue`.
- **Texto**: todo lo que se envía a Discord usa `AllowedMentions.none()` y los
  mensajes largos se trocean a 1900 caracteres.
- **SQL**: la memoria de conversación usa consultas **parametrizadas** (SQLite)
  y guarda solo texto, nunca audio.
- **Subprocesos**: FFmpeg se invoca siempre con lista de argumentos y
  `shell=False`; el audio entra por `stdin`, nunca por la línea de comandos.
- **Privacidad**: el `.db` de conversaciones se crea con permisos `0600` y su
  carpeta con `0700`, para que otras cuentas de la máquina no puedan leerlo.
- **Secretos en logs**: no se registra ninguna clave; los errores muestran un
  mensaje genérico al usuario (el detalle va solo a `mango.log`).

---

## Historial de cambios

### v1.7.9 — Manual actualizado

- En **🔊 Canal de voz**, `!hi` pasa a «entra a tu canal de voz y escucha
  «oye Mango»» y `!bye` a «deja de escuchar» (antes decían «entra a tu canal de
  voz» / «sale del canal»).
- Esas dos líneas **se quitan de 🤖 Mango AI**, que deja de repetirlas.

### v1.7.8 — Controles instantáneos y sin perder el hilo

- **«salta», «para», «pausa», «reanuda», «siguiente», «cambia», «stop»… se
  ejecutan al instante**: no pasan por el modelo, así que responden en ~1 s y
  **no puede «perderse»** preguntando qué canción suena. Se confirman con frases
  precacheadas («¡Fuera!», «Parado.», «Pausado.»).
- **El reproductor recuerda la última canción** (`last_track`): si preguntas
  «¿qué está sonando?» justo cuando acaba una pista, contesta «la última fue X»
  en vez de «no hay nada».
- **`now_playing` informa también de la cola** («Quedan N en la cola»).
- **`skip` más tolerante**: funciona aunque el mezclador acabe de cerrar la pista
  (antes decía «no hay nada sonando» y el modelo improvisaba).
- Los controles **no consumen el límite de tasa** de la voz (antes una segunda
  orden en <2,5 s se ignoraba).
- Las 21 frases cortas se sintetizan **en paralelo** al arrancar
  (`Frases cortas listas en ~5,6 s`), en vez de ~20 s en serie.

### v1.7.7 — La confirmación dice solo título y artista

- **Se limpian los títulos sucios de YouTube** antes de hablar: fuera lo que va
  tras `|` (canal), fuera paréntesis/corchetes (`(Official Video)`, `[Color
  Coded_Eng]`, `(가사)`), fuera `ft. …`, comillas y símbolos (`$`).
- Detecta «Artista 'Título'» (típico en K-pop), «Artista - Título» y títulos
  sueltos.
- Ejemplo real:
  `BTS 'Like Animals' Lyrics (방탄소년단 Like Animals 가사) [Color Coded_Eng] | ShadowByYoongi`
  → «Like Animals», de BTS.
- El título original se conserva para buscar y para las letras; solo cambia lo
  que **dice en voz alta**.

### v1.7.6 — No repite canciones y arranca sin memoria

- **Barrera determinista** (además del prompt): `play_music` **solo reproduce si
  la frase del usuario pide música** (`pide_musica`). Con «hola Mango», «buenas»
  o «¿qué está sonando?» el modelo ya no puede poner (ni repetir) nada, aunque
  insista: el ejecutor lo rechaza con «Esa frase no me pide música».
- **Historial limpio al arrancar** (`CLEAR_MEMORY_ON_START=true`): se borra toda
  la memoria de conversación de `data/mango.db` en cada reinicio, así no
  «recuerda» la canción de la sesión anterior (`Historial de conversación
  borrado al arrancar (N mensajes)`).
- Nuevo `MemoryStore.clear_all()` (con `VACUUM`).

### v1.7.5 — Saluda sin poner música y espera al entrar

- **Arreglado: poner música al saludar.** Con «hola Mango» el modelo llamaba a
  `play_music` por su cuenta y repetía la última canción (parecía un bucle).
  Ahora:
  * «hola Mango», «buenas», «hey Mango» → **contesta el saludo al instante**
    (audio precacheado) y **no pone nada**. Ni siquiera llama al modelo.
  * El modelo tiene prohibido poner música por iniciativa propia o repetir la
    canción anterior (en la persona y en la descripción de la herramienta).
- **Al entrar al canal no hace nada**: ni música ni voz. Se queda escuchando y
  espera instrucciones.
- Saludos precacheados al arrancar, junto a las interjecciones
  (`Frases cortas listas (4 interjecciones · 4 saludos)`).

### v1.7.4 — Responde en ~1 s y conversación más fluida

- **Interjección instantánea**: al arrancar se sintetizan «¡Marchando!»,
  «¡Vamos con eso!»… y Mango dice una **en cuanto terminas la frase**, antes de
  buscar nada. Después solo añade ««Título», de Artista» (sin repetir la
  apertura).
- **Modelo más rápido**: `openai/gpt-oss-20b` (medido 0,77–0,90 s frente a
  1,12–1,83 s del 120b), con las mismas herramientas.
- **Empieza a hablar en ≈1,0 s** (antes 2,5–3,3 s) y la canción suena en ≈2,4 s.
- VAD de 400 ms (equilibrio entre no cortar el final y responder rápido).

### v1.7.3 — Mejor escucha, voz más cálida y sin incongruencias

- **Margen de escucha más amplio** para no cortar el final de la frase (donde
  va el artista y por eso ponía «una cualquiera»): `VOICE_SILENCE_MS` 320 →
  **500 ms**, pre-roll 12 → **16 frames** (320 ms) y ventana de conversación
  25 → **30 s**.
- **Voz nueva y más agradable**: `es-PE-AlexNeural` (masculina, cálida, 118 Hz
  de tono medio) y ritmo más pausado (`TTS_RATE=+0%`). Alternativas documentadas
  en `.env.example` (`es-CR-JuanNeural`, `es-US-AlonsoNeural`, `es-MX-JorgeNeural`…).
- **Voz más alta**: `TTS_GAIN` 1.5 → **1.8** (+80 % de nivel con limitador suave).
- **Arreglada la incongruencia del habla**: cuando la canción se añadía y la
  herramienta ya había confirmado por voz, el bot decía además «esa se me
  perdió». Ahora, si la herramienta respondió (`handled_reply`), no se añade
  ningún aviso contradictorio.

### v1.7.2 — Nuevo manual (`!help` / `!mango`)

- **Embed de ayuda reemplazado** por el texto definido por el dueño: título
  «🥭 Mango · manual de bolsillo», descripción nueva y cinco secciones
  (🎧 Música, 🔊 Canal de voz, 🤖 Mango AI, ⌨️ Comandos de barra, 💡 Trucos).
- La sección de música **muestra los alias** (`!play / !p`, `!skip / !s`,
  `!queue / !q`), se quita `!ping` del bloque de voz y en Mango AI se documentan
  `!hi` / `!bye` en lugar de `!ai join` / `!ai leave` / `!ai status`.
- Ya **no hay sección «Solo dueño»** (el manual es igual para todos).

### v1.7.1 — El comando pasa a llamarse `/mclear`

- **Renombrado `/clear` → `/mclear`** para no chocar con el comando de otros bots
  del servidor. Convención: los comandos de barra de Mango llevan prefijo `m`.
- El antiguo `/clear` **se elimina** de Discord al sincronizar (se reemplaza la
  lista completa); para que se aplique al instante usa `!sync` y recarga Discord
  con `Ctrl+R`.

### v1.7.0 — Comandos de barra (`/mclear`)

- **Nuevo `/mclear [cantidad]`**: borra los últimos mensajes del canal (1–100,
  por defecto 10), avisa de cuántos eliminó y **el aviso se borra solo a los 6 s**.
- Requiere **Gestionar mensajes** para quien lo usa, y el bot lo necesita en el
  canal.
- **Sincronización automática** del árbol de comandos al arrancar
  (`Comandos de barra sincronizados: 1 (/mclear)`) y `!sync` (dueño) para forzarla
  al instante en un servidor.
- Nuevo cog `mango/cogs/slash.py`. Los comandos de barra no dependen del
  *Message Content Intent*.

### v1.6.3 — La música no baja cuando hablas tú

- **Corregido**: al hablar el usuario, la música **mantiene el volumen**. Antes
  bajaba (auto-ducking) para romper el eco del micrófono.
- En su lugar, la detección de voz ahora es **adaptativa al ruido de fondo**:
  toma el nivel mínimo de los últimos 2 s y exige superarlo (~5 dB). El eco
  constante de la música deja de contar como voz **sin tocar el volumen**, y tu
  voz —muy por encima— se sigue detectando.
- **La música solo baja al 12 % mientras habla Mango**, que es justo lo que
  permite distinguir su voz de la canción.
- `!diag` muestra ahora `Voz: música baja solo cuando habla Mango · umbral…`.

### v1.6.2 — Entrar al canal pidiéndoselo

- **`!mango ven`** (y `entra al canal`, `únete`, `conéctate`, `métete al canal`)
  entra al canal de voz, exactamente igual que `!hi` (reutiliza el mismo camino:
  conecta, cambia de canal si hace falta y arranca la escucha).
- **También por voz**: nueva herramienta `join_voice`, así «oye Mango, ven»
  funciona sin prefijo.
- Falsos positivos evitados: «ven a ver esto» o «¿vienes?» no conectan nada.

### v1.6.1 — `!mango di …` (hablar en voz alta)

- **`!mango di <texto>`** hace que Mango lo diga por el canal de voz, igual que
  `!ai say`. Acepta `di:`, `decir`, `repite`, `anuncia`, `say` y texto entre
  comillas para que sea literal.
- **También por voz**: nueva herramienta `say_text` para la IA, así
  «oye Mango, di que empieza el directo» funciona sin prefijo.
- **`di algo divertido` / `di un chiste`** → lo inventa la IA y lo dice (no lee
  literalmente «algo divertido»).
- `dime …` sigue siendo una pregunta normal, no una orden de hablar.
- Permisos: solo el dueño por defecto; `VOICE_SAY_PUBLIC=true` lo abre a quien
  esté escuchando en el canal. Límite de 300 caracteres.

### v1.6.0 — Conversación fluida y confirmación de locutor

- **Reconoce mejor**: STT por API pasa a `whisper-large-v3` (misma latencia,
  ~0,5 s, mejor transcripción), umbrales de voz más sensibles
  (`VOICE_ENERGY=0.010`, `VOICE_ENERGY_MUSIC=0.025`), más preroll (12 frames) y
  AGC hasta ×12 para voces flojas.
- **«Oye Mango» sin petición ya no interrumpe**: se queda callado y sigue con lo
  que estaba en vez de contestar «¿sí?».
- **Si no entiende la tarea, lo dice por voz**: «No te pillé. ¿Me lo repites?»
  (audio de 1,8 s o más sin petición, o respuesta vacía del modelo).
- **Confirmación estilo locutor de radio**: dice **título y artista**
  («¡Marchando! *Tren Al Sur*, de *Los Prisioneros*»), con variantes y también
  para la cola.
- **Conversación fluida con filtro de intención**: ventana de 25 s y
  `VOICE_CONVERSATION_FILTER` para responder solo a órdenes y preguntas,
  ignorando la charla entre otras personas (nuevo módulo `services/intent.py`).

### v1.5.4 — Voz más alta

- **La voz de Mango suena más**: se sube **×1,5 con limitador suave** (sin
  distorsión ni desbordes). Medido: edge pasa de pico 0,53 a 0,79; Piper de
  0,71 a 0,99. Y la música se aparta al **12 %** mientras él habla.
- Nuevo ajuste `TTS_GAIN` (1.0 = sin tocar, hasta 3.0) y `!diag` muestra
  `voz=x1.5`.

### v1.5.3 — Voz mientras suena música

- **Arreglado: no contestaba mientras reproducía música.** El micrófono captaba
  la música, el detector veía energía constante y la frase nunca se cerraba.
  Ahora la música se **aparta (ducking) al detectar voz**, se usa un **umbral
  propio con música** (`VOICE_ENERGY_MUSIC`) y las **frases largas se analizan
  por su final** en vez de descartarse.
- El ducking también hace que se **note al instante** que Mango te ha oído.
- `!diag` muestra el estado del auto-ducking y los dos umbrales.
- `VOICE_SILENCE_MS` por defecto a 320 ms (respuesta más rápida).

> ⚠️ El *auto-ducking* al hablar el usuario se **revirtió en la v1.6.3**: ahora la
> música solo baja cuando habla Mango. Lo que queda es el umbral adaptativo al
> ruido de fondo.

### v1.5.2 — Auditoría de seguridad

- **SSRF corregido (crítico)**: los enlaces se validan por *host* con
  `urllib.parse` en lugar de buscar substrings. Antes,
  `!play http://192.168.1.1/youtube.com` (o la IP de metadatos de la nube)
  pasaba el filtro y el bot hacía peticiones a la red interna. Ahora solo se
  aceptan YouTube y Spotify, con una segunda comprobación en `stream_url`.
- **Límite de tasa del canal de IA**: antes, escribir en `#mango-ai` disparaba
  una llamada al modelo por mensaje, sin ningún tope. Ahora: 1 cada 4 s por
  usuario, máx. 6/min y una respuesta simultánea por canal.
- **Cooldowns en todos los comandos públicos** (`skip`, `stop`, `pause`,
  `resume`, `again`, `volume`, `remove`, `shuffle`, `loop`, `hi`, `bye`,
  `queue`, `np`, `!mango`, `!forget`) y **2,5 s entre peticiones de voz**.
- **Escalada de privilegios cerrada**: las herramientas de la IA (`skip`,
  `stop`, `leave_voice`) ahora exigen estar en el canal de voz del bot, igual
  que los comandos de texto.
- **Privacidad**: el `.db` de conversaciones pasa a `0600` (carpeta `0700`).
- **Entradas acotadas**: 300 caracteres en `!play`, 200 en `!lyrics`, 2000 en
  la IA; `!reload` solo acepta cogs del proyecto.
- **Guardián de secretos** (`tests/check_secrets.py` + `./run.sh --security`):
  detecta claves reales en el código y en el historial de git, y avisa si se
  rastrean `.env`, `models/`, `data/` o logs.

### v1.5.1 — Windows y macOS

- **Instalación y arranque en Windows**: nuevo `run.bat` con `--background`,
  `--stop`, `--check` y `--voices`; `bot.py` detecta `.venv\Scripts\python.exe`
  y se relanza con él (en Windows como proceso hijo, no con `execv`).
- **README reescrito para las tres plataformas**: requisitos e instalación de
  Python/FFmpeg por sistema, pasos separados para Linux/macOS y Windows,
  ejecución equivalente (`run.sh` ↔ `run.bat`), servicio con systemd en Linux
  y Programador de tareas/NSSM en Windows, y tabla de problemas típicos de Windows.
- **Sin bucle de relanzamiento**: si el `.venv` existe pero está roto, se avisa
  una vez en lugar de reintentar indefinidamente.

### v1.5.0 — Confirmación hablada y voz más rápida

- **La canción se confirma hablando**: al pedir música por voz, Mango dice
  «Voy con *título*» en lugar de repetirlo como texto, así confirmas de oído lo
  que ha entendido sin que quede nada en el chat.
- **Respuesta ~2× más rápida** (de ~6,3 s a **2,4–3,1 s**): búsqueda de YouTube
  lanzada **en paralelo** al modelo y confirmación **pre-sintetizada** que suena
  por trozos en cuanto hay el primero.
- **Voz de respaldo local**: si edge-tts (u otro proveedor de red) falla, Mango
  sigue hablando con Piper `es_MX-ald-medium`; nunca se queda mudo.
- **Reconocimiento de canciones más robusto**: el modelo corrige nombres mal
  transcritos («Pomp Get Lucky» → «Daft Punk Get Lucky») y, si una búsqueda no
  devuelve nada, se reintenta con variantes de la consulta.
- `VOICE_SILENCE_MS` por defecto a 380 ms (responde antes al dejar de hablar).

### v1.4.1 — IA en cualquier canal

- **Voz en cualquier canal**: el bot se conecta siempre con `VoiceRecvClient` y
  arma la escucha de «oye Mango» en **cualquier** canal de voz al que entre
  (`!play`, `!hi`, `!ai join`, invitación o mover). Si lo mueven de canal, se
  rearma solo.
- **`!mango <pregunta>` en cualquier canal de texto** (y `!mango` solo muestra
  el manual). `!ask` sigue siendo alias. `AI_CHANNEL_ID` pasa a ser opcional
  (solo para el modo sin prefijo).
- **`!ai leave`** desactiva la escucha de ese servidor y `!ai join` la reactiva.
- El aviso de privacidad se publica una vez por sesión en el canal por defecto
  (canal de IA, último canal usado o canal general).

### v1.4.0 — Mango AI (texto y voz)

- **Mango AI en texto**: canal dedicado (`AI_CHANNEL_ID`) sin prefijo, `!ask`,
  `!forget`, memoria en SQLite y personalidad propia (`MANGO_AI_PERSONA`).
- **Mango AI por voz**: se activa al decir **«oye Mango»** con
  `discord-ext-voice-recv`, VAD por energía, Whisper (local o API) y TTS
  (edge-tts u OpenAI). Entra solo con `AI_VOICE_CHANNEL_ID` o con `!ai join`.
- **Mixer de audio**: la música ya no se corta cuando Mango habla; baja al 18 %
  y se mezcla en un único `AudioSource` de 48 kHz estéreo.
- **Function calling**: la IA puede reproducir, saltar, parar, consultar la cola
  y buscar letras por lenguaje natural.
- **Privacidad**: no se guarda audio, solo texto; aviso de consentimiento al
  unirse y `!forget` para borrar la memoria.
- **Nuevo verificador** `tests/check_apis.py` para validar LLM/STT/TTS.

### v1.3.0 — Refactor y personalidad

- **Adiós al monolito**: `Mango_bot_discord.py` (773 líneas) se divide en
  `mango/` con cogs, estado y servicios.
- **Estado por servidor** (`GuildPlayer`): se elimina el bug que mezclaba
  colas y voz entre guilds.
- **Seguridad**: tokens a `.env`, `!embed` privado y oculto, `AllowedMentions`
  sin `@everyone`, cooldowns, límites de cola y de playlist, borrado del
  mensaje de invocación en comandos privados.
- **Personalidad Mango**: nuevo módulo `personality.py` con paleta, embeds y
  frases variadas; se sustituyen los mensajes poco profesionales.
- **Bugs corregidos**:
  - llamadas bloqueantes a Spotify/Genius dentro del event loop,
  - tarea de desconexión huérfana que se duplicaba,
  - `after_playing` que bloqueaba el hilo de audio y se comía excepciones,
  - playlists de Spotify truncadas a 100 temas (ahora paginan),
  - un mensaje por canción al importar playlists (ahora un resumen),
  - `current_voice` desincronizado de `guild.voice_client`.
- **Nuevo**: `!volume`, `!nowplaying`, `!remove`, `!shuffle`, `!loop`,
  `!again`, `!reload`, precarga del siguiente tema y caché de búsquedas.
- **Logging real** a consola y a `mango.log`, con `on_command_error`
  centralizado.
- **Prueba de humo** (`tests/smoke_test.py`) que valida cogs y comandos sin
  conectarse a Discord.


---

## Mango AI: cómo funciona la voz

```
🎤 Hablas en el canal
   ↓  VoiceRecvClient entrega PCM 48 kHz estéreo (20 ms por frame)
   ↓  VAD por energía: agrupa la frase y corta a los 700 ms de silencio
   ↓  STT (faster-whisper local o API)
   ↓  ¿Contiene «oye Mango»?  ──no──▶  se descarta (y no se guarda nada)
   ↓  sí (o ventana de conversación abierta)
   ↓  LLM con memoria + herramientas de música
   ↓  TTS por frases → PCM 48 kHz
   ↓  Mezclador: música al 18 % + voz → mismo canal de voz
```

Detalles que importan:

- **Escucha en cualquier canal**: el bot se conecta siempre con
  `VoiceRecvClient`, así que **en cuanto entra a un canal de voz** (por
  `!play`, `!hi`, `!ai join`, invitación o porque lo muevan) queda escuchando.
- **Solo responde si le hablas a él**: hay que empezar con **«oye Mango»**
  (o «hola Mango», «hey Mango», «escucha Mango») **en cada petición**. Al terminar
  la acción vuelve a esperar la palabra clave, así **no contesta a lo que hablas
  con otras personas**. Con `VOICE_SESSION_TIMEOUT>0` deja una ventana de
  conversación para seguir hablando sin repetirla (por defecto `0` = modo estricto).
- **Turnos y eco**: mientras Mango habla se ignora el audio entrante para que no
  se responda a sí mismo.
- **Memoria separada**: la voz guarda contexto por usuario
  (`voice:<servidor>:<usuario>`) y el texto por canal.
- **`!ai sleep`** cierra la conversación sin dejar de escuchar la palabra clave.
- **`!ai leave`** apaga la escucha en ese servidor (útil si alguien no quiere
  ser escuchado); se reactiva con `!ai join`.
- **`AI_VOICE_CHANNEL_ID`** es opcional: solo hace que el bot entre **solo** a
  ese canal al arrancar, para tenerlo siempre a mano.

### Privacidad (importante)

- El bot **no guarda audio**: los frames se procesan y se descartan.
- Solo se guarda el texto de la conversación, y `!forget` lo borra.
- Al unirse, el bot publica un aviso de consentimiento. Si alguien no quiere ser
  escuchado, `!ai leave` lo saca del canal.
- Grabar a terceros sin consentimiento puede ser ilegal (RGPD en la UE).

### Comprobar tus claves

```bash
.venv/bin/python tests/check_apis.py
```

Verifica LLM, STT y TTS uno por uno, sin mostrar las claves. Si algo falla, dice
exactamente qué variable revisar y qué endpoints son válidos para OpenAI, Groq u
Ollama.

### Voces más humanas (más naturales que edge-tts)

Se cambia el proveedor en el `.env` y listo:

| `TTS_PROVIDER` | Calidad | Dónde se saca | Coste |
|---|---|---|---|
| `edge` (actual) | buena, algo robótica | viene incluida | gratis |
| `openai` | **muy natural** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) · modelo `gpt-4o-mini-tts` | ~15 $/millón de caracteres (≈3 s de voz = 20 caracteres) |
| `elevenlabs` | **la más humana** (prosodia y emoción) | [elevenlabs.io](https://elevenlabs.io) → *API Keys* | 10 000 caracteres/mes gratis; luego ~5 $/mes |
| `gemini` | muy natural | [aistudio.google.com](https://aistudio.google.com/apikey) | capa gratuita generosa |
| Azure Speech / Cartesia / Deepgram Aura | naturales | portales propios | según plan (aún sin adaptador) |

Ejemplo con ElevenLabs (la más humana y rápida con `flash`):

```env
TTS_PROVIDER=elevenlabs
TTS_API_KEY=sk_...
TTS_VOICE=EXAVITQu4vr4xnSDxMaL   # Sarah (multilingüe); o el ID de tu voz clonada
TTS_MODEL=eleven_flash_v2_5      # baja latencia
```

Ejemplo con OpenAI:

```env
TTS_PROVIDER=openai
TTS_API_KEY=sk-...
TTS_VOICE=nova
TTS_MODEL=gpt-4o-mini-tts
```

Ejemplo con Gemini:

```env
TTS_PROVIDER=gemini
TTS_API_KEY=AIza...
TTS_VOICE=Kore
TTS_MODEL=gemini-2.5-flash-preview-tts
```

**Sin coste y 100 % local**: Kokoro-82M, Piper o XTTS-v2 (necesitan instalación aparte
y, en el caso de XTTS, GPU). Si algún día quieres esa vía, dímelo y añado el adaptador.

### Voces locales: gratis, offline y (casi siempre) las más rápidas

Instalación en dos pasos (el primero es solo la primera vez):

```bash
.venv/bin/pip install -r requirements-voices.txt   # onnxruntime + Piper + Kokoro
./run.sh --voices                                  # descarga los modelos en models/
```

En **Windows**:

```powershell
.\.venv\Scripts\pip install -r requirements-voices.txt
run.bat --voices
```

> Requiere ~700 MB de disco en `models/` (ignorada por git) y funciona sin
> conexión una vez descargados. El primer `--voices` tarda un rato.

Y en el `.env`:

```env
TTS_PROVIDER=piper    # o kokoro / local
```

Medido en este equipo (misma frase, CPU normal):

| Voz | Acento / tipo | Tiempo por frase | Coste |
|---|---|---|---|
| **`es_MX-claude-high`** ← por defecto | **México · femenina** | **0,20 s** ⚡ | gratis, offline |
| `es_MX-ald-medium` | México · masculina | 0,21 s | gratis, offline |
| `es_ES-davefx-medium` | España · masculina | 0,24 s | gratis, offline |
| `es_AR-daniela-high` | Argentina · femenina | 8,85 s ❌ | gratis, offline |
| Kokoro-82M (`ef_dora`) | neutro · femenina | 1,95 s | gratis, offline |
| edge-tts (`es-PE-AlexNeural`) ← **en uso** | Perú · masculina, cálida | 1,55 s | gratis, online |
| ElevenLabs / OpenAI | el que elijas | 0,3-0,8 s | de pago |

La voz por defecto es la **mexicana femenina de Piper** (`es_MX-claude-high`): la más
rápida de todas (0,20 s), calidad «high» y tono cálido. Con ella el total hasta oír a
Mango queda en **~2,2 s** (antes 3,3 s con edge-tts).

Voces en español que puedes descargar:

```bash
./run.sh --voices                       # la de por defecto (México femenina)
./run.sh --voices piper-es-mx           # México masculina (ald)
./run.sh --voices piper-es-ar           # Argentina femenina (daniela, lenta en CPU)
./run.sh --voices piper-es-es           # España masculina (davefx)
./run.sh --voices piper-es-es-sharvard  # España femenina (sharvard)
./run.sh --voices kokoro                # Kokoro (ef_dora, em_alex, em_santa)
```

En **Windows** cambia `./run.sh` por `run.bat`, por ejemplo
`run.bat --voices piper-es-mx`.

Para usar otra voz ya descargada, en el `.env` (funciona igual en los dos sistemas;
las rutas con `/` las entiende Python en Windows):

```env
TTS_PROVIDER=piper
TTS_VOICE=es_MX-ald-medium
TTS_MODEL=models/es_MX-ald-medium.onnx
```

También existe **XTTS-v2** (clonación de voz): necesita PyTorch (~2 GB) y, para ir
fluido, GPU. Si algún día lo quieres, se añade como proveedor `xtts`.

> Los modelos se guardan en `models/` (ignorada por git): Piper ~60 MB, Kokoro ~340 MB.

### Latencia y privacidad de la voz

Medido en esta máquina (Groq `gpt-oss-20b` + `whisper-large-v3` + edge-tts):

| Etapa | Tiempo |
|---|---|
| Espera de silencio del VAD | 0,40 s |
| STT (Groq `whisper-large-v3`) | 0,62 s |
| **«¡Marchando!» (audio precacheado)** | **0,00 s** |
| LLM hasta la primera frase (`gpt-oss-20b`) | 0,80 s |
| Búsqueda en YouTube (en paralelo al modelo) | 0 s añadidos |
| Título + artista (voz pre-sintetizada) | 0 s añadidos |
| **Mango empieza a hablar** | **≈ 1,0 s** |
| Canción sonando | ≈ 2,3-2,6 s |

Antes tardaba ~6,3 s en contestar. Lo que cambió:

* **Interjección precacheada**: al arrancar se sintetizan «¡Marchando!»,
  «¡Vamos con eso!»… y se dice una **al instante** en cuanto terminas la frase,
  sin esperar a la búsqueda. Después solo se añade ««Título», de Artista».
* **Modelo más rápido**: `openai/gpt-oss-20b` (0,8 s) en vez de 120b (1,2-1,8 s);
  llama igual de bien a las herramientas.
* **Búsqueda especulativa**: se busca en YouTube *a la vez* que piensa el modelo.
* **Confirmación pre-sintetizada** que suena por trozos en cuanto hay el primero.
* VAD 400 ms y `TTS_RATE=+0%` (voz pausada pero sin demora perceptible).

#### Voz de respaldo

Si el proveedor principal es de red (`edge`, `elevenlabs`, `openai`, `gemini`) y
alguna vez falla —edge-tts devuelve de vez en cuando «No audio was received»—,
Mango **sigue hablando con la voz local** (Piper `es_MX-ald-medium`) en vez de
quedarse mudo. No hay que configurar nada: se activa sola si los modelos están
descargados (`./run.sh --voices` en Linux/macOS, `run.bat --voices` en Windows).

#### La canción se confirma hablando

Cuando pides música **por voz**, Mango dice el título que va a poner
(«Voy con Los Prisioneros - Tren Al Sur») en lugar de repetirlo como texto. Así
confirmas de oído lo que ha entendido y no hace falta publicar nada en el chat.

#### Si el reconocimiento oye mal el nombre

Whisper no conoce los nombres de grupos, así que «Avalon de Suicideboys» puede
llegar como «Avelan» o «Daft Punk» como «Dazpump». Para eso hay tres redes:

1. El **modelo corrige** la transcripción cuando reconoce la canción (la
   descripción de la herramienta se lo pide expresamente).
2. Si la búsqueda no devuelve **nada**, se reintenta con **variantes**
   («Dazpump get lucky» → «get lucky»).
3. La elección final se **puntúa**: coincidencia de palabras, canal oficial,
   duración de canción, y se descarta todo lo que no sea música.

Sobre el chat: **lo que hablas por voz no deja rastro en ningún canal** — ni la
transcripción ni la respuesta (solo se registra en `mango.log`). Las respuestas en
el chat salen únicamente cuando usas comandos de texto (`!mango`, canal de IA).
Se puede reactivar con `VOICE_POST_REPLIES=true`.

Sobre la privacidad: **fuera de conversación solo se analizan frases cortas**
(≤ `VOICE_WAKE_MAX_SECONDS`); la música o una charla larga no se transcriben.
Nada se publica en Discord salvo que pongas `VOICE_SHOW_TRANSCRIPT=true`, y en
el log solo se registra cuando de verdad te está escuchando (`→ ACTIVA`).

### Cuándo se desconecta el bot

Se desconecta **solo** en estos tres casos:

1. Si se queda **solo** en el canal (con `ALONE_GRACE` de margen, 20 s por defecto).
2. Si se lo pides con **`!bye`** (o `!ai leave`).
3. Si se lo pides **hablando** («oye Mango, sal del canal») o por **`!mango sal del canal de voz`**.

`IDLE_TIMEOUT=0` (por defecto) desactiva la desconexión por inactividad: antes
salía a los 10 minutos aunque estuvieras ahí hablando con él.

### Volumen de la voz frente a la música

La voz de Mango no siempre llega al mismo nivel según el proveedor (medido:
**edge ≈ 0,53 de pico**, **Piper ≈ 0,71**), así que sonaba baja frente a la
música. Ahora:

* **Mientras habla Mango**, la música se aparta al **12 %** (y vuelve sola). Al
  hablar el usuario **no se toca el volumen**: la canción sigue igual.
* La voz se **sube ×1,5 con un limitador suave**: gana un 50 % de nivel sin
  distorsionar y sin desbordar nunca (edge pasa de pico 0,53 a 0,79; Piper de
  0,71 a 0,99).

```env
TTS_GAIN=1.8      # 1.0 = sin tocar · 1.8 = +80 % · máximo 3.0
```

Si aún te sabe a poco, súbelo a `2.0` o `2.2` (el limitador evita que reviente).
Y si quieres la música aún más discreta mientras habla, baja el volumen con
`!volume 40` mientras dure la charla.

Comprobación en `!diag`:

```
Mezclador: frames=250 · volumen=0.50 · voz=x1.5 · música=True · hablando=False
```

### Entrar al canal de voz

Tres formas, todas equivalentes (conecta **y queda escuchando «oye Mango»**):

```
!hi                      ← el comando clásico
!mango ven               ← pidiéndoselo por texto
!mango entra al canal
!mango únete / conéctate / métete al canal
```

Y **por voz**, sin prefijo:

```
«oye Mango, ven»            → entra (o se cambia) a tu canal
«oye Mango, entra al canal» → lo mismo
```

Detalles:

| Caso | Qué hace |
|---|---|
| Ya está en tu canal | «Ya estoy en *canal*, te escucho.» |
| Está en **otro** canal y no hay música sonando | Se cambia al tuyo |
| Está sonando música en otro canal | Avisa en vez de cortar la sesión |
| No estás en ningún canal de voz | Te pide que entres primero |
| `ven a ver esto`, `¿vienes?` | No son órdenes de entrar: las trata como charla/pregunta |

`!hi` es el mismo camino, así que da igual cómo lo pidas: el comportamiento, el
embed y el arranque de la escucha son idénticos.

### Hacer que hable en voz alta

Igual que `!ai say`, pero desde `!mango` (y también por voz):

```
!mango di hola a todos          → dice «hola a todos» por el canal de voz
!mango di: buenos días          → lo mismo (con dos puntos)
!mango di "texto exacto, con comas"
!mango decir feliz cumpleaños
!mango repite el estribillo
!mango anuncia que empezamos
```

Y **por voz**, sin prefijo:

```
«oye Mango, di que empieza el directo»   → lo dice en voz alta
«oye Mango, di algo divertido»           → se lo inventa él y lo dice
```

Reglas:

| Petición | Qué hace |
|---|---|
| `di <texto>` | Dice **ese texto tal cual** (máx. 300 caracteres) |
| `di algo …`, `di un chiste`, `di una frase …` | Lo **crea la IA** y luego lo dice |
| Con comillas (`"…"`, `«…»`) | Siempre literal |
| `dime …` | **No** es esto: es una pregunta normal, se responde charlando |

**Permisos**: por defecto solo el **dueño** puede hacerle hablar
(`VOICE_SAY_PUBLIC=false`), porque la voz del bot es su identidad. Si quieres que
cualquiera que esté escuchando pueda pedirlo:

```env
VOICE_SAY_PUBLIC=true    # solo afecta a quien esté en el canal de voz
```

`!ai say <texto>` sigue funcionando igual (comando oculto del dueño).

### Cómo entiende lo que dices

1. **Reconocimiento**: Whisper `large-v3` en Groq (medido: **0,5 s**, lo mismo que
   `turbo` pero con mejor transcripción) con prompt de vocabulario musical. Si un
   nombre sale mal transcrito («Pomp» por «Punk», «Avelan» por «Avalon»), el
   modelo lo corrige antes de buscar.
2. **Margen de escucha amplio**: se espera **400 ms** de silencio antes de cerrar
   la frase (y 320 ms de pre-roll para no perder el arranque), así no se corta el
   final —que es justo donde va el artista— y la búsqueda acierta más.
3. **Palabra clave + petición en la misma frase**: «oye Mango, pon tren al sur»
   se detecta de una vez (comparador difuso: tolera «oy mango», «hola mango», «o
   la mango»).
4. **Al entrar no hace nada**: no pone música ni habla. Se queda escuchando y
   espera instrucciones.
5. **Saludo → contesta al instante**: «hola Mango», «buenas» o «hey Mango»
   reciben un saludo precacheado al momento **y no ponen música** (no es una
   petición).
6. **Solo la palabra clave → no interrumpe**: si dices «oye Mango» y nada más, se
   queda callado y sigue con lo que estaba (la música no se corta).
7. **Oye algo pero no lo entiende → te avisa por voz**: «No te pillé. ¿Me lo
   repites?» (cuando el audio dura 1,8 s o más y no salió petición, o el modelo
   no devolvió nada). **Nunca** después de confirmar una canción: si la
   herramienta ya respondió, no se añade ningún aviso contradictorio.
8. **Confirmación de locutor de radio**: antes de sonar dice el **título y el
   artista**:
   > «¡Marchando! *Tren Al Sur*, de *Los Prisioneros*.»
   > «Al aire: *Get Lucky*, cortesía de *Daft Punk*.»

### Conversación fluida (sin meterse donde no le llaman)

Tras activarlo, la conversación queda abierta **25 s** (`VOICE_SESSION_TIMEOUT`)
para que puedas seguir hablando sin repetir «oye Mango». Durante esa ventana el
bot oye todo lo que se dice en el canal, pero **solo responde si la frase va
dirigida a él** (`VOICE_CONVERSATION_FILTER`):

| Se responde | Se ignora |
|---|---|
| «oye Mango…», «mango…» | «esa canción está buenísima» |
| órdenes: «pon…», «para…», «sube el volumen» | «vamos a jugar una partida» |
| preguntas: «¿qué está sonando?», «¿cuál es mejor?» | «jaja qué risa» |
| respuestas cortas: «sí», «no», «vale» | «mi hermana llega mañana» |

Y la ventana **no se renueva** con la charla ajena: solo con lo que va dirigido a
él, así que si hablas con tus amigos se cierra sola a los 25 s.

```env
VOICE_SESSION_TIMEOUT=25        # 0 = modo estricto (siempre «oye Mango»)
VOICE_CONVERSATION_FILTER=true  # ignora la charla que no va con él
```

### Hablar con Mango mientras suena música

El caso más frágil: **el micrófono del usuario capta la música de los altavoces**
(eco), el detector de voz ve energía constante y la frase nunca se cierra, así
que Mango parecía sordo mientras reproducía. Se resuelve **sin tocar el volumen
de la canción**:

1. **Detección adaptativa al ruido de fondo**: el detector toma el nivel mínimo
   de los últimos 2 s y exige superarlo (~5 dB por encima). Si la música entra
   por el micro, ese ruido pasa a ser la referencia y deja de contar como voz;
   tu voz, que está muy por encima, sí entra.
2. **Umbral propio con música** (`VOICE_ENERGY_MUSIC`): con música sonando se
   pide algo más de energía, para no confundir el eco suave con habla.
3. **Frases largas no se tiran**: si el audio supera `VOICE_WAKE_MAX_SECONDS` y
   hay música, se analiza **su final** (donde acabas de hablar) en vez de
   descartarlo.

**El volumen de la música no cambia cuando hablas tú.** Solo baja (al 12 %)
**mientras habla Mango**, justo para distinguir su voz de la canción.

```
!diag
```
```
Voz: música baja solo cuando habla Mango · umbral voz=0.010 · con música=0.025
```

| Si... | Ajusta |
|---|---|
| No te oye con música | baja `VOICE_ENERGY_MUSIC` (p. ej. `0.02`) |
| Se activa solo con la música | súbelo (`0.04`) |
| Quieres respuesta aún más rápida | baja `VOICE_SILENCE_MS` (320) o usa `TTS_PROVIDER=piper` (~0,2 s de voz) |

> Con **auriculares** no hay eco y todo va aún más fino: es la mejor opción si
> tienes la música alta.

### Ajustar la escucha

- Si **no detecta** cuando hablas: baja `VOICE_ENERGY` (p. ej. `0.008`).
- Si **se activa con ruido**: súbelo (`0.02`) y sube `VOICE_MIN_SPEECH_MS`.
- Si **corta frases**: sube `VOICE_SILENCE_MS` (p. ej. `900`).
- Primer arranque con `STT_PROVIDER=local`: la primera transcripción tarda más
  porque descarga el modelo de Whisper (~500 MB para `small`).

### Si no se oye la música o no te responde por voz

1. **Usa `!diag`** (solo tú): muestra canal, permisos, mezclador, pico de audio,
   frames recibidos y el último texto que oyó. Con eso se ve el problema en 5 s.
2. **¿Estoy silenciado o ensordecido?** Clic derecho sobre el bot en el canal de
   voz → si tiene «Silenciar» o «Ensordecer» activo, la música no suena y no oye.
   El bot ahora avisa solo cuando detecta esto.
3. **Música**: hay que pedirla con `!play`; el bot no pone música al entrar.
   Ojo: algunas canciones empiezan con 2-4 s de silencio (p. ej. el videoclip
   oficial de «Instant Crush»). Si `!diag` marca `pico=0.4` y sigues sin oír
   nada, el problema es del lado de Discord (mute/permisos), no del bot.
4. **Permisos del canal**: el rol del bot necesita `Conectar` y `Hablar`, y que
   no haya una denegación por canal.
5. **`!test`** (solo dueño): pitido de 4 s a volumen máximo, sin YouTube. Si no lo
   oyes pero `!diag` muestra `pico=0.8`, el audio sale del bot y se pierde en tu
   cliente: sube el **volumen del usuario bot** (clic derecho sobre él en la lista
   de miembros → Volumen 100 %), comprueba que **no estás ensordecido/a** y que la
   **salida de audio** de Discord es la correcta. Y asegúrate de tener **una sola
   instancia** (`./run.sh --stop` en Linux/macOS, `run.bat --stop` en Windows):
   dos sesiones del mismo bot se pelean y el
   servidor puede enviar el audio a la sesión equivocada.
6. **Voz**: mira `mango.log`; cada frase que oye aparece como
   `[voz] <usuario> dijo '...' → ACTIVA / ignorado`. Si no aparece ninguna línea
   al hablar, mira `escuchando` y `frames` en `!diag`.
7. Si el bot oye pero no siempre reacciona, baja `VOICE_ENERGY` (p. ej. `0.008`).
8. **DAVE/E2EE (obligatorio en Discord)**: la voz va cifrada de extremo a
   extremo y `discord-ext-voice-recv` no lo descifra por sí solo; Mango lo
   parchea con `davey`. Clave: **la sesión DAVE solo se activa con más de una
   persona en el canal** (con el bot solo verás `lista=False`, y es normal).
   Con gente dentro, `!diag` debe mostrar:
   `DAVE/E2EE: protocolo=1 · lista=True · cifra_salida=True`.
   Mientras `cifra_salida=False`, Discord descarta el audio del bot (no se oye la
   música) y la voz entrante no se puede descifrar. `VOICE_DAVE=off` **no sirve**
   donde E2EE es obligatorio: Discord cierra la conexión con el código 4017 (el
   bot lo detecta y reactiva DAVE automáticamente).

### Problemas típicos del LLM

| Síntoma | Causa y solución |
|---|---|
| `429 · You have no credits remaining` | La cuenta de OpenAI no tiene saldo. Usa Ollama Cloud (gratis) u Ollama local |
| `402 · not included in your free usage` (Ollama) | Ese modelo de la nube es de pago: usa `gpt-oss:120b`, `gemma4:31b` o `nemotron-3-super` |
| Respuestas vacías | Modelo con razonamiento sin límite: pon `LLM_REASONING_EFFORT=low` |
| `404 model not found` | El nombre del modelo no existe en ese proveedor |
| En Token Harbor: `model not allowed` | Tu plan no incluye ese modelo; usa uno de la lista de `/v1/models` (los `:free` nunca fallan) |

### Problemas típicos en Windows

| Síntoma | Causa y solución |
|---|---|
| `'python' no se reconoce como un comando…` | Python no está en el `PATH`. Reinstálalo marcando **Add python.exe to PATH**, o usa el lanzador `py` (`py -3.12 -m venv .venv`) |
| `'ffmpeg' no se reconoce como un comando…` | FFmpeg no está en el `PATH`: `winget install Gyan.FFmpeg` y **reabre** la terminal. Sin FFmpeg no hay música ni voz |
| `[WinError 2] El sistema no puede encontrar el archivo especificado` al reproducir | Es lo mismo: FFmpeg no está disponible. Comprueba `ffmpeg -version` |
| `.\run.bat` «se cierra solo» al hacer doble clic | Se cierra al terminar; abre **CMD/PowerShell en la carpeta** y ejecuta `run.bat` para ver el mensaje. Si hay error, usa `cmd /k run.bat` |
| PowerShell: *no se puede cargar `Activate.ps1` porque la ejecución de scripts está deshabilitada* | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (una vez). O no actives nada y usa `run.bat` |
| `ModuleNotFoundError: No module named 'discord'` | Lo lanzaste con el Python del sistema: usa `run.bat` o `.venv\Scripts\python bot.py` (`bot.py` se relanza solo con el `.venv`) |
| `py` no existe | Tu Python vino de la Microsoft Store: usa `python -m venv .venv` |
| SmartScreen / antivirus bloquea `run.bat` | *Más información* → *Ejecutar de todas formas* (el archivo es texto plano, puedes abrirlo con el Bloc de notas) |
| `Access is denied` al parar con `run.bat --stop` | Ejecuta la terminal **como administrador**, o cierra la ventana donde corre el bot con `Ctrl+C` |
| Rutas con acentos o espacios (`C:\Users\José\Mis Documentos`) | Funcionan, pero si algo falla mueve la carpeta a `C:\Bot-Discord` para descartar |

### Mantener el bot encendido

El bot es un proceso normal. **Si cierras la terminal se apaga**; por eso lo
cómodo es lanzarlo en segundo plano.

**Linux / macOS**

```bash
./run.sh --background    # lo deja corriendo en segundo plano
./run.sh --stop          # para el bot
tail -f mango.log        # ver qué está haciendo
```

Otras opciones en Linux/macOS:

```bash
# sesión persistente (puedes cerrar la terminal)
screen -S mango ./run.sh    # volver con: screen -r mango
```

Como servicio del sistema, crea `/etc/systemd/system/mango-bot.service`
(ajusta rutas y usuario):

```ini
[Unit]
Description=Mango Bot
After=network-online.target

[Service]
WorkingDirectory=/home/TU_USUARIO/Bot-Discord
ExecStart=/home/TU_USUARIO/Bot-Discord/.venv/bin/python bot.py
Restart=always
RestartSec=5
User=mango

[Install]
WantedBy=multi-user.target
```

Luego: `sudo systemctl enable --now mango-bot`

**Windows**

```bat
run.bat --background     :: lo deja oculto en segundo plano
run.bat --stop           :: para el bot
type mango.log           :: ver qué está haciendo
```

Para que arranque **solo al encender el PC**, usa el *Programador de tareas*
(`taskschd.msc` → *Crear tarea*):

- **Desencadenador**: *Al iniciar sesión*
- **Acción**: *Iniciar un programa* → `C:\ruta\a\Bot-Discord\run.bat`
- **Iniciar en**: `C:\ruta\a\Bot-Discord` (importante, para que encuentre el `.venv`)
- **Configuración**: marca *Si la tarea falla, reiniciarla cada 1 minuto*

Alternativa rápida con [NSSM](https://nssm.cc/) (lo instala como servicio):

```bat
nssm install MangoBot C:\ruta\a\Bot-Discord\.venv\Scripts\python.exe bot.py
nssm set MangoBot AppDirectory C:\ruta\a\Bot-Discord
nssm start MangoBot
```

