# DebugPilot local MVP
Objective: implement the supplied specification in its six ordered phases.
Branch: feat/debugpilot-mvp; delivery: feature-branch-chain (user confirmed; local only); runner: uv run pytest; forecast: >400 authored lines.

## Specs
### S1

# 1. Visión del producto

DebugPilot será una aplicación local que permita inspeccionar, monitorear y depurar aplicaciones que se ejecutan en Docker.

El desarrollador podrá ejecutar:

```bash
debugpilot
```

Y abrir una interfaz interactiva directamente en su terminal.

Desde esa interfaz podrá:

1. Descubrir contenedores Docker activos y detenidos.
2. Visualizar logs en tiempo real.
3. Buscar, filtrar y pausar visualmente los logs.
4. Identificar errores y excepciones.
5. Conectarse a aplicaciones Python que ejecutan Debugpy.
6. Establecer y eliminar breakpoints.
7. Detener la ejecución de Python cuando alcance un breakpoint.
8. Inspeccionar variables, threads y call stack.
9. Continuar la ejecución.
10. Ejecutar Step Over, Step Into y Step Out.
11. Navegar por el código fuente local.
12. Administrar y cerrar sesiones de debugging.

En el futuro DebugPilot incorporará:

- GUI de escritorio con PySide6.
- Soporte para Node.js y Go.
- Integración con agentes de IA mediante MCP.
- Análisis inteligente de logs y errores.
- Correlación de eventos entre microservicios.
- Captura y reproducción de sesiones de debugging.
- Capacidades colaborativas y una futura versión SaaS.

**No implementar estas capacidades futuras todavía.**

La primera versión debe funcionar completamente en local, sin conexión a Internet ni servicios cloud durante su uso.

---


### S2

# 2. Decisiones tecnológicas

Utilizar:

### Lenguaje y herramientas

- Python 3.12 o superior.
- `uv` para gestionar dependencias.
- `pyproject.toml` para empaquetado.
- Typer para la CLI.
- Rich para mensajes y salidas de comandos.
- Pydantic para modelos y configuración.
- Platformdirs para rutas de configuración y datos.
- Ruff para linting y formato.
- Pytest y pytest-asyncio para pruebas.

### Interfaz

- Textual para la Terminal UI.
- Textual CSS para estilos.
- Widgets nativos de Textual cuando sea posible.

### Docker

- Docker SDK for Python.
- Docker Engine API.
- Docker Compose mediante etiquetas y metadatos de los contenedores.

### Debugging

- Debug Adapter Protocol.
- Debugpy para procesos Python.
- Cliente DAP implementado como módulo independiente.
- Transporte y manejo de eventos asíncronos.

### Persistencia

- SQLite para datos locales que realmente necesiten persistencia.
- Archivos TOML para configuración.
- No introducir un ORM si no es necesario.

### Restricciones

No utilizar:

- React.
- Electron.
- FastAPI.
- Servidores HTTP propios.
- WebSockets.
- PostgreSQL.
- Redis.
- Kafka.
- Servicios cloud.
- APIs de inteligencia artificial en esta fase.

La aplicación debe ejecutarse localmente como un proceso Python.

---


### S3

# 3. Arquitectura obligatoria

Implementar una arquitectura modular que permita reutilizar el motor con distintas interfaces.

La lógica de negocio no debe depender de Textual.

Diseñar las siguientes capas:

## A. DebugPilot Core

Responsable de:

- Gestión del ciclo de vida.
- Gestión de sesiones.
- Coordinación de servicios.
- Modelos de dominio.
- Gestión de errores.
- Configuración.
- Publicación de eventos.
- Cancelación de tareas asíncronas.

Debe proporcionar una API interna independiente de la interfaz.

Ejemplo conceptual:

```python
class DebugPilotEngine:
    async def list_containers(self): ...
    async def stream_logs(self, container_id): ...
    async def attach_debugger(self, config): ...
    async def set_breakpoints(self, session_id, file, lines): ...
    async def continue_execution(self, session_id): ...
    async def disconnect_debugger(self, session_id): ...
```

Adapta estas firmas si encuentras una arquitectura mejor.

## B. Docker Integration

Responsable de:

- Conexión con Docker Engine.
- Descubrimiento de contenedores.
- Metadatos.
- Logs históricos.
- Streaming de logs.
- Detección de cambios de estado.
- Manejo de desconexiones.

## C. Debug Adapter

Responsable de:

- Transporte DAP.
- Inicialización.
- Attach.
- Breakpoints.
- Threads.
- Stack frames.
- Scopes.
- Variables.
- Controles de ejecución.
- Eventos.
- Desconexión.

## D. Presentation Layer

Inicialmente:

`debugpilot/tui/`

Posteriormente:

`debugpilot/gui/`

Ambas interfaces deberán utilizar el mismo motor.

## E. Storage

Responsable de:

- Configuración.
- Workspaces autorizados.
- Configuraciones de debugging.
- Preferencias.
- Historial local mínimo, si aporta valor.

---


### S4

# 4. Estructura del repositorio

Utiliza una estructura similar a esta:

```text
debugpilot/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .gitignore
├── .python-version
│
├── src/
│   └── debugpilot/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── engine.py
│       │   ├── events.py
│       │   ├── models.py
│       │   ├── exceptions.py
│       │   ├── sessions.py
│       │   └── protocols.py
│       │
│       ├── docker/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── discovery.py
│       │   ├── containers.py
│       │   └── logs.py
│       │
│       ├── debugger/
│       │   ├── __init__.py
│       │   ├── dap_transport.py
│       │   ├── dap_client.py
│       │   ├── debugpy_adapter.py
│       │   ├── breakpoints.py
│       │   ├── sessions.py
│       │   └── path_mapping.py
│       │
│       ├── tui/
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── styles.tcss
│       │   ├── screens/
│       │   │   ├── dashboard.py
│       │   │   └── debug_session.py
│       │   └── widgets/
│       │       ├── container_list.py
│       │       ├── log_viewer.py
│       │       ├── source_viewer.py
│       │       ├── variable_tree.py
│       │       └── call_stack.py
│       │
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   └── database.py
│       │
│       └── utils/
│           └── logging.py
│
├── examples/
│   └── fastapi-debug/
│       ├── Dockerfile
│       ├── compose.yaml
│       ├── requirements.txt
│       └── app/
│           ├── __init__.py
│           ├── main.py
│           └── payments.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── docs/
    ├── architecture.md
    ├── debugging.md
    ├── docker.md
    └── future-gui.md
```

Puedes ajustar la estructura si encuentras una razón técnica clara.

No crear archivos vacíos innecesarios.

---


### S5

# 5. CLI

Implementar los comandos:

```bash
debugpilot
debugpilot tui
debugpilot doctor
debugpilot containers
debugpilot logs <container>
debugpilot version
```

Reservar para el futuro:

```bash
debugpilot gui
```

El comando `debugpilot` debe abrir directamente la Terminal UI.

### Doctor

Debe comprobar:

- Versión de Python.
- Disponibilidad de Docker Engine.
- Conectividad con Docker.
- Versión del servidor Docker.
- Disponibilidad de permisos.
- Estado del entorno.
- Configuración de DebugPilot.

Los errores deben ser comprensibles.

### Logs

Permitir:

```bash
debugpilot logs payments-api
debugpilot logs payments-api --follow
debugpilot logs payments-api --tail 100
```

No implementar todavía comandos destructivos.

---


### S6

# 6. Docker Engine

Implementar un servicio que permita descubrir contenedores y consultar sus metadatos.

Información requerida:

- ID.
- Nombre.
- Imagen.
- Estado.
- Fecha de creación.
- Puertos.
- Labels.
- Proyecto Docker Compose.
- Nombre del servicio Compose.

La herramienta debe funcionar con contenedores iniciados mediante `docker run` y Docker Compose.

No depender de que Docker Compose esté instalado para descubrir contenedores.

### Streaming de logs

Implementar:

- Lectura histórica.
- Seguimiento en tiempo real.
- Timestamps.
- Stdout y stderr cuando Docker permita distinguirlos.
- Reconexión controlada.
- Cancelación.
- Buffer circular.
- Límites de memoria.
- Manejo de contenedores detenidos.

El Docker SDK contiene operaciones bloqueantes. No ejecutarlas directamente en el event loop de Textual.

Utilizar workers, threads o mecanismos equivalentes, con limpieza explícita.

Evitar duplicar logs al reconectar.

No asumir que todos los contenedores permiten recuperar logs: algunos drivers de logging pueden tener limitaciones.

---


### S7

# 7. Terminal UI

Crear una interfaz profesional, oscura y orientada a teclado.

Diseño inicial:

