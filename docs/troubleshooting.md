# Troubleshooting

First step, always: open the **Log** tab, tick **Detailed**, try again. The full log of every session is also saved in the log folder (*File → Open logs folder*).

- [No files found](#no-files-found)
- [Errors 403 on every file](#errors-403-on-every-file)
- ["Too many requests" (429)](#too-many-requests-429)
- [The built-in browser stays blank](#the-built-in-browser-stays-blank)
- [Cloudflare "are you human?" fails (600010)](#cloudflare-are-you-human-fails-600010)
- [Downloads look slow](#downloads-look-slow)
- [Previews of videos don't show](#previews-of-videos-dont-show)
- [The app crashed](#the-app-crashed)
- [Known issues](#known-issues)

## No files found

- Under the link box, check the service is recognised. "No active template recognises this link" means no template matches: add one, or switch on *All file types*.
- If the site needs a login, press **Browser**, sign in, wait for the content, then **Continue download**.
- When a search finds 0 files, the first pages it read are saved in `log/pagine/`. Opening them shows whether the site changed its layout.
- In the log, look at lines starting with `- scartato` (skipped): they say why each link was ignored, for example *excluded by [ExcludedURLs]* or *other site*.

## Errors 403 on every file

- **Links tied to one IP.** Some CDNs sign file links for the IP that asked for them (the built-in browser). AllDownload detects this, downloads those files without the proxy, and retries refused ones through the built-in browser. The log line shows both IPs. Use the same connection (VPN on or off) for both browsing and downloading.
- **Expired links.** Signed links last a limited time. AllDownload offers to search again before downloading.
- **Old cache.** The built-in browser keeps its HTTP cache only in memory and clears it every time it opens, so every search gets fresh links.

## "Too many requests" (429)

The app already slows down: fewer connections to that server, the pause the server asks for, and after repeated refusals a 15-minute pause for that server only. If it keeps happening:

- *Settings → Downloads → Pauses between files:* choose *As the template says*.
- Lower *Per server*.
- Check *Tools → Statistics → Requests today*: many sites have a daily limit.

## The built-in browser stays blank

- Press **Clear data** in the browser (logins are deleted too), then reload.
- Close the app completely (Cmd+Q) and open it again: a browser profile can stay locked by a crashed process.
- If the page works in your normal browser but never here, the site may refuse embedded browsers.

## Cloudflare "are you human?" fails (600010)

- The built-in browser uses its real engine name (User-Agent) so the check sees consistent information.
- When Turnstile reports a failure, AllDownload reloads the page without its request capture so the check runs on an untouched page. Complete it, then capture switches back on.
- If it still fails, wait a few minutes, use your normal network (not a proxy or VPN), and try again. AllDownload does not try to trick these checks.

## Downloads look slow

- With *adaptive connections* the app starts with few connections per server and adds more while the server answers well. The limit it reaches is remembered.
- The template's pause between files is often the real limit. *Pauses between files → Halved* is faster but riskier.
- All files on one server share that server's limit; several sites download in parallel.
- *Schedule & limits* may be holding downloads: download hours, battery, or bandwidth share.

## Previews of videos don't show

Video frames need **ffmpeg** (`brew install ffmpeg` on macOS). If ffmpeg is installed somewhere unusual, set its path in *Settings → Previews*. Sites that give their own thumbnails work without it.

## The app crashed

- Look at `crash.log` in the log folder: it contains the Python and Qt traceback.
- Open an issue with that file and the session log. Remove personal links first.

## Known issues

- **OnlyFans / Fansly with proxies:** file links are bound to the IP of the built-in browser, so proxies cause 403 errors and timeouts. Use the direct connection; with a VPN keep the same server for the whole search and download.
- **Bunkr:** the gallery API only lists photos, so every video still needs its own file page (about 1–3 s per file depending on the pause setting).
- **OnlyFans:** videos available only as protected streams (DRM) are not downloaded. Pay-per-view content you have not bought is not available.
- Packaged builds: macOS (Apple Silicon) and Windows from GitHub Releases; Linux runs from source. The Mac app is not notarized: right-click → Open the first time.
- Changing language or theme needs a restart.
