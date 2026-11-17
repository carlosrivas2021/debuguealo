# Security policy

## Supported versions

Security fixes go into the latest release. Upgrade with:

```sh
uv tool install --reinstall git+https://github.com/carlosrivas2021/debuguealo
```

## Reporting a vulnerability

Please report vulnerabilities **privately**, through GitHub's
[private vulnerability reporting](https://github.com/carlosrivas2021/debuguealo/security/advisories/new)
(the **Security** tab → **Report a vulnerability**). Do not open a public issue for them.

Include what you found, how to reproduce it, and the debugealo version
(`debugealo version`). You should get a first answer within a week.

## Scope

debugealo is a local tool. It is designed to:

- talk only to a local Docker daemon (a Unix socket or a Windows named pipe, never a remote
  endpoint);
- listen for debug adapters on `127.0.0.1` only;
- ask before destructive actions and before downloading images;
- never write the user's `launch.json` on its own.

Reports that break one of these guarantees are especially welcome. The debuggers it drives
(debugpy, Delve, Node's inspector) can run any code in the debugged program, by design;
that is not a vulnerability in debugealo.
