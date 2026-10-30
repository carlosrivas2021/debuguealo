# Explicit container stop

Stop is an explicit, confirmation-gated operation for a selected container or a
selected Compose group. The confirmed request pins the exact container IDs or names;
inventory changes do not silently retarget it. It works independently of saved launch
profiles, including for manually started containers.

Select a container or project header, then press **s** or click **Stop**. Review the
pinned scope in the inline bar and press Enter to confirm, or Escape to cancel.
Groups include their active services only and are limited to 32 targets per request;
select an individual service for larger groups. No launch profile is required.

## What stop does

- Sends one bounded stop request per selected target, continuing after an individual
  failure and reporting each observed result.
- Does not remove containers, images, volumes, networks, or Compose configuration.
- Is separate from **Stop CLI**, which cancels only a local DebugPilot worker process.
- While a real stop is running, **Cancel wait** stops waiting locally; it does not
  undo requests already sent to Docker.
- Does not retry a stop request. If the local worker is cancelled or disconnects after
  sending a request, unreported targets have an unknown outcome; inspect their state.

The stop grace period is 1–30 seconds. Docker may force a container to exit after that
period. Use fake Docker boundaries in automated tests; real stop checks require explicit
authorization for the exact local container targets.
