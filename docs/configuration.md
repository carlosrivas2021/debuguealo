# Local settings

Use `load_settings(Path(...))` from `debugpilot.storage.config`. Missing files use defaults without writes; invalid/oversized TOML is rejected without echoing values. Remote endpoints are rejected.

Configuration is at most64KiB; event capacity1–10000; Docker request timeout1–30seconds. No Docker connection is made by loading settings. The CLI arrives in the next unit.
