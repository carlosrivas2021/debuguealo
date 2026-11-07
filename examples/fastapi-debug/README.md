# FastAPI debug example

A small payment API in Docker for trying Python attach. `debugpy` runs inside the container,
and both ports are published on host loopback only. Anything that can reach the debug port
can run code in the container, so keep this example local and disposable.

## Start it

```console
docker compose -f examples/fastapi-debug/compose.yaml up --build -d
```

Set `FASTAPI_DEBUG_API_PORT` or `FASTAPI_DEBUG_DAP_PORT` if 8000 or 5678 is already in use.

## Attach from Code

Add this profile to Code's central `projects/launch.json`, using the absolute path of this folder:

```json
{
  "name": "FastAPI example",
  "workspaceFolder": "/absolute/path/to/examples/fastapi-debug",
  "pythonAttach": {
    "host": "127.0.0.1",
    "port": 5678,
    "remoteRoot": "/workspace"
  }
}
```

1. In **Code**, select the profile and open `app/payments.py`.
2. Mark a breakpoint inside `process_payment`, then press **Shift+F5**.
3. Send a payment:

   ```console
   curl -X POST http://127.0.0.1:8000/payments -H 'Content-Type: application/json' \
     -d '{"amount_cents": 1000, "currency": "EUR", "card_token": "tok_ok"}'
   ```

4. Inspect `payment` and the stack, step with **F10**, then **Continue**.
5. Press **Disconnect**. The API keeps running and the same profile can attach again.

A connection that closes without attaching, such as a port probe, can end the `debugpy`
listener. If attach is refused afterwards, recreate the container from **Containers**.

## Endpoints

| Request | Result |
| --- | --- |
| `GET /health` | `200` with `{"status": "ok"}` |
| `POST /payments` | `200` with the settlement |
| `POST /payments` with `"card_token": "tok_declined"` | `402` card declined |
| `POST /payments` with a non-positive amount or unsupported currency | `422` rule rejected |
| `POST /payments` with a missing field | `422` request validation |
| `GET /debug/error` | `500` from an intentional exception |

## Clean up

```console
docker compose -f examples/fastapi-debug/compose.yaml down --rmi local
```
