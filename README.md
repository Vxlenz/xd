# NovaDeck

Centro de automatización personal para Windows 10/11, Python 3.11+.

## Descargar

- **[Descargar el código fuente en ZIP](https://github.com/Vxlenz/xd/archive/refs/heads/main.zip)**.
- **[Versiones y descargas para Windows](https://github.com/Vxlenz/xd/releases)**.
- **[Estado de la compilación en GitHub Actions](https://github.com/Vxlenz/xd/actions/workflows/windows.yml)**.

En una versión publicada, descarga `NovaDeck-windows-x64.zip`, usa **Extraer todo**
y abre `NovaDeck/NovaDeck.exe`. Conserva `_internal` junto al ejecutable. Esta
distribución no necesita Python. También se ofrece un ZIP de fuentes y sus sumas
SHA-256. La descarga de código fuente está disponible aunque no haya una versión
Windows publicada todavía.

Las etiquetas `v*` generan una versión descargable cuando la compilación y las
pruebas de Windows terminan correctamente. Si no aparece ningún ZIP de Windows,
consulta el estado de Actions; no se publica un ejecutable si falla la validación.

## Funciones

- Perfiles con nombre, icono, color y lista ordenada de acciones.
- Editor con arrastrar para reordenar, botones de subir/bajar y prueba individual.
- Steam mediante `steam://rungameid/<AppID>`, aplicaciones `.exe` con argumentos
  separados y enlaces HTTP/HTTPS en el navegador predeterminado.
- Ejecución en segundo plano, resultado por acción y continuación tras errores.
- CRUD e importación/exportación desde la pantalla de tarjetas; idiomas ES/EN.
- Modelos estrictos y almacenamiento JSON atómico con backup.
- Spotify con OAuth PKCE, mini reproductor y buscador de playlists propias.
- Horarios semanales, disparadores de inicio de sesión y avisos cancelables.
- Bandeja con perfiles y pausa del programador; inicio con Windows e icono de la app.
- Volumen maestro por dispositivo y No molestar, con restauración y recuperación tras fallos.
- Voz offline ES/EN con Vosk, pulsar para hablar, escucha con «nova» y feedback visual.

La aplicación y el empaquetado están implementados. El entorno de desarrollo es
Linux: las ventanas se prueban con pantalla virtual y las integraciones Windows con
mocks. La descarga y carga de los dos modelos Vosk se han comprobado con archivos
oficiales reales. La validación de las integraciones nativas y del ejecutable Windows
debe hacerse en Windows 10/11; no se ha realizado desde este entorno.

## Instalar y ejecutar

Necesitas Windows 10/11 y Python 3.11 o superior de 64 bits, con Tcl/Tk
(incluido en la instalación oficial de Python). En PowerShell, desde la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

La interfaz empieza en español. El selector superior permite cambiar a inglés y
guarda la elección para el siguiente inicio. Los diálogos ya abiertos conservan su
idioma hasta volver a abrirlos; el idioma del reconocimiento de voz se elige aparte.

Crea un perfil con **Crear perfil**, añade acciones y guarda. No se importa ni se
activa ningún ejemplo automáticamente. Para abrir varias pestañas, añade una acción
URL por pestaña. Cada línea del campo de argumentos representa un argumento completo;
no añadas comillas alrededor de una ruta con espacios. Los ejecutables se lanzan sin
consola de comandos y desde su propia carpeta. Deben existir al ejecutar la acción.
Steam debe estar instalado y registrado como controlador de sus enlaces.

La espera se aplica **antes de cada acción**, también la primera. **Probar** ejecuta
solo la acción elegida inmediatamente, sin aplicar esa espera ni guardar los cambios
del editor. **Detener acciones pendientes** cancela las esperas y lo que aún no se
ha iniciado; no cierra juegos o aplicaciones ya abiertos. Solo se permite una ejecución
a la vez. Editar un perfil durante una ejecución no modifica esa ejecución.

«Solicitud enviada» confirma que el sistema aceptó abrir el destino; no garantiza
que el juego o la aplicación hayan terminado de iniciar. Una acción fallida nunca
impide intentar la siguiente. Los errores se muestran traducidos, sin trazas ni argumentos.

## Si NovaDeck no abre

Si no se puede escribir en la carpeta de datos, NovaDeck muestra un aviso para
revisar los permisos y el espacio libre. La carpeta habitual es `%APPDATA%/NovaDeck`.
Comprueba que tu usuario tenga acceso y vuelve a abrir la aplicación.

Si falla la carga de la interfaz o de sus dependencias, se muestra un mensaje
traducido sin rutas privadas, argumentos ni trazas. En Windows el aviso usa un
diálogo del sistema, incluso si CustomTkinter no puede cargarse. Conserva toda la
carpeta de la distribución; desde fuentes, vuelve a instalar `requirements.txt`.
Los errores inesperados dejan solo su tipo en el log. Estos avisos respetan el
idioma guardado cuando se puede leer; si los ajustes están dañados, usan español
y conservan el archivo para que puedas revisarlo.

## Encontrar un Steam AppID

Abre la página del juego en la tienda de Steam y copia su enlace (desde el cliente,
**Compartir → Copiar enlace**, o desde el navegador). El número después de `/app/`
es su AppID: en `https://store.steampowered.com/app/570/Dota_2/`, es **570**.
También puedes consultar el archivo `steamapps/appmanifest_<AppID>.acf` del juego
instalado, sin editarlo. En la acción Steam escribe solo el número y un nombre visible.
NovaDeck envía `steam://rungameid/<AppID>`; Steam gestiona la instalación, permisos,
actualizaciones e inicio del juego. No se espera a que termine de cargar.

## Conectar Spotify

1. Inicia sesión en [Spotify for Developers](https://developer.spotify.com/dashboard).
2. Crea una aplicación y selecciona **Web API**. Spotify puede imponer requisitos
   de cuenta, acceso y modo de desarrollo; consulta las condiciones de su panel.
3. En los ajustes de esa aplicación, registra exactamente esta Redirect URI:
   `http://127.0.0.1:8888/callback`.
4. Copia su **Client ID**. En NovaDeck, abre **Ajustes**, pégalo y pulsa
   **Conectar / volver a autorizar**. No copies ni uses el Client Secret.
5. Autoriza en el navegador y vuelve a NovaDeck para comprobar el resultado.
   Si el modo desarrollo lo requiere, incluye la cuenta en los usuarios autorizados.

El callback escucha solo en `127.0.0.1:8888`, valida un estado aleatorio por conexión
y caduca a los dos minutos. Puedes cancelar desde Ajustes. PKCE usa SHA-256 y un
verificador nuevo en cada intento. Ninguna llamada del reproductor abre un diálogo
de autorización ni pide datos por consola: si hace falta consentimiento, vuelve a Ajustes.

Permisos solicitados: `user-read-playback-state`, `user-modify-playback-state`,
`user-read-currently-playing`, `playlist-read-private`, `user-library-read`.
Los tokens se guardan en `%APPDATA%/NovaDeck/.spotify_cache`, asociados al Client ID,
y se renuevan automáticamente. La caché es local y **no está cifrada**; protégela como
una credencial y no la compartas. NovaDeck no registra tokens, códigos OAuth ni
respuestas de autenticación. El Client ID público se guarda aparte en `settings.json`.

### Reproducción y playlists

Añade una acción Spotify con una URI o enlace de playlist, álbum, canción o artista.
También puedes elegir una playlist propia desde el editor, sin copiar enlaces. El
buscador admite nombres con o sin tildes. **Mis playlists** en la ventana principal
permite elegir una para reproducirla inmediatamente; desde el editor solo rellena la URI.

El perfil comprueba Spotify Desktop en Windows y lo abre con `spotify:` si hace falta.
Espera hasta 20 segundos por un dispositivo, con esperas crecientes. Prioriza el
ordenador cuyo nombre coincide con el equipo local; si el proceso ya estaba abierto,
usa como alternativa un ordenador activo y después el primer ordenador disponible.
Si no había proceso local, espera un dispositivo nuevo o que coincida con el nombre
local para evitar transferir a otro PC existente. Un dispositivo restringido no se usa.
Después transfiere la reproducción, aplica volumen/aleatorio y reproduce. Las canciones
usan una lista de URIs; álbumes, playlists y artistas usan un contexto.

La barra inferior muestra canción y artista y permite reproducir/pausar, avanzar,
retroceder y cambiar el volumen de Spotify (no el volumen maestro de Windows).
Se actualiza cada cinco segundos; **Actualizar** solicita una lectura inmediata.
Las operaciones van por hilos de trabajo, sin bloquear la interfaz. Los cambios del
slider se agrupan tras 400 ms para evitar saturar la API.

La reproducción por API requiere **Spotify Premium** y una cuenta autorizada para la
app. Un 403 también puede indicar restricciones de acceso de Spotify. Si no hay
dispositivo, falta autorización, hay un error de red o la API rechaza la reproducción,
NovaDeck muestra el motivo y abre la URI para reproducción manual. Esto **no** se
cuenta como éxito de reproducción por API. Las demás acciones del perfil continúan.
Un 429 respeta `Retry-After` y bloquea nuevas peticiones hasta que venza ese plazo,
sin reintentos ocultos. Un 401 intenta renovar el token una vez antes de pedir reconexión.

Spotify se valida con API simulada, callback HTTP local y ventanas reales en pantalla
virtual. No se ha comprobado la reproducción con una cuenta real ni Spotify Desktop
en Windows. Spotify usa `accounts.spotify.com` y `api.spotify.com`; el enlace de
respaldo puede abrir `open.spotify.com`. Deben ser accesibles desde tu equipo.

## Horarios, sesión y bandeja

En el editor de perfiles puedes añadir varios horarios, cada uno con hora `HH:MM`
y sus días de la semana. Todos usan la zona horaria local del equipo y sus cambios
de horario de verano. Cada tarjeta muestra la próxima ejecución. Si no añades horarios
ni activas el disparador de sesión, el perfil es solo manual. Los perfiles siempre
se pueden ejecutar manualmente, aunque también tengan horarios.

**Iniciar con Windows**, en Ajustes, registra exclusivamente el valor `NovaDeck` de
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; no requiere administrador
ni cambia otros programas de inicio. Inicia con `--minimized --login`, usando
`pythonw.exe` cuando está disponible o el ejecutable empaquetado en una distribución.
Mantén la instalación y su entorno virtual en la misma ubicación; si los mueves,
desactiva y vuelve a activar el interruptor para actualizar la ruta.

Los perfiles con **Al iniciar sesión en Windows** se ofrecen una vez cuando NovaDeck
se inicia con `--login`. Abrir `python app.py` manualmente no activa esos perfiles.
El interruptor global debe estar activo para que Windows inicie la app automáticamente.

Cada ejecución automática muestra un aviso de escritorio de NovaDeck, visible incluso
con la ventana principal en la bandeja, con **cinco segundos para Cancelar**. Es un
aviso propio de CustomTkinter, no una notificación del centro de actividades de Windows.
Si se perdió un horario por suspensión y lleva menos de diez minutos de retraso,
primero pregunta si quieres ejecutarlo y después muestra la cuenta atrás. Se toleran
dos segundos de retraso normal del planificador. Los horarios de diez minutos o más
se descartan. Si el equipo se suspende durante la cuenta atrás, se pide confirmación
al volver, en vez de ejecutar inmediatamente. Las fechas futuras tras un ajuste del
reloj esperan a su hora.

Las ejecuciones automáticas se ponen en cola detrás de la lista de acciones en curso;
no se solapan. Activar el siguiente perfil termina y restaura el anterior, aunque
el juego o la aplicación que abrió continúen ejecutándose.
Editar o eliminar un perfil invalida los avisos pendientes de esa versión. Pausar el
programador cancela sus avisos y pendientes; reanudar programa desde ese momento,
sin recuperar lo omitido durante una pausa intencionada. Los horarios necesitan que
NovaDeck siga abierto: la app no despierta el PC ni recupera horarios mientras estuvo
cerrada. Usa una sola instancia para evitar que dos procesos repitan un horario.

En Windows, cerrar con **X** oculta la ventana cuando la bandeja está disponible.
Desde su menú puedes abrir NovaDeck, activar perfiles, pausar/reanudar el programador
y **Salir**. También hay un botón **Salir** en la ventana. Si la bandeja falla o estás
en Linux, la ventana permanece accesible; X no deja la aplicación oculta sin forma
de volver. La opción de inicio con Windows aparece deshabilitada fuera de Windows.

El icono PNG/ICO se incluye en `novadeck/assets`; puede reproducirse con
`python tools/generate_icon.py` (Pillow). La bandeja y el registro están verificados
con mocks; aún necesitan validación nativa en Windows 10/11.

## Volumen maestro y No molestar

Añade una acción **Sistema** para cambiar el volumen maestro (0–100), activar o
quitar No molestar, o ambas cosas. Un perfil **permanece activo** después de abrir
sus aplicaciones: termina al pulsar **Terminar perfil**, activar otro perfil o usar
**Salir**. X solo lo oculta a la bandeja cuando está disponible. No se detecta
automáticamente el cierre de juegos o procesos para decidir el fin del perfil.

**Detener acciones pendientes** cancela lo que no se ha iniciado y deja el perfil
activo. **Terminar perfil** cancela los pendientes, espera a que termine la operación
en curso y restaura sus ajustes. Ninguna de estas opciones cierra aplicaciones ajenas.
La restauración y el control de audio van por hilos de trabajo, con inicialización
COM en el hilo que usa pycaw; la ventana sigue respondiendo.

El volumen se aplica al dispositivo de salida predeterminado en el momento de la
acción y no cambia su estado de silencio. Si **Restaurar volumen original** está
activado, se conserva el nivel exacto anterior, sin redondearlo a un porcentaje.
Si un perfil contiene varias acciones de volumen para el mismo dispositivo, basta
que una solicite restauración para recuperar el valor anterior a la primera acción
de ese perfil. Una acción posterior no cancela esa obligación. Si todas eligen
**No**, se conserva el volumen configurado incluso al terminar o salir.

Cada salida afectada se identifica por su ID. Si cambias de altavoces a auriculares,
se pueden restaurar ambos dispositivos; nunca se aplica el volumen antiguo a otro
solo porque se haya convertido en el predeterminado. Si el dispositivo original
está desconectado, se conserva la recuperación y puedes reconectarlo y reintentar.
La restauración de No molestar se intenta aunque falle la del volumen.

No molestar modifica exclusivamente el DWORD
`HKCU\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\NOC_GLOBAL_SETTING_TOASTS_ENABLED`
(0 desactiva los avisos, 1 los permite), y comunica el cambio a Windows. Al terminar
**siempre** restaura el valor original; si no existía, elimina solo ese valor, sin
borrar la clave ni otros ajustes. Un formato de registro inesperado se deja intacto.

Esta preferencia no equivale al control completo de **Focus Assist / Concentración**
y no garantiza silenciar todas las aplicaciones. Algunas versiones de Windows,
políticas del equipo y aplicaciones con avisos propios pueden ignorarla o tardar en
aplicarla. No se modifican políticas globales ni se cambia Focus Assist por otras vías.
Los avisos propios de NovaDeck con botón Cancelar continúan siendo visibles.

### Recuperación y salida

Antes de cada primer cambio reversible se guarda atómicamente el estado original en
`%APPDATA%/NovaDeck/system_recovery.json`. Si no se puede guardar, ese cambio no se
aplica. El archivo contiene solo datos de restauración, nunca credenciales. Una salida
normal restaura antes de cerrar; después de un cierre inesperado, el siguiente inicio
restaura antes de permitir nuevos perfiles o ejecuciones programadas. Una prueba
individual de una acción Sistema restaura al acabar, incluso si esa acción desactiva
la restauración del volumen. Termina el perfil activo antes de probar acciones aisladas.

Cada ajuste restaurado se retira del archivo de recuperación; los que fallen se
conservan. **Reintentar restauración** vuelve a intentarlo. Si salir falla, se pregunta
si deseas salir conservando el archivo para el próximo inicio. Un segundo intento de
salida vuelve a cargar los pendientes. Activar otro perfil se bloquea si no se pudieron
restaurar los anteriores. Un error de una acción no impide ejecutar las demás acciones
del mismo perfil.

Un bloqueo del sistema operativo en `.system-session.lock` evita que otra instancia
restaure un perfil que sigue activo. El bloqueo se libera al salir y también cuando
el proceso termina forzosamente. El pequeño archivo de bloqueo puede permanecer en
la carpeta; su existencia por sí sola no significa que esté ocupado. Si la recuperación
JSON está dañada o no se puede leer, se conserva y no se aplican nuevos cambios del
sistema: revisa los valores originales antes de repararlo, sin borrarlo a ciegas.

Las pruebas verifican las llamadas a pycaw y al registro con mocks y simulan además
un proceso real que termina sin ejecutar limpieza. El funcionamiento del volumen y
la efectividad de No molestar siguen pendientes de comprobación nativa en Windows.

## Comandos de voz sin conexión

En **Ajustes → Voz sin conexión**, selecciona el idioma, busca el micrófono y guarda
los ajustes con **Activar comandos de voz**. Está desactivado de forma predeterminada.
El idioma del reconocimiento es independiente del idioma de la interfaz. Se guarda
el nombre del dispositivo y su sistema de audio, no un índice que cambie al reiniciar.
Si el dispositivo desaparece o hay nombres duplicados, vuelve a seleccionarlo o usa
**Predeterminado del sistema**.

La primera activación descarga el modelo pequeño del idioma elegido desde
`https://alphacephei.com/vosk/models/` y lo instala en `%APPDATA%/NovaDeck/models`:

- Español: `vosk-model-small-es-0.42`.
- Inglés: `vosk-model-small-en-us-0.15`.

**Preparar modelos de español e inglés** descarga ambos para usarlos después sin
conexión. Las descargas mantienen la verificación TLS, validan el ZIP y sus CRC,
limitan tamaños y rechazan rutas fuera del modelo. Se instalan primero en una carpeta
temporal y solo se activan al terminar; no se sobrescriben carpetas existentes inválidas.
Si un modelo está dañado, conserva o mueve esa carpeta antes de descargarlo de nuevo.
Una vez instalado, Vosk se carga por ruta local y no consulta servicios de reconocimiento.

Mantén **Ctrl+Alt+Espacio** o el botón **Mantén para hablar** mientras dices una orden;
suelta para ejecutarla. El atajo se puede cambiar a Ctrl/Alt/Shift más una letra,
un número, F1–F12 o `space`. El atajo global usa pynput en Windows y funciona también
en la bandeja; si no se puede registrar, queda disponible el botón.
Cambiar o desactivar el atajo descarta los eventos pendientes del registro anterior
y libera el pulsador, incluso si el cierre del registro nativo falla.
Con la voz activada el micrófono puede permanecer abierto, pero fuera del pulsador se descartan los bloques
sin reconocerlos. Al desactivar voz se cierra la captura.

**Escucha continua con «nova»** es opcional. En ese modo debes comenzar **cada frase**
con la palabra completa «nova», por ejemplo «nova activa perfil jugar» o «nova pause».
Decir solo «nova» no habilita la siguiente frase. No se ejecutan conversaciones sin
esa palabra inicial. Los modelos pequeños pueden equivocarse: usa nombres de perfil
bien diferenciados. La coincidencia aproximada solo se aplica a perfiles existentes;
si hay varios candidatos similares, no se ejecuta ninguno. La voz nunca crea rutas,
URLs ni comandos de consola a partir de lo escuchado.

| Español | English | Efecto |
| --- | --- | --- |
| activa perfil jugar | start gaming profile | Activa el perfil indicado. |
| pausa | pause music | Pausa Spotify, sin alternar a reproducción. |
| reanuda la música | resume music | Reanuda Spotify. |
| siguiente canción | next track | Avanza en Spotify. |
| canción anterior | previous track | Retrocede en Spotify. |
| sube el volumen | volume up | Sube el volumen maestro 10 puntos, con máximo 100. |
| baja el volumen | volume down | Baja el volumen maestro 10 puntos, con mínimo 0. |
| activa no molestar | enable do not disturb | Desactiva los avisos mediante la preferencia de Windows. |
| desactiva no molestar | disable do not disturb | Vuelve a permitir los avisos mientras siga activo el perfil. |
| detén todo | stop everything | Termina el perfil, restaura sus ajustes, pausa el programador e intenta pausar Spotify. |

Los cambios de volumen maestro y No molestar se añaden al perfil activo sin volver a
abrir sus aplicaciones. Si no hay ninguno, se crea una sesión temporal **Control por
voz**, que puedes terminar para restaurar esos cambios. «Detén todo» no mata procesos
ni cierra juegos. Si Spotify falla al pausar, el aviso muestra ese error aunque el
perfil se haya terminado correctamente. Una operación ocupada se informa sin acumular
órdenes para ejecutarlas más tarde por sorpresa.

La barra inferior muestra el estado de voz y un pequeño panel flotante muestra lo
escuchado y el resultado. La captura, reconocimiento y descarga van por hilos de trabajo;
solo la interfaz accede a widgets. El audio vive en una cola acotada en memoria, nunca
se guarda ni se envía por red. Tampoco se guardan transcripciones en los logs. Si la
captura pierde datos, se detiene en vez de ejecutar una frase incompleta. Los controles
de Spotify siguen necesitando Internet, pero no transmiten audio del micrófono.

En Linux, sounddevice necesita PortAudio (`libportaudio2` en Debian/Ubuntu); en Windows
su rueda incluye las bibliotecas de audio. Las pruebas automatizadas usan audio
simulado y ventanas reales con Xvfb. También se verificaron la descarga oficial,
la carga de los dos modelos reales, el procesamiento de silencio y la transcripción
correcta de la muestra de voz inglesa del repositorio oficial de Vosk. El
entorno en la nube carece de micrófono físico; faltan las órdenes habladas reales
y el atajo global en Windows. Si no aparece ningún micrófono, revisa los permisos
de acceso al micrófono para aplicaciones de escritorio en la configuración de Windows.

## Datos y backups

Los perfiles se guardan en `%APPDATA%/NovaDeck/profiles.json`; el backup del estado
anterior es `profiles.json.bak`. Un archivo inválido produce un error y no se sustituye
automáticamente por un documento vacío. La primera escritura no tiene estado anterior
que respaldar. El almacenamiento está pensado para una instancia de la aplicación;
no coordina escrituras entre procesos. Importar un ID existente actualiza ese perfil,
previa confirmación, y nunca ejecuta el contenido importado.

`profiles.example.json` contiene un documento completo con dos perfiles; no es un
archivo de importación individual. Para probarlos, con NovaDeck cerrado y sin perfiles
propios, puedes copiarlo a `%APPDATA%/NovaDeck/profiles.json`. Si ya tienes datos,
conserva el archivo y crea los ejemplos desde el editor. No se ejecutan por copiarlos.
Los logs rotativos se guardan en
`%APPDATA%/NovaDeck/logs`; no registran rutas, argumentos ni credenciales.

## Crear la distribución Windows

Ejecuta desde una terminal de Windows con Python de 64 bits en el `PATH`:

```bat
build.bat
```

El script crea su propio `.venv-build`, instala `requirements-build.txt`, comprueba
las dependencias, ejecuta las pruebas y genera una distribución **one-folder** con
PyInstaller. Si falla un paso, se detiene con error. Las versiones de PyInstaller
y sus hooks están fijadas; las dependencias de la aplicación usan los rangos de
`requirements.txt`, por lo que no es una compilación idéntica byte a byte.

El resultado es `dist\NovaDeck\NovaDeck.exe`. Distribuye **toda** la carpeta
`dist\NovaDeck`, incluido `_internal`, README y los perfiles de ejemplo. No copies
solo el `.exe`. No requiere Python instalado en el equipo de destino. Incluye el
icono, traducciones, recursos de CustomTkinter, datos horarios y bibliotecas de Vosk,
PortAudio, bandeja, atajo global y volumen. Los modelos de voz se descargan por usuario
al primer uso; las credenciales y datos del usuario no se empaquetan.

Al terminar, `tools/check_build.py` ejecuta el binario desde una carpeta temporal y
comprueba que funciona sin el árbol de fuentes: importa dependencias, valida iconos,
traducciones y zona horaria, y abre/cierra una ventana de prueba. No accede a perfiles,
tokens, micrófono ni ajustes de Windows, ni contacta con servicios externos. Puedes
repetir esa comprobación desde una sesión gráfica:

```powershell
.\.venv-build\Scripts\python.exe tools\check_build.py dist\NovaDeck\NovaDeck.exe
```

El workflow `.github/workflows/windows.yml` hace esos pasos en Windows con Python 3.11
y conserva ZIP descargables como artefactos. Las etiquetas `v*` también los publican
en GitHub Releases después de pasar las comprobaciones. Consulta Actions para conocer
el resultado de cada ejecución. PyInstaller debe compilar en el sistema de destino:
la compilación de comprobación realizada localmente es Linux y no produce un `.exe`
para Windows.

Antes de distribuir en Windows, comprueba en una sesión de usuario: conectar Spotify
y reproducir con Premium; abrir un juego y un `.exe`; bandeja e inicio con Windows;
horario cancelado y recuperación tras suspensión; volumen/No molestar y restauración
al terminar/salir; recuperación después de un cierre forzado; micrófono, atajo global
y ambos idiomas. Estas comprobaciones requieren dispositivos y servicios reales.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas de núcleo, ejecutor, Spotify y lanzadores usan mocks: no abren navegadores
ni juegos ni contactan con Spotify. Las pruebas del callback usan temporalmente el
puerto local 8888; debe estar libre.
Las de interfaz ejercitan ventanas reales de CustomTkinter y requieren pantalla.
En Linux sin escritorio se omiten explícitamente; con Xvfb instalado:

```bash
xvfb-run -a .venv/bin/python -m pytest -q
```

Se comprueban fallos parciales, cancelación durante esperas, ejecución concurrente,
validación de destinos, separación de argumentos, CRUD, backups, flujo del editor,
PKCE, estado OAuth, renovación, 403, 429, dispositivos y controles del reproductor,
horarios, cambios de zona/DST, suspensión, cancelación, bandeja, registro de inicio,
restauración del sistema, fallos parciales, bloqueo entre instancias y recuperación
tras terminar abruptamente un proceso, parser bilingüe puro, palabra de activación,
pulsar/soltar, captura interrumpida, instalación segura de modelos y ajustes de voz.
La interfaz requiere una sesión gráfica. Linux sirve para estas pruebas, pero los
lanzamientos reales de Steam y `.exe` requieren Windows. Si no existe APPDATA, el
almacenamiento de desarrollo usa `~/.local/share/NovaDeck`.

## English

NovaDeck is a Windows 10/11 profile launcher with ordered Steam/app/URL actions,
Spotify PKCE playback and mini player, weekly/login triggers, tray/startup controls,
restorable master volume and toast preferences, and offline Spanish/English voice
commands. Spanish is the default UI language; the English switch is saved. Use Python
3.11+ (64-bit), install `requirements.txt`, and run `python app.py` in a desktop session.

Create a Spotify developer app with redirect `http://127.0.0.1:8888/callback`, then
enter its Client ID in Settings. No Client Secret is needed. API playback requires
Premium and appropriate app/account access. The local token cache is not encrypted.
For Steam, use the numeric ID following `/app/` in the game's store URL.

Voice is off by default. Enable it in Settings and download the small official Vosk
models once; recognition then runs locally. Hold Ctrl+Alt+Space, or opt into continuous
listening and begin each utterance with “nova”. Audio and transcripts are never saved
or uploaded. Generic volume commands change Windows master volume by 10 points.
A profile stays active until **End profile**, another profile starts, or the app quits;
original system settings are journaled for recovery. The toast preference is not full
Focus Assist control. Stopping never kills games or other processes.

Run `build.bat` on Windows to test and build with PyInstaller. Distribute the complete
`dist/NovaDeck` folder. The Windows CI workflow is provided but has not been run here.
Cloud validation covers mocked integrations, real GUI windows, a Linux frozen build,
and download/loading of both official Vosk models. Windows hardware, global hotkeys,
startup/tray behavior and live Spotify playback still require native validation.
