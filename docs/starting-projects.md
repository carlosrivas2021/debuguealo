# Start a project from its Compose file

Use **Open Compose** (Ctrl+N), even when the inventory is empty. The terminal
browser starts in debugealo's working directory; expand directories or enter an
absolute directory/file path. **Up** navigates to the parent. Escape cancels
without inspecting configuration or changing Docker.

1. Open a trusted `.yaml` or `.yml` file. Its parent becomes the workspace;
   no path from a container label is opened automatically.
2. Keep **Start project**, then choose **Preview**. This runs only
   `docker compose --project-directory ... -f ... config --format json` to resolve
   Compose's declared/interpolated/default project name. It does not create containers.
3. Check the resolved name, whole-project/service scope and command. Only
   **Confirm & run** starts the project with `up -d --pull never`.

For the lab, choose `examples/multi-project/orders/compose.yaml`: its project
name is `dp-demo-orders`, not `orders`. Start the other lab projects separately;
see their lab README for the shared network prerequisite.

## Overrides and existing projects

The modal's **Browse Compose file** button replaces the base file and workspace.
Add further files manually, one per line, in override order. All files must remain
inside the selected workspace. Editing the form invalidates confirmation.
A dialog opened for an existing group/service refuses a file whose resolved
project name differs; open the general dialog to start another project.

**Start** does not force recreation or force a rebuild. Compose may build missing
service images; builds can still access networks or obtain base images.
**Restart** only restarts existing containers. **Recreate** forces replacement;
**Rebuild and recreate** additionally passes `--build`.

Only trust projects you control: configuration inspection reads `.env`, referenced
files and interpolation locally. Full configuration JSON is never displayed or
persisted. Missing CLI, invalid configuration and excessive output fail closed.
Starting/building requires the explicit confirmation; it is not a rollback-safe
operation. See [Compose safety and limitations](compose.md).