```text
┌─────────────────────────────────────────────────────────────┐
│ DebugPilot                      Docker ● Connected         │
├──────────────────┬──────────────────────────────────────────┤
│ CONTAINERS       │ LIVE LOGS                                │
│                  │                                          │
│ ● payments-api   │ INFO  POST /payments                     │
│ ● postgres       │ INFO  Processing payment                 │
│ ● rabbitmq       │ ERROR Invalid amount                     │
│ ● worker         │                                          │
├──────────────────┼──────────────────────────────────────────┤
│ DEBUG SESSION    │ SOURCE                                   │
│                  │                                          │
│ ● Connected      │ 40  def process_payment(payment):        │
│ ● Paused         │ 41      amount = payment.amount          │
│                  │ ●42      validate(amount)               │
├──────────────────┴──────────────────────────────────────────┤
│ VARIABLES            │ CALL STACK                           │
│ amount = -150        │ process_payment                      │
│ status = pending     │ create_payment                       │
├─────────────────────────────────────────────────────────────┤
│ F5 Continue  F9 Breakpoint  F10 Step Over  Ctrl+P Commands │
└─────────────────────────────────────────────────────────────┘
```

La distribución puede adaptarse al tamaño de la terminal.

### Panel de contenedores

- Selección mediante teclado.
- Estados visuales.
- Actualización de estados.
- Identificación de servicios Compose.

### Panel de logs

- Streaming.
- Scroll.
- Búsqueda.
- Filtros por texto.
- Filtro por severidad inferida.
- Auto-scroll.
- Pausa visual.
- Limpieza de vista.
- Copiar entradas cuando sea posible.

### Panel de debugging

- Estado de sesión.
- Thread seleccionado.
- Call stack.
- Variables.
- Breakpoints.
- Controles de ejecución.

### Visor de código

- Archivos del workspace autorizado.
- Números de línea.
- Breakpoints.
- Línea actual.
- Scroll.
- Selección de línea.

No necesitamos construir un editor completo de código en esta fase.

### Atajos

- F5: Continue.
- F9: Toggle Breakpoint.
- F10: Step Over.
- F11: Step Into.
- Shift+F11: Step Out.
- Ctrl+P: Command Palette.
- Ctrl+L: enfocar logs.
- Q: salir cuando no haya un campo de entrada activo.

Asegurar que los atajos no interfieran con la entrada de texto.

---


### S8

# 8. Debug Adapter Protocol

Implementar un cliente DAP real y reutilizable.

El protocolo debe soportar mensajes con framing:

```text
Content-Length: <bytes>

<JSON message>
```

Utilizar los separadores CRLF requeridos por DAP y calcular el tamaño en bytes UTF-8.

El cliente debe gestionar:

- Sequence numbers.
- Requests.
- Responses.
- Events.
- Timeouts.
- Requests pendientes.
- Errores de protocolo.
- Desconexiones.
- Cancelación.
- Estado de sesión.

### Requests iniciales

- initialize
- attach
- setBreakpoints
- configurationDone
- threads
- stackTrace
- scopes
- variables
- continue
- next
- stepIn
- stepOut
- disconnect

### Eventos

- initialized
- stopped
- continued
- terminated
- exited
- thread
- output

Respetar el orden y las capacidades negociadas con el adaptador.

No asumir que todos los adaptadores soportan exactamente las mismas operaciones.

### Debugpy

Utilizar el mecanismo documentado de conexión con Debugpy.

Importante: distinguir entre el endpoint de conexión expuesto por Debugpy y su comunicación interna con el adaptador.

No implementar una conexión DAP ingenua que ignore el proceso de handshake y attach requerido por Debugpy.

Si es necesario, estudiar el comportamiento del cliente de referencia y las especificaciones oficiales.

---


### S9

# 9. Sesiones de debugging

Crear un Session Manager con estados explícitos:

- disconnected
- connecting
- initializing
- configuring
- running
- paused
- disconnecting
- error

Las transiciones deben estar controladas.

Una sesión debe contener:

- Identificador.
- Tipo de debugger.
- Configuración.
- Estado.
- Breakpoints.
- Threads.
- Stack frames.
- Variables consultadas.
- Eventos relevantes.

Para el MVP soportar una sesión activa de debugging a la vez.

Diseñar la arquitectura para soportar múltiples sesiones posteriormente.

### Breakpoints

Permitir establecer y eliminar breakpoints desde el visor de código.

Gestionar breakpoints por archivo.

Utilizar las respuestas del adaptador para determinar si un breakpoint fue verificado.

No mostrar como confirmado un breakpoint que el adaptador todavía no verificó.

### Variables

Permitir consultar variables cuando la aplicación esté pausada.

Mostrar:

- Nombre.
- Tipo, cuando esté disponible.
- Valor.
- Referencia a hijos.
- Variables anidadas mediante carga bajo demanda.

No habilitar evaluación arbitraria de expresiones ni modificación de variables en esta versión.

### Controles

Implementar:

- Continue.
- Step Over.
- Step Into.
- Step Out.

Deshabilitar controles incompatibles con el estado actual.

---


### S10

# 10. Path Mapping

El debugging de aplicaciones Docker necesita mapear archivos del contenedor al host.

Ejemplo:

```text
Host:
C:\projects\payments\app\payments.py

Container:
/app/app/payments.py
```

Implementar un sistema explícito de path mapping.

Debe soportar:

- Windows.
- Linux.
- macOS.
- Separadores de rutas.
- Prefijos de rutas.
- Validación de rutas.
- Workspaces autorizados.

No permitir leer archivos arbitrarios fuera del workspace configurado.

Los errores de mapeo deben mostrarse claramente.

---


### S11

# 11. Proyecto FastAPI de ejemplo

Crear una aplicación de prueba real.

Estructura:

```text
examples/fastapi-debug/
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── app/
    ├── main.py
    └── payments.py
```

La aplicación debe tener:

```text
GET /health
POST /payments
GET /debug/error
```

Implementar una función:

```python
def process_payment(payment):
    ...
```

Que permita colocar breakpoints e inspeccionar variables.

Agregar:

- Logs estructurados.
- Errores reproducibles.
- Validaciones.
- Dockerfile funcional.
- Docker Compose.
- Debugpy.

Ejecutar Python mediante Debugpy.

Utilizar un único worker Uvicorn, sin autoreload.

Exponer el puerto de Debugpy solamente en loopback del host.

Documentar cómo ejecutar el ejemplo y cómo conectar DebugPilot.

---


### S12

# 12. Seguridad

DebugPilot tendrá acceso a información sensible de desarrollo.

Aplicar las siguientes reglas:

1. Todo funciona localmente.
2. No enviar código ni logs a servidores externos.
3. No recopilar telemetría.
4. No exponer el Docker socket.
5. No ejecutar comandos arbitrarios en contenedores.
6. No permitir conexiones de debugging a hosts remotos por defecto.
7. Requerir configuración explícita del endpoint Debugpy.
8. Validar los workspaces.
9. Limitar memoria y tamaños de mensajes.
10. Cerrar correctamente threads y conexiones.
11. No registrar secretos en logs internos.
12. No persistir valores de variables sensibles por defecto.

La conexión Debugpy debe considerarse una capacidad privilegiada de desarrollo y nunca exponerse a redes no confiables.

---


### S13

# 13. Preparación para futura GUI de escritorio

Este requisito es obligatorio.

En el futuro implementaremos:

```bash
debugpilot gui
```

Utilizando PySide6.

Por lo tanto:

- El Core no debe importar Textual.
- Docker Integration no debe importar Textual.
- Debugger no debe importar Textual.
- Storage no debe importar Textual.
- Los modelos de dominio no deben contener widgets.
- Los eventos deben ser independientes de la interfaz.
- Los servicios deben ofrecer APIs asíncronas bien definidas.
- Los tests del Core deben ejecutarse sin una terminal interactiva.
- El ciclo de vida del motor no debe depender del ciclo de vida de Textual.
- Documentar cómo integrar el motor con el event loop de Qt, por ejemplo mediante un adaptador asíncrono apropiado.

No implementar PySide6 todavía.

No crear abstracciones vacías innecesarias.

---


### S14

# 14. Testing

Implementar pruebas unitarias para:

- Docker discovery.
- Normalización de metadatos.
- Streaming de logs.
- Buffer circular.
- Cancelación de streaming.
- DAP framing.
- Parsing de mensajes.
- Correlación de requests.
- Timeouts.
- Estado de sesiones.
- Breakpoints.
- Path mapping.
- Configuración.
- Manejo de errores.

Implementar pruebas de integración para:

1. Conexión real con Docker, cuando esté disponible.
2. Lectura de logs de un contenedor real.
3. Conexión con Debugpy.
4. Configuración de un breakpoint.
5. Detención en el breakpoint.
6. Consulta de stack frames.
7. Consulta de variables.
8. Continuación de la ejecución.
9. Desconexión limpia.

Utilizar mocks solamente en pruebas unitarias donde sean apropiados.

Si Docker no está disponible, omitir las pruebas que lo requieran y documentarlo.

No declarar como verificadas funcionalidades que no hayan sido probadas.

---


### S15

# 15. Documentación

Crear documentación clara para:

