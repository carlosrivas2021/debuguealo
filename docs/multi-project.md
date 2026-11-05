# Test three independent Compose projects

This disposable lab creates **three projects and six containers**. Each project has
an `api` and a `worker`, its own build context and its own Compose file. You can copy
each directory into a separate repository without changing its source layout.

| Project directory | Compose project | API alias on shared network | Calls |
| --- | --- | --- | --- |
| `examples/multi-project/gateway` | `dp-demo-gateway` | `dp-demo-gateway-api` | Orders |
| `examples/multi-project/orders` | `dp-demo-orders` | `dp-demo-orders-api` | Catalog |
| `examples/multi-project/catalog` | `dp-demo-catalog` | `dp-demo-catalog-api` | None |

All three attach to the external bridge `debugpilot-demo-shared`. Explicit unique
aliases avoid collisions between the three services all named `api`. Workers poll
their project's `/flow` endpoint every five seconds and retry while dependencies start.
Only Gateway publishes a host port, on **127.0.0.1:18080** by default. No Docker socket,
host source mounts, credentials or persistent volumes are exposed to these containers.
The standard-library servers are disposable examples, not production HTTP servers.

## Start the lab

Run these commands from the debugealo repository root. The Docker commands work in
PowerShell and POSIX shells; do not copy prompt markers such as `PS>` or `$`.
Docker Engine and Compose v2 must be available. The first build may download the public
`python:3.12-alpine` base image. That is installation activity, not an offline-runtime claim.

First check that the reserved lab names are not being used by something else:

```console
docker ps -a --filter label=io.debugpilot.demo=multi-project
docker ps -a --filter label=com.docker.compose.project=dp-demo-gateway
docker ps -a --filter label=com.docker.compose.project=dp-demo-orders
docker ps -a --filter label=com.docker.compose.project=dp-demo-catalog
docker network inspect debugpilot-demo-shared
```

If a reserved project name already exists, verify that its containers belong to your
previous demo and have `io.debugpilot.demo=multi-project`; otherwise stop and do not run
the lab commands against them. An absent network is expected on the first run. If it exists,
verify that it is your
previous lab network and has the label below; do not reuse an unrelated network. Then
create it **only if absent**, and start each project independently:

```console
docker network create --label io.debugpilot.demo=multi-project debugpilot-demo-shared
docker compose -f examples/multi-project/catalog/compose.yaml up --build -d
docker compose -f examples/multi-project/orders/compose.yaml up --build -d
docker compose -f examples/multi-project/gateway/compose.yaml up --build -d
```

The `name:` in each Compose file fixes project identity regardless of the shell's current
directory. API and worker build their project's context into distinct image tags,
avoiding concurrent exports to the same tag. API health checks
check `/health`; a healthy Gateway API does not imply its upstream services are ready.

From the repository root, request the full chain:

```console
uv run python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:18080/flow', timeout=10).read().decode())"
docker compose -f examples/multi-project/gateway/compose.yaml logs --tail 20
```

Expected JSON includes `"chain": ["gateway", "orders", "catalog"]`. Every `hops` entry
contains the project's marker, a startup timestamp and a unique API instance ID.
Workers log `worker_poll` with the same chain; `worker_retry` or HTTP 502 means an
upstream is not available yet. Requests never rely on the host's proxy environment.

## Select a service or its group in debugealo

Start `uv run debugealo`. Look for `dp-demo-gateway`, `dp-demo-orders` and
`dp-demo-catalog` project groups, each containing its API and worker. A container's
Compose service identity (`api` or `worker`) is different from its generated name.

Select the service or project, then press **Ctrl+O**. Configure the explicit **absolute
workspace directory for that project**, its project name from the table above, and
`compose.yaml` as the file. Choose selected-service or entire-project scope, then
**Preview** and **Confirm & run**. Discovery and selection alone never run an operation.
Files must remain inside the selected workspace. Keep the three workspace directories
and project names paired correctly; a group is a Compose project, not the shared network.
For contextual actions, press **r** to request restart or **Shift+R** to request
rebuild/recreate at the selected service or group. Both still require Preview and
Confirm & run. **Ctrl+R** retries the selected log stream instead.

For example, to restart just Orders API from a terminal:

```console
docker compose -f examples/multi-project/orders/compose.yaml restart --no-deps api
```

To restart its entire two-service group:

```console
docker compose -f examples/multi-project/orders/compose.yaml restart
```

Those commands do not restart Gateway or Catalog even though all projects use the same
network. During an Orders restart, Gateway may return a temporary 502; workers retry.

## Observe the scope of the change

Before and after an action, collect the container IDs and their start times. Commands
below use Compose project labels, not a potentially ambiguous short service name:

```console
docker ps -a --filter label=com.docker.compose.project=dp-demo-orders --format "{{.ID}} {{.Names}}"
docker ps -a --filter label=com.docker.compose.project=dp-demo-gateway --format "{{.ID}} {{.Names}}"
docker ps -a --filter label=com.docker.compose.project=dp-demo-catalog --format "{{.ID}} {{.Names}}"
docker inspect --format "{{.Name}} {{.State.StartedAt}} {{.RestartCount}}" CONTAINER_ID
```

Replace `CONTAINER_ID` with each ID from the listings; it is a placeholder, not a literal
argument. A manual restart changes `StartedAt` but need not increment `RestartCount`,
which tracks automatic restarts. For a single Orders API restart only that container's
start time should change. For the group restart Orders API and worker should change;
Gateway and Catalog should retain their start times. Recreation may also change IDs.
The API `/health` and `/flow` instance IDs provide a second observable startup signal.

## Change environment or rebuild source

Each project includes `.env.example` with a harmless `APP_MARKER`. Copy it to `.env`
**inside that project's directory**, then change the marker. Use a file manager, or
`cp .env.example .env` in a POSIX shell / `Copy-Item .env.example .env` in PowerShell.
Do not put real secrets into the demo or commit `.env` files.

**Restart keeps the existing environment.** Use Recreate in debugealo, or:

```console
docker compose -f examples/multi-project/orders/compose.yaml up -d --force-recreate --no-deps api
```

Then `/flow` should show the new Orders API marker while Catalog/Gateway are unchanged.
To apply source/Dockerfile changes, choose Rebuild and recreate, or:

```console
docker compose -f examples/multi-project/orders/compose.yaml up --build -d --force-recreate
```

debugealo additionally uses `--pull never` for service images; its **Rebuild** action
can build the local service image. Builds can still obtain base images or use networks.
Read [Compose safety and limitations](compose.md) before using non-disposable projects.

## Remove only this lab

Stop the three explicitly named projects first. Do not add `-v`, `--rmi`, or prune commands:

```console
docker compose -f examples/multi-project/gateway/compose.yaml down
docker compose -f examples/multi-project/orders/compose.yaml down
docker compose -f examples/multi-project/catalog/compose.yaml down
docker network inspect debugpilot-demo-shared
```

Remove the network only after confirming it has the `io.debugpilot.demo=multi-project`
label and no remaining attached containers:

```console
docker network rm debugpilot-demo-shared
```

The external network is not removed by any project's `down`. Demo images remain cached;
no existing user application, volume, unrelated network or image is targeted by cleanup.
