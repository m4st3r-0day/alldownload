# Templates (`.etmpl`)

AllDownload reads the template format of **Extreme Picture Finder** (EPF). A template tells the app where to start, which pages to follow, which files to keep and how to name them. Templates are plain INI files.

- [Where templates live](#where-templates-live)
- [Compatibility check](#compatibility-check)
- [Supported sections](#supported-sections)
- [Custom parsers](#custom-parsers)
- [Built-in browser and API capture](#built-in-browser-and-api-capture)
- [AllDownload extension: `[PicFinderStart]`](#alldownload-extension-picfinderstart)
- [Python plugins](#python-plugins)
- [Writing and testing a template](#writing-and-testing-a-template)

## Where templates live

| Location | Use |
|---|---|
| `picfinder/templates/` | Bundled templates (empty: every supported site now has a Python plugin). |
| `<data folder>/templates/` | Templates you add (drag a `.etmpl` onto the window, or *Templates → Add template…*). |
| `$PICFINDER_TEMPLATES` | Extra folder, checked first. |

Templates can be switched off in the *Templates* window. The list of disabled templates is stored in `template_disattivati.txt` in the data folder.

When two templates match the same link, the most specific one wins: the one whose matching `StartingURLTemplates` expression is longest. A Python plugin marked `PREFERRED` always wins over a template for the same service.

## Compatibility check

Every template is checked when it loads. The *Templates* window shows the result:

| Mark | Meaning |
|---|---|
| ✓ Compatible | Everything the template uses is supported. |
| ◐ To be tested | It should work, with a note (for example: it needs the built-in browser). |
| ✗ Partial | It uses something not supported yet (listed in the details). |

Not supported yet:
- exploration modes other than `setRegular` (for example TGP);
- `ExplorationLimit` other than `selEntireSite` / `selNone`;
- naming modes other than original name or a tag attribute;
- subfolder modes other than `sfmNone` / `sfmParentURLRE`;
- `[$from-to$]` loops inside custom parsers;
- references to other parsers inside an `Expression`;
- header value types other than `chvtText` and `chvtCopyFromParent`.

## Supported sections

| Section | Support |
|---|---|
| `[Settings]` | `ManualLogin`, `ManualLoginMessage`, `MinDelayBetweenDownloads` / `MaxDelayBetweenDownloads`, `UseRandomDelayBetweenDownloads`, `SuggestedSimultaneousConnections`, `UseExplorationDepth` / `ExplorationDepth`, `ResolveNamingConflictsType`, `ConflictsRenameNumberOfDigits`, `SaveNamingType`, `UseMinFileSizeLimit` / `MinFileSizeLimit` / `MinFileSizeUnit`, `ParseErrorPages`, `DownloadTargetFilesFromExternalSites`. |
| `[StartingURLTemplates]` | Which links the template accepts (regular expressions). |
| `[TargetFiles]` | File masks to keep (`*.jpg`, `*.mp4`, …). A binary response counts as a target when its `Content-Disposition` name or URL name matches. |
| `[IncludedURLs]` / `[ExcludedURLs]` | Which links to follow. "Same site" means the same registrable domain. |
| `[CustomParsers]` | See below. |
| `[ExcludedPageParts]` | Parts of the page to ignore. An empty `From` means "from the start", an empty `To` means "to the end". |
| `[CustomHTTPReferers]` | `hrtCustomParser`, `hrtSimpleText`, `hrtCustomText`, `hrtNone`. |
| `[CustomHTTPHeaders]` | `chvtText` (fixed value) and `chvtCopyFromParent` (copied from the request the built-in browser made). |
| `[SubFoldersParentURLREs]` | Subfolders from the parent pages; the whole chain of parents is used. |
| `[TemplateSettings]` | `EncodedTitle` is shown as the service name. |

Resource tags (`img`, `script`, `link`, …) are never explored as pages, and streaming manifests (`.m3u8`, `.mpd`) are not followed unless the template targets them.

## Custom parsers

Each parser has an `Expression` (regular expression run on the page), an `Address` template and optionally `Post` data and a method.

**Group references in `Address`:**

| Syntax | Value |
|---|---|
| `[#n]` | Group *n* of the current match. |
| `[#k:n]` | Group *n* of the *k*-th match on the page. |
| `[#-k:n]` / `[#+k:n]` | Group *n* of the match *k* positions before / after. |

**Functions:** `jsonencode`, `jsondecode`, `urlencode`, `urldecode`, `htmldecode`, `lowercase`, `uppercase`, `base64decode`, `base64encode`, `hextodec`, `dectohex`. Example: `[#urlencode([#1])]`.

An address made only of `/` and `-` counts as "no address".

## Built-in browser and API capture

A template needs the built-in browser when it sets `ManualLogin=True` or uses `chvtCopyFromParent` headers. The browser then:

1. opens the starting link; the user signs in or solves a check;
2. records every `fetch` / `XHR` request the page makes (URL, method, headers, body, status, response);
3. hands the rendered page, the recorded requests and the cookies to the crawler when the user presses *Continue download*.

The crawler reads the recorded responses first, without sending them again. It only follows non-target links from the rendered page when they match `[IncludedURLs]`. That keeps it from crawling every thumbnail and script of a modern web app.

Downloads use the same User-Agent as the browser, so cookies issued by anti-bot checks stay valid.

## AllDownload extension: `[PicFinderStart]`

EPF ignores sections it does not know, so this is safe to add to any template. It rewrites the pasted link into the real starting address (for example an API):

```ini
[PicFinderStart]
Expression000=pixeldrain\.com/l/([A-Za-z0-9]+)
Address000=https://pixeldrain.com/api/list/[#1]
PasswordParam000=password
```

If the user types a password, `PasswordParam` adds it as a query parameter.

## Python plugins

Some services work better with a few lines of Python than with a template. Plugins live in `picfinder/plugins/` and expose:

```python
NAME = "pixeldrain (API)"
PREFERRED = True            # wins over a template for the same service

def match(url: str) -> bool: ...

async def list_files(client, url, password=None):
    yield RemoteFile(url=..., name=..., subdir=..., size=...)
```

Site-specific fixes that a template cannot express (for example Bunkr's link decoding) live in `picfinder/sitehooks.py`.

## Writing and testing a template

Open *Tools → Template editor* (Cmd/Ctrl+E):

1. Pick a template or start a new one.
2. Paste a test link and press **Test**: you get the files found and the full log (every request, every skipped link and why).
3. **Save** writes to your template folder.

Templates that need the built-in browser cannot be tested in the editor; test them from the main window with the log set to *Detailed*.