- Instalación.
- Requisitos.
- Uso de la CLI.
- Navegación TUI.
- Docker.
- Configuración de Debugpy.
- Path mapping.
- Troubleshooting.
- Arquitectura.
- Futuro soporte GUI.

Documentar las diferencias de instalación y ejecución entre Windows, Linux y macOS.

---


### S16

# 16. Plan de implementación

Trabajar en fases.

### Fase 1 — Foundation

- Inicializar proyecto.
- Configurar dependencias.
- Crear CLI.
- Crear Core.
- Definir modelos.
- Configurar tests.

### Fase 2 — Docker

- Conexión Docker.
- Descubrimiento.
- Metadatos.
- Logs históricos.
- Streaming.
- Reconexión y cancelación.

### Fase 3 — TUI

- Layout.
- Panel de contenedores.
- Visor de logs.
- Navegación.
- Atajos.
- Estados de error.

### Fase 4 — DAP

- Transporte.
- Cliente.
- Estados.
- Eventos.
- Debugpy attach.

### Fase 5 — Debugging interactivo

- Breakpoints.
- Call stack.
- Variables.
- Continue.
- Step Over.
- Step Into.
- Step Out.
- Visor de código.

### Fase 6 — Integración

- Ejemplo FastAPI.
- Pruebas reales.
- Documentación.
- Corrección de errores.
- Empaquetado.

Después de cada fase:

- Ejecutar las pruebas relevantes.
- Ejecutar Ruff.
- Corregir errores.
- Comprobar compatibilidad con lo implementado previamente.

No avanzar dejando errores conocidos sin documentar.

---


### S17

# 17. Criterios de aceptación

Consideraremos que el MVP funciona cuando:

1. `uv sync` instala el proyecto.
2. `debugpilot` abre la TUI.
3. `debugpilot doctor` comprueba Docker.
4. Se detectan contenedores reales.
5. Los logs se visualizan en tiempo real.
6. Los filtros funcionan.
7. La pausa visual funciona sin detener el contenedor.
8. Se puede seleccionar un proyecto FastAPI en Docker.
9. Se puede conectar a Debugpy.
10. Se puede establecer un breakpoint.
11. El breakpoint detiene la ejecución.
12. Se pueden inspeccionar variables.
13. Se puede consultar el call stack.
14. F5 continúa la ejecución.
15. F10, F11 y Shift+F11 funcionan.
16. Se puede desconectar el debugger.
17. La aplicación cierra sin dejar tareas huérfanas.
18. El Core puede ejecutarse sin Textual.
19. La arquitectura permite incorporar PySide6 posteriormente.

---


### S18

# 18. Instrucciones finales

Primero inspecciona el repositorio.

Si está vacío, inicializa DebugPilot.

Después implementa las fases en el orden indicado.

Prioriza código funcional, modular y testeable.

No generes únicamente scaffolding.

No simules conexiones Docker o Debugpy en la aplicación real.

No afirmes que una funcionalidad funciona sin haberla comprobado.

Si una fase resulta demasiado grande, completa una porción vertical funcional, documenta exactamente qué queda pendiente y continúa en la siguiente iteración.

No hagas cambios destructivos en el entorno del usuario.

Al finalizar, presenta:

1. Resumen de implementación.
2. Estructura final.
3. Comandos para instalar.
4. Comandos para ejecutar.
5. Cómo iniciar el ejemplo FastAPI.
6. Cómo establecer el primer breakpoint.
7. Resultados de tests.
8. Funcionalidades completas y pendientes.
9. Problemas conocidos.
10. Recomendaciones para el siguiente prompt.

**Comienza ahora con la implementación de DebugPilot.**
### S19 — Compose lifecycle controls (scope extension)

User request (verbatim):
> Quisera que para las imagenes, tenga la capacidad de hacer un docker compose -f ruta/docker-compose.yaml -f configuracionlocal.yaml up --build -d --force-recreate, o un reinicio para que tome variables de entorno por ejemplo

Clarifying question (verbatim):
> ¿Querés que estas acciones permitan operar tanto sobre **el servicio seleccionado como sobre todo el proyecto Compose**?

User answer (verbatim):
> Si

This explicitly extends S5's read-only application scope to user-confirmed Compose lifecycle actions, not permission to mutate the developer's current containers while implementing/testing. Support ordered Compose files, selected-service or whole-project scope, restart and rebuild/recreate. Explain that restart does not reload changed environment configuration. Test subprocess boundaries with fakes; no real build/restart/recreate against the user's environment. Files and execution target must be explicit and local; show scope and interruption consequences before confirmation. T4-T6 remain deferred.

### S20 — Multi-project simulation and grouped actions

User request (verbatim):
> Necesito simular un caso necesito 3 proyectos separados, cada uno levante con docker compose sus propios servicios y que se comuniquen entre si a traves de red, entonces por proyecto deberian agruparse los servicios y deberia poder reiniciar la imagen sola o el grupo

Scope: three independent Compose project directories sharing a Docker network, with an observable inter-project request chain; group discovered services by Compose project in the terminal and allow confirmed selected-service or whole-project lifecycle actions. A service/container restarts; rebuild/recreate applies an image or environment change. Existing confirmation, explicit local target, ordered-file and no-credential-reuse boundaries remain unchanged. Names and example domain are implementation assumptions: gateway, orders and catalog, each with its own API and worker. No DAP, persistence, cloud or automatic publication is added.

### S21 — Contextual restart and rebuild shortcuts

User request (verbatim):
> Si toco la letra r reinicia, si pongo shift r build de donde este parado

Lowercase r opens the restart preview/confirmation for the selected Compose service or project group. Shift+R (uppercase R) opens rebuild-and-recreate for that same target. Existing explicit confirmation and trusted workspace/files remain required; typing in input fields must not execute an operation. Move the old log-retry shortcut from R to Ctrl+R, including help/status messages. Standalone containers are not silently treated as Compose services.

## Tasks
- T1 | S2-S5, S12-S15 | inline, no writer trigger | foundation: verified; default TUI deferred to T3 | commits 25283394dd8f12867242be5dc601313df22f53a7, df5c421b2c3b2e1ec9a760ab6e9494b718bb6aaf
- T2 | S6, S14 | inline, no writer trigger | Docker: independently verified | commits e11a94df522995f717b5ed40bbb9f524e7f1d600, 697af07b033801dd1cd7f79d0a95cb02aabb9d24, 6ee3eb330cd58538582118ededd084139dc7fba4; native review pending
- T3 | S5, S7 | inline; explorer used for resumed API map, no independent writer units | TUI: functionally verified; dashboard commit8a0fc8c; native review pending
- T4 | S8-S9 | inline, no writer trigger | DAP: pending
- T5 | S9-S10 | inline, no writer trigger | interactive debugging: pending
- T6 | S11, S14-S17 | inline, no writer trigger | integration, example, docs and packaging: pending
- T7 | S19 | delegated backend alongside inline dashboard; disjoint new module/test/doc surfaces | Compose execution/confirmation: functionally verified; backend442eea9, UI8a0fc8c, cleanup719ed2e; native review pending; no real lifecycle commands executed

- T8 | S20 | delegated parallel fixtures unit (disjoint examples/tests/docs) | in progress; baseline24b561b
- T9 | S7, S19-S21 | delegated parallel grouped TUI/actions unit (disjoint UI/tests/docs) | in progress; baseline24b561b

- T10 | S19-S20 | inline discovered integration fix | verified locally: preserve Windows system plugin locations, RED unknown-compose/missingenv then GREEN; commit pending

## Log
L1 — Original user request (verbatim):

# DebugPilot — Prompt 01: Arquitectura e implementación del MVP local

## Rol

Actúa como un Principal Software Engineer y Software Architect especializado en:

- Python y programación asíncrona.
- Docker Engine y Docker Compose.
- Debug Adapter Protocol (DAP).
- Debugpy y debugging de aplicaciones Python.
- Desarrollo de Terminal UI con Textual.
- Arquitecturas modulares, extensibles y multiplataforma.
- Herramientas profesionales para desarrolladores.
- Testing, seguridad y distribución de aplicaciones.

Tu misión es diseñar e implementar **DebugPilot**, una herramienta profesional de debugging local para desarrolladores.

No quiero únicamente documentación, pseudocódigo o componentes simulados. Quiero una aplicación ejecutable, modular y probada.

---

# 1. Visión del producto

DebugPilot será una aplicación local que permita inspeccionar, monitorear y depurar aplicaciones que se ejecutan en Docker.

El desarrollador podrá ejecutar:

```bash
debugpilot
```

Y abrir una interfaz interactiva directamente en su terminal.

Desde esa interfaz podrá:

1. Descubrir contenedores Docker activos y detenidos.
2. Visualizar logs en tiempo real.
3. Buscar, filtrar y pausar visualmente los logs.
4. Identificar errores y excepciones.
5. Conectarse a aplicaciones Python que ejecutan Debugpy.
6. Establecer y eliminar breakpoints.
7. Detener la ejecución de Python cuando alcance un breakpoint.
8. Inspeccionar variables, threads y call stack.
9. Continuar la ejecución.
10. Ejecutar Step Over, Step Into y Step Out.
11. Navegar por el código fuente local.
12. Administrar y cerrar sesiones de debugging.

