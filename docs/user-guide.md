# User guide

[Italiano](guida-utente.md)

- [The window](#the-window)
- [Download from a link](#download-from-a-link)
- [Projects](#projects)
- [The built-in browser](#the-built-in-browser)
- [Folders and duplicates](#folders-and-duplicates)
- [Pause, resume, queue](#pause-resume-queue)
- [Settings](#settings)
- [Proxies](#proxies)
- [Send links from your browser](#send-links-from-your-browser)
- [Tools](#tools)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Where your data is](#where-your-data-is)

## The window

![Main window](images/main-en.png)

| Area | What it does |
|---|---|
| **Sidebar** | Saved projects (by category), *Quick download*, and at the bottom: active templates, network status, settings. |
| **Links** | Paste one or more links, one per line. Under the box you see which service each link belongs to. |
| **Options** | Project name and category, password (for protected links), destination folder, and two switches: *Download everything right away* and *All file types*. The options close while a search runs, to leave room for the list. |
| **Results** | Counters (found, selected, downloaded, already there, errors), the progress bar, the file list with preview, and the **Log** tab. |

## Download from a link

1. Paste a link (or drag it onto the window) and press **Enter** or **Find files**.
2. Files appear while they are found. Click one to see its preview.
3. Choose files: tick boxes, or use **All / None / Images / Videos**, or type in the filter.
4. Press **Download N files**.

**Download everything right away:** with this switch on, files start downloading as soon as they are found, without the selection step.

**Status column:**

| Status | Meaning |
|---|---|
| To download | Ticked, waiting. |
| Already downloaded | You downloaded it before (even if the link changed). Unticked. |
| Done | Saved. |
| Already there | A file with the same name and size is already in the folder. |
| Duplicate | The same photo already exists with another name. |
| Retry N | The server was slow or busy: trying again. |
| Error | Not saved. Look at the **Log** tab for the reason. |

## Projects

A project remembers links, destination folder and options.

- **Save:** open *Options*, type a name (and a category if you like) and press **Save project**. Shortcut: Cmd/Ctrl+S.
- **Update:** select one or more projects (or a whole category) and press **Update**. Only new files are downloaded.
- **Right-click a project:**
  - **Queue priority:** high, normal or low. When several projects are updated, high priority goes first.
  - **Check automatically:** every hour, 6 hours, 12 hours or every day. The check runs only when the app is idle. Watched projects show an eye icon.

## The built-in browser

Some sites need a login, a token, or an "are you human?" check. The template says so, and the browser opens on its own. You can also press **Browser**.

1. Sign in if needed.
2. Wait until the content shows. Use **Auto-scroll** or scroll yourself to load more (galleries, chats).
3. Press **Continue download**.

The browser hands the page, its API requests and its cookies to the downloader. Logins are kept for next time.

- **Home** brings you back to the starting link (useful after a login that lands elsewhere).
- **Clear data** deletes cookies and saved data of the built-in browser, logins included.
- **Cloudflare "are you human?":** if the check fails, AllDownload reloads the page without its request capture. You complete the check, then capture turns back on.

Some sites sign their file links for one IP address: the one of the browser. If a download through a proxy gets refused for that reason, AllDownload downloads those files directly or through the built-in browser itself.

## Folders and duplicates

Default layout (*Settings → Downloads → Folders*):

```
AllDownload/
  mario/            ← one folder per link: profile, album, folder
    Foto/
    Video/
    Chat/           ← OnlyFans chat gallery of this user
      Foto/
      Video/
  _Doppioni/        ← only if "Move to _Doppioni" is chosen
```

**Duplicates** (*Settings → Downloads → Duplicates*):
- *Don't download files again:* every downloaded file is remembered by a stable key, so it is recognised even when the site re-signs the link. If you delete a file from disk, it is downloaded again next time.
- *Same photos with a different name:* off, mark as "Duplicate", or move to `_Doppioni`. Uses an image fingerprint, so resized copies match too.
- *If the name already exists:* skip if same size, don't save, save as `name_001`, or overwrite.

## Pause, resume, queue

- **Pause** (button next to the counters, or Cmd/Ctrl+P): parts already downloaded are kept. **Resume** continues from there.
- If you close the app during a download, the next start asks whether to resume.
- Expired links: some sites sign links for a short time. Before downloading, AllDownload checks this and offers to search again and download the same files.

## Settings

Open with Cmd/Ctrl+, or the sidebar.

| Page | Main options |
|---|---|
| **General** | Language, theme, default folder, notifications. |
| **Downloads** | Files at once, per server, adaptive connections, parts for large files, HTTP/2, pauses between files (as the template says / halved / minimal), speed limit, retries, timeout, folders, duplicates. |
| **Schedule & limits** | Download only between two times, pause on battery, bandwidth share (e.g. 70% of your line), daily request warning per site, how often watched projects are checked. |
| **Network & proxies** | Proxy mode and list, test address, custom User-Agent. |
| **Previews** | Automatic thumbnails, maximum preview size, ffmpeg path. |
| **Built-in browser** | Auto-continue time in queues. |
| **Log** | Detailed log in the window, how many log files to keep. |

Language and theme apply after restarting the app.

![Settings](images/settings-en.png)

## Proxies

*Settings → Network & proxies.*

- **Add…** accepts one proxy per line: `http://host:port`, `socks5://user:password@host:port`, or `ip:port:user:password`.
- **List from link…** loads a list from a URL (for example the Webshare download link). It reloads at every start.
- **Test all** measures every proxy. Mode *fastest that answers* uses the quickest one.
- If a proxy stops answering, the next one is used. If a **site** refuses (403/429), the proxy is not changed: the app slows down instead.

Passwords are hidden in the window and in the log. Whoever runs a proxy can see your traffic: use proxies you trust.

## Send links from your browser

*Tools → Send to AllDownload from the browser…*

- **Bookmarklet** (Safari, Chrome, Firefox): create a bookmark and paste the given text as its address. Click it on any page: the link arrives in AllDownload.
- **Chrome extension** (Chrome, Edge, Brave): load the `extension/` folder from `chrome://extensions` → *Developer mode* → *Load unpacked*. It adds "Send to AllDownload" to the page and link menus.

Both use `alldownload://` links, which work with the installed macOS app.

## Tools

- **Statistics** (Cmd/Ctrl+I): files and space by site, today's requests, errors, and the connection limits learned for each server.
- **Template editor** (Cmd/Ctrl+E): open, edit and test a template on a link, with the full log. Bundled templates are saved as a copy among yours.
- **Templates** (Cmd/Ctrl+T): every template with service, type, compatibility and an on/off switch.

## Keyboard shortcuts

| Action | macOS | Windows / Linux |
|---|---|---|
| Find / download | Enter or ⌘↩ | Enter or Ctrl+Enter |
| Paste | ⌘V | Ctrl+V |
| Built-in browser | ⌘B | Ctrl+B |
| Save project | ⌘S | Ctrl+S |
| New project | ⌘N | Ctrl+N |
| Pause / resume | ⌘P | Ctrl+P |
| Templates | ⌘T | Ctrl+T |
| Template editor | ⌘E | Ctrl+E |
| Statistics | ⌘I | Ctrl+I |
| Settings | ⌘, | Ctrl+, |
| Open downloads folder | ⇧⌘D | Ctrl+Shift+D |

## Where your data is

| | macOS | Windows | Linux |
|---|---|---|---|
| Base folder | `~/Library/Application Support/PicFinder` | `%APPDATA%\PicFinder` | `~/.local/share/PicFinder` |

Inside the base folder:

| File / folder | Content |
|---|---|
| `settings.json` | Settings (proxy passwords included). |
| `picfinder.db` | Projects, download history, request counters, image fingerprints. |
| `templates/` | Templates you added. |
| `browser/` | Built-in browser profile (logins). |
| `log/` | Session logs, `crash.log`. |
| `limiti_siti.json` | Connection limits learned per server. |
| `pagine.sqlite` | Saved copies of pages (for faster updates). |

The folder is still called `PicFinder`, the project's original name, so existing data keeps working. Its exact paths are shown in *About AllDownload*.
