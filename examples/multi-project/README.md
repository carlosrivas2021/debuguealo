# Three independent Compose projects

Each of `gateway/`, `orders/`, and `catalog/` is a self-contained project with an API,
a worker, distinct API/worker image tags and its own Compose lifecycle. There is no shared build context.
The projects communicate through the explicit `debugpilot-demo-shared` Docker network.

Follow the [lab walkthrough](../../docs/multi-project.md) for startup, the observable
request chain, single-service versus whole-project actions, environment changes and cleanup.
No lab resources start merely by importing or opening these files.