En el futuro DebugPilot incorporará:

- GUI de escritorio con PySide6.
- Soporte para Node.js y Go.
- Integración con agentes de IA mediante MCP.
- Análisis inteligente de logs y errores.
- Correlación de eventos entre microservicios.
- Captura y reproducción de sesiones de debugging.
- Capacidades colaborativas y una futura versión SaaS.

**No implementar estas capacidades futuras todavía.**

La primera versión debe funcionar completamente en local, sin conexión a Internet ni servicios cloud durante su uso.

---

# 2. Decisiones tecnológicas

Utilizar:

### Lenguaje y herramientas

- Python 3.12 o superior.
- `uv` para gestionar dependencias.
- `pyproject.toml` para empaquetado.
- Typer para la CLI.
- Rich para mensajes y salidas de comandos.
- Pydantic para modelos y configuración.
- Platformdirs para rutas de configuración y datos.
- Ruff para linting y formato.
- Pytest y pytest-asyncio para pruebas.

### Interfaz

- Textual para la Terminal UI.
- Textual CSS para estilos.
- Widgets nativos de Textual cuando sea posible.

### Docker

- Docker SDK for Python.
- Docker Engine API.
- Docker Compose mediante etiquetas y metadatos de los contenedores.

### Debugging

- Debug Adapter Protocol.
- Debugpy para procesos Python.
- Cliente DAP implementado como módulo independiente.
- Transporte y manejo de eventos asíncronos.

### Persistencia

- SQLite para datos locales que realmente necesiten persistencia.
- Archivos TOML para configuración.
- No introducir un ORM si no es necesario.

### Restricciones

No utilizar:

- React.
- Electron.
- FastAPI.
- Servidores HTTP propios.
- WebSockets.
- PostgreSQL.
- Redis.
- Kafka.
- Servicios cloud.
- APIs de inteligencia artificial en esta fase.

La aplicación debe ejecutarse localmente como un proceso Python.

---

# 3. Arquitectura obligatoria

Implementar una arquitectura modular que permita reutilizar el motor con distintas interfaces.

La lógica de negocio no debe depender de Textual.

Diseñar las siguientes capas:

## A. DebugPilot Core

Responsable de:

- Gestión del ciclo de vida.
- Gestión de sesiones.
- Coordinación de servicios.
- Modelos de dominio.
- Gestión de errores.
- Configuración.
- Publicación de eventos.
- Cancelación de tareas asíncronas.

Debe proporcionar una API interna independiente de la interfaz.

Ejemplo conceptual:

```python
class DebugPilotEngine:
    async def list_containers(self): ...
    async def stream_logs(self, container_id): ...
    async def attach_debugger(self, config): ...
    async def set_breakpoints(self, session_id, file, lines): ...
    async def continue_execution(self, session_id): ...
    async def disconnect_debugger(self, session_id): ...
```

Adapta estas firmas si encuentras una arquitectura mejor.

## B. Docker Integration

Responsable de:

- Conexión con Docker Engine.
- Descubrimiento de contenedores.
- Metadatos.
- Logs históricos.
- Streaming de logs.
- Detección de cambios de estado.
- Manejo de desconexiones.

## C. Debug Adapter

Responsable de:

- Transporte DAP.
- Inicialización.
- Attach.
- Breakpoints.
- Threads.
- Stack frames.
- Scopes.
- Variables.
- Controles de ejecución.
- Eventos.
- Desconexión.

## D. Presentation Layer

Inicialmente:

`debugpilot/tui/`

Posteriormente:

`debugpilot/gui/`

Ambas interfaces deberán utilizar el mismo motor.

## E. Storage

Responsable de:

- Configuración.
- Workspaces autorizados.
- Configuraciones de debugging.
- Preferencias.
- Historial local mínimo, si aporta valor.

---

# 4. Estructura del repositorio

Utiliza una estructura similar a esta:

```text
debugpilot/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .gitignore
├── .python-version
│
├── src/
│   └── debugpilot/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── engine.py
│       │   ├── events.py
│       │   ├── models.py
│       │   ├── exceptions.py
│       │   ├── sessions.py
│       │   └── protocols.py
│       │
│       ├── docker/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── discovery.py
│       │   ├── containers.py
│       │   └── logs.py
│       │
│       ├── debugger/
│       │   ├── __init__.py
│       │   ├── dap_transport.py
│       │   ├── dap_client.py
│       │   ├── debugpy_adapter.py
│       │   ├── breakpoints.py
│       │   ├── sessions.py
│       │   └── path_mapping.py
│       │
│       ├── tui/
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── styles.tcss
│       │   ├── screens/
│       │   │   ├── dashboard.py
│       │   │   └── debug_session.py
│       │   └── widgets/
│       │       ├── container_list.py
│       │       ├── log_viewer.py
│       │       ├── source_viewer.py
│       │       ├── variable_tree.py
│       │       └── call_stack.py
│       │
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   └── database.py
│       │
│       └── utils/
│           └── logging.py
│
├── examples/
│   └── fastapi-debug/
│       ├── Dockerfile
│       ├── compose.yaml
│       ├── requirements.txt
│       └── app/
│           ├── __init__.py
│           ├── main.py
│           └── payments.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── docs/
    ├── architecture.md
    ├── debugging.md
    ├── docker.md
    └── future-gui.md
```

Puedes ajustar la estructura si encuentras una razón técnica clara.

No crear archivos vacíos innecesarios.

---

# 5. CLI

Implementar los comandos:

```bash
debugpilot
debugpilot tui
debugpilot doctor
debugpilot containers
debugpilot logs <container>
debugpilot version
```

Reservar para el futuro:

```bash
debugpilot gui
```

El comando `debugpilot` debe abrir directamente la Terminal UI.

### Doctor

Debe comprobar:

- Versión de Python.
- Disponibilidad de Docker Engine.
- Conectividad con Docker.
- Versión del servidor Docker.
- Disponibilidad de permisos.
- Estado del entorno.
- Configuración de DebugPilot.

Los errores deben ser comprensibles.

### Logs

Permitir:

```bash
debugpilot logs payments-api
debugpilot logs payments-api --follow
debugpilot logs payments-api --tail 100
```

No implementar todavía comandos destructivos.

---

# 6. Docker Engine

Implementar un servicio que permita descubrir contenedores y consultar sus metadatos.

Información requerida:

- ID.
- Nombre.
- Imagen.
- Estado.
- Fecha de creación.
- Puertos.
- Labels.
- Proyecto Docker Compose.
- Nombre del servicio Compose.

La herramienta debe funcionar con contenedores iniciados mediante `docker run` y Docker Compose.

No depender de que Docker Compose esté instalado para descubrir contenedores.

### Streaming de logs

Implementar:

- Lectura histórica.
- Seguimiento en tiempo real.
- Timestamps.
- Stdout y stderr cuando Docker permita distinguirlos.
- Reconexión controlada.
- Cancelación.
- Buffer circular.
- Límites de memoria.
- Manejo de contenedores detenidos.

El Docker SDK contiene operaciones bloqueantes. No ejecutarlas directamente en el event loop de Textual.

Utilizar workers, threads o mecanismos equivalentes, con limpieza explícita.

Evitar duplicar logs al reconectar.

No asumir que todos los contenedores permiten recuperar logs: algunos drivers de logging pueden tener limitaciones.

---

# 7. Terminal UI

Crear una interfaz profesional, oscura y orientada a teclado.

Diseño inicial:

```text
┌─────────────────────────────────────────────────────────────┐
│ DebugPilot                      Docker ● Connected         │
├──────────────────┬──────────────────────────────────────────┤
│ CONTAINERS       │ LIVE LOGS                                │
│                  │                                          │
│ ● payments-api   │ INFO  POST /payments                     │
│ ● postgres       │ INFO  Processing payment                 │
│ ● rabbitmq       │ ERROR Invalid amount                     │
│ ● worker         │                                          │
├──────────────────┼──────────────────────────────────────────┤
│ DEBUG SESSION    │ SOURCE                                   │
│                  │                                          │
│ ● Connected      │ 40  def process_payment(payment):        │
│ ● Paused         │ 41      amount = payment.amount          │
│                  │ ●42      validate(amount)               │
├──────────────────┴──────────────────────────────────────────┤
│ VARIABLES            │ CALL STACK                           │
│ amount = -150        │ process_payment                      │
│ status = pending     │ create_payment                       │
├─────────────────────────────────────────────────────────────┤
│ F5 Continue  F9 Breakpoint  F10 Step Over  Ctrl+P Commands │
└─────────────────────────────────────────────────────────────┘
```

La distribución puede adaptarse al tamaño de la terminal.

### Panel de contenedores

- Selección mediante teclado.
- Estados visuales.
- Actualización de estados.
- Identificación de servicios Compose.

### Panel de logs

