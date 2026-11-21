# Security and privacy

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's **private vulnerability reporting** on this repository ("Security" tab → "Report a vulnerability").

## What AllDownload stores

Everything stays on your computer, in the data folder (see the [user guide](docs/user-guide.md#where-your-data-is)). Nothing is sent to the authors.

| Data | Where | Notes |
|---|---|---|
| Settings | `settings.json` | **Includes proxy passwords and proxy list links in plain text.** |
| Logins of the built-in browser | `browser/` | Cookies of the sites you sign in to. |
| History, projects | `picfinder.db` | Links and file paths. |
| Logs | `log/` | Links you opened. Proxy passwords are masked. |

Keep these files out of backups you share and out of git (the provided `.gitignore` already excludes them).

## Network

- AllDownload connects only to the sites you give it, to the proxies you configure, and to a speed-test address when you test proxies.
- When a link is tied to one IP, the app may ask a public "what is my IP" service (ipify, icanhazip, ifconfig.me) to explain the error in the log.
- Proxy operators can see your traffic. Use proxies you trust.
