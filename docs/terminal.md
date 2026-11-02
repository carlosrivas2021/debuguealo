# Embedded terminal

The terminal backend starts no shell automatically. A host session requires Bash to be present on `PATH` (`bash` on POSIX, `bash.exe` on Windows) and an existing working directory. Host Bash is launched interactively without loading user startup files. POSIX sessions use a pseudo-terminal; Windows uses the optional pywinpty/ConPTY adapter. Native Windows execution was not available for this implementation, so Windows behavior is not claimed as verified.

A container session requires a running container whose identifier is the full 64-character Docker ID, a local endpoint accepted by the shared `Settings` validator (local Unix socket or local Windows named pipe), the Docker CLI, and an existing local working directory for the Docker CLI process. The local working directory is not passed as a container `--workdir`; the container's configured working directory is retained. The CLI is invoked with an argument array and an explicit `--host`. No real Docker session is started by the unit tests.

## Container execution isolation

- Container exec removes inherited `DOCKER_*` overrides, including case variants, without changing the parent process environment.
- Each container session gets its own empty temporary `DOCKER_CONFIG` directory. Both POSIX and ConPTY receive that environment, so exec does not fall back to the host user's Docker configuration, credentials or saved contexts. The user's configuration files are not modified.
- The temporary configuration is released after failed or cancelled startup, normal EOF, and explicit session close.
- Host Bash keeps its normal inherited environment. This isolation applies to the container-exec client, not to commands the user chooses to run in the host shell.

Adapter tests use fake processes for POSIX and Windows. They check argument/environment forwarding and configuration lifetime; they do not establish native Windows/ConPTY behavior or Docker connectivity.

Rows and columns are clamped to the supported range. Output is UTF-8 decoded incrementally so multibyte characters can span reads. Closing a session terminates the session process group, reaps the child when possible, closes the pseudo-terminal and cancels its reader. An optional `on_exit` callback is synchronous, accepts no arguments, and is intended to notify a caller once after an opened session has ended or been closed. Callers should still close sessions during teardown.

Bash, Docker, and native terminal availability depend on the host installation and platform. The container shell is `/bin/sh`; no host shell is substituted inside a container. Unsupported or invalid endpoint and container state requests fail before Docker execution.