- Streaming.
- Scroll.
- Búsqueda.
- Filtros por texto.
- Filtro por severidad inferida.
- Auto-scroll.
- Pausa visual.
- Limpieza de vista.
- Copiar entradas cuando sea posible.

### Panel de debugging

- Estado de sesión.
- Thread seleccionado.
- Call stack.
- Variables.
- Breakpoints.
- Controles de ejecución.

### Visor de código

- Archivos del workspace autorizado.
- Números de línea.
- Breakpoints.
- Línea actual.
- Scroll.
- Selección de línea.

No necesitamos construir un editor completo de código en esta fase.

### Atajos

- F5: Continue.
- F9: Toggle Breakpoint.
- F10: Step Over.
- F11: Step Into.
- Shift+F11: Step Out.
- Ctrl+P: Command Palette.
- Ctrl+L: enfocar logs.
- Q: salir cuando no haya un campo de entrada activo.

Asegurar que los atajos no interfieran con la entrada de texto.

---

# 8. Debug Adapter Protocol

Implementar un cliente DAP real y reutilizable.

El protocolo debe soportar mensajes con framing:

```text
Content-Length: <bytes>

<JSON message>
```

Utilizar los separadores CRLF requeridos por DAP y calcular el tamaño en bytes UTF-8.

El cliente debe gestionar:

- Sequence numbers.
- Requests.
- Responses.
- Events.
- Timeouts.
- Requests pendientes.
- Errores de protocolo.
- Desconexiones.
- Cancelación.
- Estado de sesión.

### Requests iniciales

- initialize
- attach
- setBreakpoints
- configurationDone
- threads
- stackTrace
- scopes
- variables
- continue
- next
- stepIn
- stepOut
- disconnect

### Eventos

- initialized
- stopped
- continued
- terminated
- exited
- thread
- output

Respetar el orden y las capacidades negociadas con el adaptador.

No asumir que todos los adaptadores soportan exactamente las mismas operaciones.

### Debugpy

Utilizar el mecanismo documentado de conexión con Debugpy.

Importante: distinguir entre el endpoint de conexión expuesto por Debugpy y su comunicación interna con el adaptador.

No implementar una conexión DAP ingenua que ignore el proceso de handshake y attach requerido por Debugpy.

Si es necesario, estudiar el comportamiento del cliente de referencia y las especificaciones oficiales.

---

# 9. Sesiones de debugging

Crear un Session Manager con estados explícitos:

- disconnected
- connecting
- initializing
- configuring
- running
- paused
- disconnecting
- error

Las transiciones deben estar controladas.

Una sesión debe contener:

- Identificador.
- Tipo de debugger.
- Configuración.
- Estado.
- Breakpoints.
- Threads.
- Stack frames.
- Variables consultadas.
- Eventos relevantes.

Para el MVP soportar una sesión activa de debugging a la vez.

Diseñar la arquitectura para soportar múltiples sesiones posteriormente.

### Breakpoints

Permitir establecer y eliminar breakpoints desde el visor de código.

Gestionar breakpoints por archivo.

Utilizar las respuestas del adaptador para determinar si un breakpoint fue verificado.

No mostrar como confirmado un breakpoint que el adaptador todavía no verificó.

### Variables

Permitir consultar variables cuando la aplicación esté pausada.

Mostrar:

- Nombre.
- Tipo, cuando esté disponible.
- Valor.
- Referencia a hijos.
- Variables anidadas mediante carga bajo demanda.

No habilitar evaluación arbitraria de expresiones ni modificación de variables en esta versión.

### Controles

Implementar:

- Continue.
- Step Over.
- Step Into.
- Step Out.

Deshabilitar controles incompatibles con el estado actual.

---

# 10. Path Mapping

El debugging de aplicaciones Docker necesita mapear archivos del contenedor al host.

Ejemplo:

```text
Host:
C:\projects\payments\app\payments.py

Container:
/app/app/payments.py
```

Implementar un sistema explícito de path mapping.

Debe soportar:

- Windows.
- Linux.
- macOS.
- Separadores de rutas.
- Prefijos de rutas.
- Validación de rutas.
- Workspaces autorizados.

No permitir leer archivos arbitrarios fuera del workspace configurado.

Los errores de mapeo deben mostrarse claramente.

---

# 11. Proyecto FastAPI de ejemplo

Crear una aplicación de prueba real.

Estructura:

```text
examples/fastapi-debug/
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── app/
    ├── main.py
    └── payments.py
```

La aplicación debe tener:

```text
GET /health
POST /payments
GET /debug/error
```

Implementar una función:

```python
def process_payment(payment):
    ...
```

Que permita colocar breakpoints e inspeccionar variables.

Agregar:

- Logs estructurados.
- Errores reproducibles.
- Validaciones.
- Dockerfile funcional.
- Docker Compose.
- Debugpy.

Ejecutar Python mediante Debugpy.

Utilizar un único worker Uvicorn, sin autoreload.

Exponer el puerto de Debugpy solamente en loopback del host.

Documentar cómo ejecutar el ejemplo y cómo conectar DebugPilot.

---

# 12. Seguridad

DebugPilot tendrá acceso a información sensible de desarrollo.

Aplicar las siguientes reglas:

1. Todo funciona localmente.
2. No enviar código ni logs a servidores externos.
3. No recopilar telemetría.
4. No exponer el Docker socket.
5. No ejecutar comandos arbitrarios en contenedores.
6. No permitir conexiones de debugging a hosts remotos por defecto.
7. Requerir configuración explícita del endpoint Debugpy.
8. Validar los workspaces.
9. Limitar memoria y tamaños de mensajes.
10. Cerrar correctamente threads y conexiones.
11. No registrar secretos en logs internos.
12. No persistir valores de variables sensibles por defecto.

La conexión Debugpy debe considerarse una capacidad privilegiada de desarrollo y nunca exponerse a redes no confiables.

---

# 13. Preparación para futura GUI de escritorio

Este requisito es obligatorio.

En el futuro implementaremos:

```bash
debugpilot gui
```

Utilizando PySide6.

Por lo tanto:

- El Core no debe importar Textual.
- Docker Integration no debe importar Textual.
- Debugger no debe importar Textual.
- Storage no debe importar Textual.
- Los modelos de dominio no deben contener widgets.
- Los eventos deben ser independientes de la interfaz.
- Los servicios deben ofrecer APIs asíncronas bien definidas.
- Los tests del Core deben ejecutarse sin una terminal interactiva.
- El ciclo de vida del motor no debe depender del ciclo de vida de Textual.
- Documentar cómo integrar el motor con el event loop de Qt, por ejemplo mediante un adaptador asíncrono apropiado.

No implementar PySide6 todavía.

No crear abstracciones vacías innecesarias.

---

# 14. Testing

Implementar pruebas unitarias para:

- Docker discovery.
- Normalización de metadatos.
- Streaming de logs.
- Buffer circular.
- Cancelación de streaming.
- DAP framing.
- Parsing de mensajes.
- Correlación de requests.
- Timeouts.
- Estado de sesiones.
- Breakpoints.
- Path mapping.
- Configuración.
- Manejo de errores.

Implementar pruebas de integración para:

1. Conexión real con Docker, cuando esté disponible.
2. Lectura de logs de un contenedor real.
3. Conexión con Debugpy.
4. Configuración de un breakpoint.
5. Detención en el breakpoint.
6. Consulta de stack frames.
7. Consulta de variables.
8. Continuación de la ejecución.
9. Desconexión limpia.

Utilizar mocks solamente en pruebas unitarias donde sean apropiados.

Si Docker no está disponible, omitir las pruebas que lo requieran y documentarlo.

No declarar como verificadas funcionalidades que no hayan sido probadas.

---

# 15. Documentación

Crear documentación clara para:

- Instalación.
- Requisitos.
- Uso de la CLI.
- Navegación TUI.
- Docker.
- Configuración de Debugpy.
- Path mapping.
- Troubleshooting.
- Arquitectura.
- Futuro soporte GUI.

Documentar las diferencias de instalación y ejecución entre Windows, Linux y macOS.

---

# 16. Plan de implementación

Trabajar en fases.

### Fase 1 — Foundation

- Inicializar proyecto.
- Configurar dependencias.
- Crear CLI.
- Crear Core.
- Definir modelos.
- Configurar tests.

### Fase 2 — Docker

- Conexión Docker.
- Descubrimiento.
- Metadatos.
- Logs históricos.
- Streaming.
- Reconexión y cancelación.

### Fase 3 — TUI

- Layout.
- Panel de contenedores.
- Visor de logs.
- Navegación.
- Atajos.
- Estados de error.

### Fase 4 — DAP

- Transporte.
- Cliente.
- Estados.
- Eventos.
- Debugpy attach.

### Fase 5 — Debugging interactivo

- Breakpoints.
- Call stack.
- Variables.
- Continue.
- Step Over.
- Step Into.
- Step Out.
- Visor de código.

### Fase 6 — Integración

