# Contributing

Thanks for helping. Bug reports, templates and code are all welcome.

## Reporting a bug

Please include:

1. what you did and what you expected;
2. your system (macOS / Windows / Linux and version) and the app version (*About AllDownload*);
3. the session log with **Detailed** on (*File → Open logs folder*), and `crash.log` if the app crashed.

**Before attaching logs, remove anything private:** personal links, usernames, cookies, tokens. Proxy passwords are already masked, but check anyway.

## Templates

- New or fixed `.etmpl` templates are welcome. Test them in *Tools → Template editor* first.
- Say which links you tested and what the template finds.
- Only templates you wrote yourself or are allowed to share.

## Code

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

- Keep pull requests small and focused, with a test for new behaviour.
- Interface text is written in Italian in the code; add the English text to `picfinder/lang_en.py`.
- Comments are short and say *why*.

## What will not be accepted

AllDownload stays polite and honest with the sites it talks to. Changes that do any of the following will not be merged:

- bypassing DRM, encryption or paywalls;
- rotating proxies or identities to get around rate limits or bans;
- faking browser fingerprints or solving captchas automatically;
- parsers for sites that host leaked or pirated content.