- Ejemplo FastAPI.
- Pruebas reales.
- Documentación.
- Corrección de errores.
- Empaquetado.

Después de cada fase:

- Ejecutar las pruebas relevantes.
- Ejecutar Ruff.
- Corregir errores.
- Comprobar compatibilidad con lo implementado previamente.

No avanzar dejando errores conocidos sin documentar.

---

# 17. Criterios de aceptación

Consideraremos que el MVP funciona cuando:

1. `uv sync` instala el proyecto.
2. `debugpilot` abre la TUI.
3. `debugpilot doctor` comprueba Docker.
4. Se detectan contenedores reales.
5. Los logs se visualizan en tiempo real.
6. Los filtros funcionan.
7. La pausa visual funciona sin detener el contenedor.
8. Se puede seleccionar un proyecto FastAPI en Docker.
9. Se puede conectar a Debugpy.
10. Se puede establecer un breakpoint.
11. El breakpoint detiene la ejecución.
12. Se pueden inspeccionar variables.
13. Se puede consultar el call stack.
14. F5 continúa la ejecución.
15. F10, F11 y Shift+F11 funcionan.
16. Se puede desconectar el debugger.
17. La aplicación cierra sin dejar tareas huérfanas.
18. El Core puede ejecutarse sin Textual.
19. La arquitectura permite incorporar PySide6 posteriormente.

---

# 18. Instrucciones finales

Primero inspecciona el repositorio.

Si está vacío, inicializa DebugPilot.

Después implementa las fases en el orden indicado.

Prioriza código funcional, modular y testeable.

No generes únicamente scaffolding.

No simules conexiones Docker o Debugpy en la aplicación real.

No afirmes que una funcionalidad funciona sin haberla comprobado.

Si una fase resulta demasiado grande, completa una porción vertical funcional, documenta exactamente qué queda pendiente y continúa en la siguiente iteración.

No hagas cambios destructivos en el entorno del usuario.

Al finalizar, presenta:

1. Resumen de implementación.
2. Estructura final.
3. Comandos para instalar.
4. Comandos para ejecutar.
5. Cómo iniciar el ejemplo FastAPI.
6. Cómo establecer el primer breakpoint.
7. Resultados de tests.
8. Funcionalidades completas y pendientes.
9. Problemas conocidos.
10. Recomendaciones para el siguiente prompt.

**Comienza ahora con la implementación de DebugPilot.**

L2 — 2026-10-26: Empty workspace, Git initialized. Branch feat/debugpilot-mvp. Python 3.12.14 bundled runtime; uv 0.13.5 installed only under ignored .tools/uv. uv sync generated uv.lock and .venv. No remote Git operations authorized or performed.
L3 — Foundation diagnostic slice: version/doctor CLI, bounded events, owned task cancellation, immutable settings, local endpoint guard, isolated Docker SDK probe. Remaining T1 API/session models and the default TUI launch are intentionally pending later phases, not simulated. No SQLite persistence need yet; no license selected.
L4 — RED: test_foundation.py initially failed collection (debugpilot.cli missing). GREEN: 7 tests passed. Added diagnostic tests: 2 failed/9 passed/1 deselected before probe implementation; an initial unbounded test wait was interrupted and replaced with a timeout. Windows pywintypes.error is not OSError: reproduced on a missing named pipe and handled explicitly.
L5 — Current checks: Ruff check clean; Ruff format applied. Full suite 19 passed, 1 integration skipped (no local Docker daemon). doctor exits 1 with unavailable daemon and unknown permissions/server version; no successful Docker connection verified. uv build produced wheel and sdist. No prior source baseline exists, so differential command regression comparison is N/A for this initial slice.
L6 — Risk: items 2 (local-only endpoint/credential isolation), 4 (async task/process cancellation), 5 (initial dependencies/packaging). Independent verifier required. No commits yet: forecast exceeds 400 authored lines; delivery/chain strategy must be selected before the next commit. RDD effective mode is on; review not started for this uncommitted initial slice.
L7 — Engram initial reads and saves fail unknown_project for the canonical detected debugealo key; mirror pending. No project-specific skill registry exists; injected global work-unit-commits and cognitive-doc-design skills are used. Source artifacts use English; original specification remains verbatim Spanish.
L8 — Independent high-risk foundation verification passed (not full MVP acceptance): isolated suite 19 passed/1 skipped; config rejection preserves file bytes; caller-cancelled and repeated/concurrent engine close; real worker output bounds, cancellation, timeout and reap; no ambient credentials/remote context; wheel and sdist checked. Parent reran scratch suite: 19 passed/1 skipped. No blockers found. Probes used scratch imports; sanitized SDK children use the editable installed package, so packaged imports were also checked independently. Verifier scratch directory is scheduled for exact-path cleanup by parent.
L9 — Latest Ruff formats Markdown Python fences. Excluded odd/ from Ruff to keep user specification verbatim; structural check confirms original request is preserved. Final Ruff check and format --check pass. Locked sync succeeds. No previous command baseline exists. Native RDD has not started; candidate commit/chain strategy is pending. The current slice is ready for a work-unit commit, not a complete T1/TUI/MVP claim.

L10 — Final verbatim assertion initially failed: the earlier Ruff run had reformatted a Python fence in L1. Restored L1 directly from the attachment, then observed the structural assertion pass. odd/ remains excluded so future normalization preserves it. The earlier L9 assertion claim is superseded by this observed result.
L11 — Verifier scratch exact-path cleanup completed (initial elevated cleanup hit mixed-ownership permissions; cleanup under the creating sandbox identity removed the remainder). Final Ruff check and format --check both pass. Wheel and sdist rebuilt successfully. No code changes after independent verification beyond Ruff's odd/ exclusion; specification/log restoration is passive documentation.
L12 — Native assessment attempted under enabled RDD: risk high/unassessable because all 22 intended source/docs/lock paths are untracked. Capabilities v2.6 supports start_lens_selection. First lens-bearing STATUS refused (invalid_request; selection required first). Canonical selectorless STATUS returned collect intended_untracked_selection_required, no mutation/authority/reviewer started. Eligible inventory sha256:9f876de719f7b1abb193f1f851f482e8d436c83cf3264eb5d5be3ce3af7e648d; projection workspace; empty base tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904. Native review remains pending, not approved. Select intended paths through its schema-bound input after the delivery decision; do not invent consent or authority.
L13 — Needs user decision before first work-unit commit: stacked-to-main vs feature-branch-chain. Recommend feature-branch-chain for integrating the completed MVP together. This decision does not authorize publishing, opening PRs, or remote operations. Preserve current verified diagnostic slice and continue the original ordered phases after that decision. Engram mirror/summary attempts continue to fail unknown_project; this local log is the recovery source.
L14 — Engram enabled at user's explicit request using engram init debugealo. .engram/config.json contains project_name debugealo; mem_current_project resolves by config with matching workspace; observation227 saved and read back successfully. Earlier unknown_project reports are historical, not current. No synthetic session registration used. The 52557-byte local feature document exceeds Engram's 50000-byte observation limit; full mirror remains pending rather than silently truncating it. Configuration and current verification state are separately persisted.
L15 — Latest stage validation with Docker running: full suite20 passed in2.43s, no skips; Ruff check clean; format --check17 files unchanged. This validates only the implemented foundation diagnostic slice; full MVP remains pending. User asks what else to validate; no additional implementation or delivery decision inferred.
L16 — User continuation (verbatim): Continua
L17 — Resume T2 inline: implement real container discovery/metadata and bounded historical/follow logs behind the existing local-only isolated SDK worker boundary. Reuse Settings endpoint guard and default_endpoint; never import Textual in core/Docker. No user-container mutations, remote access, publishing or delivery-strategy inference. Defer unresolved chain choice until before a commit. Existing version/doctor behavior must remain unchanged; focused tests RED→GREEN, full suite, differential smoke checks against an outside-workspace source snapshot. Risk items2 (local-only boundary) and4 (worker cancellation/reconnect). Independent verifier after own checks.

L18 — T2 implementation inline: real DockerService/isolated JSON-lines worker, full container and Compose metadata, containers/--json CLI, logs --follow/--tail, bounded multiplex and line decoder, ring buffer, state polling, inclusive replay counts, owned producer cancellation. No destructive app operations. Existing diagnostic protocol is unchanged.
L19 — RED observed: Docker service tests failed import before implementation. Subsequent focused checks reproduced dropped EOF records under backpressure, invalid width-wrapped JSON and initial stdout/stderr timestamp-skew loss. Fixed and pinned. Fixture integration initially assumed total cross-channel order; real Docker interleaving disproved it, so assertions now require per-channel order and complete records. Distinct test module names avoid pytest's default import-name collision.
L20 — 39 tests passed in8.45s, including real metadata/history and live stdout/stderr/cancellation through an isolated test-owned no-network fixture using a cached image; no pull or user-container mutation. Ruff clean. Final stopped-container EOF/packaging checks running. Docker SDK internal transport helpers intentionally preserve stream IDs and bound bodies; integration compatibility checked against installed SDK7.x and local Docker28.5.1. Bounded replay is not a durable exactly-once guarantee across daemon rotation/restarts. Risk: items2 and4; independent verification pending.
L21 — Final pre-verifier T2 checks:39 passed in11.00s; Ruff clean and format convergent; wheel/sdist built. Independent verifier launched on the full feature specs with a pre-T2 source snapshot for differential command checks. Commit and native review remain pending the user-owned delivery decision; no publication or authority is inferred.
L22 — The Engram observation limit cannot hold the verbatim specification twice plus its log. Preserve the FULL current document losslessly as gzip+base64 with its SHA-256 and repository locator under odd/debugpilot-mvp/tasks; verify decompression before save and blob equality after readback. This changes only the memory encoding, not specs or local file content. Future recovery must decode the envelope before reconciling with the local task file.

L23 — Engram mirror packing was lossless locally (full56475-byte document roundtrip, SHA-256 a0f5ff12ba909c3e44574863a35821cca4c7c9f998fc70709f2b5194c03484f2,16244 base64 chars), but mem_save failed with Transport closed; no saved mirror ID/readback exists and no successful full mirror is claimed. Cause unconfirmed. Local task file remains authoritative; restore MCP transport before resynchronizing. Last confirmed architecture observation241 records Docker implementation, not full task mirror.
L24 — Independent T2 verifier PASS: scratch39 tests passed with real Docker after approved pipe access. Additional real process, bounded-output, shutdown/backpressure/error, retry budget, replay multiplicity, API error classification and rejected-input hash probes passed. Existing version/doctor behavior matched pre-T2 snapshot for stdout/stderr/exit with normal input and sibling --json/--tail options. No blockers. Parent reran independent_probes.py successfully, including successful real doctor differential (exit0).
L25 — Durable regressions added for buffered producer-error delivery and retry/terminal budget. Final suite42 passed in11.62s, no skips; Ruff check clean; format converged; wheel and sdist built. Only tests/docs changed after independent source verification. Scope S3/S5/S6/S12/S13/S14/S16 verified for the Docker slice, not full MVP acceptance. T3 TUI and T4-T6 remain pending. No commits or native review approval; before the first commit user must select delivery/chain strategy. No remote operation or publication authorized. Risk: item2 local-only credential boundary; item4 async worker/producer/reconnect lifecycle.
L26 — Final readonly inventory confirms0 test-owned fixture containers. Parent verifier scratch and sidecar cleanup completed after removing mixed-ownership elevated pytest files under their matching identity. Pre-T2 source snapshot remains intentionally retained until work-unit commit/differential preparation is finished. Engram final session-summary save also failed Transport closed; all recovery notes remain in this local document.
L27 — Cleanup result verified: the verifier scratch root no longer exists; sidecar was removed earlier. The first L26 completion claim preceded its tool result; this observed result supersedes it.

L28 — User delivery decision (verbatim): si
L29 — Accepted the preceding explicit recommendation: use feature-branch-chain, with feat/debugpilot-mvp as local integration branch. No push, PR, merge or remote execution is authorized. Cache this decision; do not ask it again. Engram MCP transport remains closed, so configuration/mirror persistence is pending and this local log is authoritative.
L30 — Initial checkpoint is the first complete read-only local Docker exploration vertical (foundation + T2, code/tests/docs together) because there is no prior commit. One honest slicing pass: separating package, client and tests by file type would make an unexecutable intermediate unit. Keep the coherent root checkpoint, record its actual authored line count and recommend a PR size exception if ever publishing; do not distort code or repeatedly reslice to fit400 lines. Future TUI/DAP behaviors remain separate work units. Root checkpoint rollback boundary is the initial DebugPilot package/tests/docs; no previous application behavior or stored user data exists. Independent foundation and Docker verification already passed; recheck final candidate before commit. Native review is not yet approved.
L31 — Final initial checkpoint validation after delivery confirmation:42 tests passed in11.03s with real Docker, Ruff check clean and format24 files unchanged, wheel/sdist built. User-owned RDD mode is on (global). Stage only the inspected30 project/config/source/test/doc/lock paths; ignored tools/venv/dist/caches stay outside Git. No source-mutating normalizers may run after the native review freeze. This is the read-only Docker CLI vertical, not completed MVP/TUI acceptance.
L32 — Staged initial checkpoint:30 files,4672 added lines total,4057 excluding generated uv.lock;1981 lines are the full verbatim task specification/recovery log. Initial vertical remains larger than the400-line advisory. Preserve tests/docs/readability and report size:exception recommendation before any future PR publication; do not silently claim a <=400-line slice. Staged whitespace check passed. No ignored tool/cache/dist content staged.

L33 — Initial verified local checkpoint committed:1a5db56525816b1cf2c73d49136cb19639110397, feat(docker): add local container discovery and log streaming. Final count30 files/4673 added lines (4058 excluding uv.lock; task document1982 lines). No AI attribution, push, PR or merge. Branch feat/debugpilot-mvp is the local integration branch. This passive recovery update is intentionally not part of the committed candidate. Assess/review the immutable root checkpoint against Git's empty tree, explicitly excluding later working-tree recovery notes via committed-only selectors. Native review remains pending.
L34 — User candidate consent (verbatim): `granted`
L35 — Executed exactly the captured granted invocation for target sha256:ebb7c5cbc23486f513266a845f693fe6e1f3ada99effd58234bd3754222f8591, lineage review-56f68a01f9e078e3. Native START refused in preflight: gentle-ai.review-integration.failure/v2, code lens_context_budget_exceeded, next_action stop, mutation_outcome not_started, authority_applicability not_evaluated. Complete immutable reviewer evidence exceeds the native budget; no authority, reviewer result or receipt exists. Numeric budget was not provided. Do not retry this same candidate, truncate its evidence, abandon nonexistent authority, disable review, or claim approval.
L36 — Root cause of this workflow blockage: the initial grouping put the complete foundation/Docker code, tests, lockfile and duplicate verbatim specification into one oversized root checkpoint. Application tests remain last verified42 passed; this is not a Docker failure or a failed functional test. Parent owns the grouping decision. Next safe recovery is a smaller work-unit chain, requiring explicit user authorization before rewriting existing local integration history. Preserve current source, passive uncommitted tracking notes, and original commit.
L37 — Created and verified local backup ref backup/debugpilot-initial-checkpoint at1a5db56525816b1cf2c73d49136cb19639110397, without moving feat/debugpilot-mvp, changing source, publishing or repairing Gentle AI. Ask one focused history-reorganization authorization question, then stop. A reduced candidate needs a fresh provider-issued native next transition and its own candidate consent. The current granted invocation is not authority for a new candidate.
L38 — User authorization to reconstruct local history (verbatim): si
L39 — User resume request (verbatim): Continua
L40 — Reconstruction plan: preserve original backup and a complete current-tree snapshot (including pending task notes); keep .atl/ and ignored files untouched. Build a replacement commit chain using an external temporary Git index and immutable Git objects; do not delete/reset working-tree files. Units: passive specification; installable strict configuration library; bounded lifecycle/events; real local Docker diagnostics; diagnostic CLI; bounded log protocol; Docker service API; engine/CLI integration; reproducible dependency lock. Keep code/tests/docs for each behavior together and test each materialized checkpoint. Generated lock is isolated with its reproducible-install behavior, never truncated. Verify final blob/mode/path identity before atomically updating the integration ref under the explicit user permission. New scopes require new native preflight/consent, never reuse the failed root authority.

L41 — Reconstruction applied under user authorization without deleting/resetting/checking-out working-tree files. Integration HEAD ec3fb690da5b2b028b7d09f53719790d83b04880; final tree d8b48770428b7a614da4d7eb76d62f2377a4417f equals the full pre-reconstruction snapshot. Original backup/debugpilot-initial-checkpoint stays1a5db56525816b1cf2c73d49136cb19639110397; backup/debugpilot-before-history-split9dfe8e32ac256e431eaf6add1c4d76353f93d114 preserves pending notes. .atl remains untracked/untouched.
L42 — Runnable chain:035da675 specification (structural readback);25283394 core (12 tests);df5c421b doctor CLI (20);e11a94df log protocol (29);697af07b Docker API (38);6ee3eb33 engine/CLI (42);ec3fb690 dependency lock (42). Every runtime checkpoint built wheel/sdist offline. Changed lines1994/405/477/370/513/804/619 (last615 generated lock lines); disclose coherent overages and recommend size:exception before any future PR, never claim every slice is <=400 or truncate evidence.
L43 — Independent history audit PASS: exact seven-commit parent/ref/tree chain, both backups intact, all30 raw working-file hashes unchanged before/after tests, index identical to HEAD, ignored tooling/caches absent and .atl preserved. Auditor reran immutable core12 tests and final42 tests with real Docker (no skips) and offline build; no reconstruction-caused blockers. Parent reran audit.py successfully before these append-only recovery notes. This is not native review approval. Native review must now address new reduced candidates, not failed old target; TUI/DAP/example remain pending.
L44 — Core native review lineage review-da591098f52714df found R4-001 repeated cancellation interrupting asynchronous cleanup. Scoped fix committed as8ad25b2 in isolated core-review:13 Core tests passed; Ruff clean; wheel/sdist built. Targeted validator approved; exact acknowledge-approved returned gentle-ai.review-acknowledged/v1 action acknowledged, authority burned, target sha256:cd885f5adaa2b55207a583830db7166510dfe0023def778c07112018de528007. This closes only the reduced Core candidate. Non-blocking R3-001 oversized TOML integer conversion is a separate follow-up, not authority to expand this correction.
L45 — Same correction propagated without rewriting integration history; durable regression moved into tests/unit/test_foundation.py, because historical test_core_library.py was replaced by the doctor unit. Integration regression observed RED then GREEN. Ruff checks clean; full suite40 passed3 skipped (Docker daemon unavailable), so no claim of fresh real-Docker validation. Independent verifier PASS: baseline39/3, candidate40/3,10 lifecycle probes, CLI stdout/stderr/exit differentials unchanged. Parent reran lifecycle probes PASS. Existing source/test behavior otherwise retained; .atl untouched. Risk: item4 async cleanup and item3 shared engine lifecycle. Integration candidate needs its own assessment; isolated review is not approval of other Docker/history slices. TUI/DAP/example remain pending.
L46 — User integrated-candidate consent (verbatim): granted. Executed exact captured START for review-ca9c52d09225891f, committed-only target sha256:f3138f7e63034877596b5e51c5af4d00b6b7201bed0e410f5d975f2aeddbcd54, commit72dfaa3. Concurrent native resilience/reliability captures both returned no findings. Final admitted capture approved; exact acknowledge-approved returned acknowledged with authority burned, consumed revision sha256:9a4ed5bf72b41b8f469a7724b14301c9c7c0eb9a5521202b6df7a797f40f4d56. No trailing lifecycle action, no push/PR/merge. This closes only the integrated cancellation correction, not remaining Docker-history candidates or full MVP. Last functional evidence40 passed3 Docker tests skipped; TUI/DAP/example remain pending.
L47 — User resume request (verbatim): Continua. Clarification: ¿Querés que avance ahora con la TUI? User authorization (verbatim): Si. Advance T3 containers/logs/keyboard/error states; DAP, source navigation and debugger actions remain T4-T5, visibly unavailable rather than simulated. Prior Docker revalidation passed all3 integration tests with zero skips.
L48 — T3 route: parent writes inline because log controls and dashboard integration are dependent behaviors, not independent parallel writer units. Read-only explorer mapped public engine/list/stream/close APIs and existing LogBuffer. Keep engine/service/config unchanged; use bounded rendering and explicit UI stream ownership. Planned local work units: bounded log viewer with tests; dashboard/CLI with tests/docs. Forecast approximately700-1000 authored lines, feature-branch-chain retained, no publication. Risk: item4 switching/refresh/shutdown async ordering; item3 shared CLI dispatch. Independent verifier required after functional checks. CodeGraph initialization unavailable (access denied, then project recognition failed); filesystem fallback used. Test-first runner: .venv/Scripts/python.exe -m pytest; no downloads or image pulls.

L49 — S19/T7 added after user explicitly confirmed selected-service and whole-project Compose scope. Backend delegated in parallel with parent-owned TUI on disjoint surfaces. Worker own RED then12 GREEN; final cancellation delta initially unverified due mixed Windows TEMP ownership. Parent reran final14 backend tests successfully in a fresh same-identity temp root, including an additional real benign Python full-pipe cancellation regression (observed RED then GREEN). No real Compose lifecycle operation was executed.
L50 — T3/T7 current source checks:67 tests passed in16.53s, zero skips; real existing Docker integration fixtures passed; Ruff check/format clean after two UI string line wraps;11 CLI stdout/stderr/exit differentials identical to72dfaa3. New tests cover Pilot navigation/selection/visual pause/filter/search/copy, modal confirmation invalidation and background refresh; backend tests cover targets/files/credentials/exit/cancellation. Backend commit442eea9 (515 authored added lines) is a cohesive mutating operation boundary with its tests/docs; coherent overage disclosed, recommend size:exception before future publication. UI is the second coherent work unit; do not minify/drop tests to fit400. Independent verifier and native candidate consent remain pending; no approval/completion claimed. RDD is on(global); assessment needs explicit untracked inventory exclusion even with committed-only selectors.

L51 — Independent feature verification of immutable8a0fc8c: S5 PASS, scoped S7 PASS; S19 blockerB1 reproduced descendant-held stdout delaying.08s timeout to2.14s. One correction batch introduced owned helper: Windows kill-on-close Job Object before launching Docker, POSIX isolated process group. Commit719ed2e adds160/removes5 lines; backend16 tests pass including real benign Python descendants, timeout and exit7. Independent B1-only recheck PASS on immutable719ed2e: timeout.41s, cancellation.39s, normal exit.30s/exit7, all survival markers absent. Parent reran retained probe PASS (.44s/.00s/.27s). POSIX branch not executable on Windows; no claim of cross-platform runtime proof.
L52 — Final full suite initially68 passed/1 failed due a TUI test racing a timer (not a reproduced application regression). Replaced fixed sleeps with bounded awaits of observable states; focused5 tests GREEN. Final full suite69 passed in19.64s, zero skips. Ruff check/format clean;11 baseline CLI differentials unchanged. No new independent review sweep; B1 targeted recheck remains closed. UI unit8a0fc8c is1057 additions/7 deletions; one honest slicing pass retained coherent UI behavior/tests/docs, disclose overage and recommend size:exception before publication rather than dropping proof. All commits remain local; no push, PR, merge, install, pull or actual Compose mutation. Native review remains pending; do not describe functional proof as review approval.

L53 — User correction-candidate consent (verbatim): granted. Exact native START created review-faad03867384ef63 for targetsha256:2b63bcb54592fb62c721b6b96d45d88254fd13b05aed2b84501198107bc6003b (base8a0fc8c through24b561b;6files211lines). Four provider-issued captures launched concurrently in risk/resilience/readability/reliability order, all no findings. Last admitted capture approved; exact acknowledge-approved returned acknowledged/authorityburned at consumedrevision07e393b452609cc15cd07628fe8f5010c6fb8633027eeee35d7b8182090a759a. No further lifecycle action. Approval covers this correction only, not all TUI/backend/earlierDocker candidates. Functional proof remains69tests/zero skips; no source edits, realCompose operation or publication this turn. User screenshot launch error was copied PowerShell >> prompt text; parser verified ordinary ampersand invocation is valid.

L54 — User scope extension (verbatim): Necesito simular un caso necesito 3 proyectos separados, cada uno levante con docker compose sus propios servicios y que se comuniquen entre si a traves de red, entonces por proyecto deberian agruparse los servicios y deberia poder reiniciar la imagen sola o el grupo
L55 — Two independent multi-minute units run concurrently on disjoint surfaces: standalone lab fixture projects and grouped dashboard selection/action scope. Parent owns task document/git/.gitignore and one full seam suite. Forecast approximately800-1200 authored lines; existing feature-branch-chain retained; no push authorized for these new changes. Risk: item1 owned demo container recreation; item2 project/service mutation target isolation; item4 UI selection/stream cleanup; item5 fixture Docker builds/network. Deterministic behavior tests must observe RED before implementation. Existing reviewed engine/service/Compose executor remain unchanged. Live lab execution, if performed, must use explicit owned names and isolated local Docker configuration, no ambient credentials; require native permission before any image download or new containers.

L56 — User shortcut correction (verbatim): Si toco la letra r reinicia, si pongo shift r build de donde este parado
L57 — T9 scope updated before shortcut implementation; grouped-dashboard writer notified directly. r targets restart, Shift+R targets rebuild/recreate at selectedservice/group, both previewthenconfirm. Ctrl+R replaces previous logretry; inputtyping andmodalfocus guard preserved. T8 fixtureunit unchanged.

L58 — Writers returned within declared surfaces. T8 lab6 deterministic tests GREEN after6 RED failures; T9 grouping3 RED and shortcuts5 RED then19 focused UI tests GREEN. Parent integrated88 tests passed28.05s, zero skips; Ruff check/format clean45 files, diff whitespace clean. Parent corrected two test assumptions: environment keys case-normalize onWindows; group logstatus must be awaited after async stream cleanup. Docker Compose config--formatjson validated all3projects/6services/sharedexternalnetwork/loopbackonlyGateway.
L59 — Actual isolated Compose preflight exposed a pre-existing executor integration issue: stripping ProgramFiles/ProgramData prevented Docker from discovering installed systemplugins (unknowncommand). Preserving only these non-credential systempaths made Compose2.40.0 visible; targeted regression RED before fix, full88 suite GREEN after. No ambientcredentials orDockercontext restored. Python3.12-alpine baseimage absent; any livebuild/download must request explicitnativepermission. No newsource push authorized.
