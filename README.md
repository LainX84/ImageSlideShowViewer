<p align="center"><img src="docs/icon.png" width="96" alt=""></p>

<h1 align="center">Image SlideShow Viewer</h1>

<p align="center">
An ACDSee-style image viewer for Windows: folder tree and thumbnail browser, full-screen viewer,
a slideshow that jumps from one folder to the next, CBZ/ZIP comic archives and batch operations.<br>
<b>English</b> · <a href="README.it.md">Italiano</a>
</p>

---

## Features

- **Browser** with folder tree and thumbnail grid (thumbnails cached on disk), natural sort by name, date or size.
- **Viewer** with fit-to-window / 100% / zoom, EXIF auto-rotation and animated GIF/WebP.
- **Slideshow** with interval, random order, loop and subfolders; **↓ / ↑ jump to the next / previous folder** while it runs.
- **CBZ / ZIP archives** shown as folders with their cover, readable like comics.
- **Batch rename** modelled on ACDSee: template, search and replace, case change, insert text, remove text, strip spaces, with live preview.
- **Batch convert** to JPEG, PNG, WebP, BMP or TIFF, with quality and resizing.
- **Copy / move / delete** (to the Recycle Bin) of files and folders.
- **Explorer context menu**: right-click a folder, an archive or an image to start a slideshow, rename or convert.
- **Network shares**: type `\\192.168.0.2` to list the shared folders of a computer.
- **English and Italian** interface, selectable from the menu.

## Requirements

- Windows 10 or 11 (it also runs on Linux and macOS, without the Windows-only parts)
- Python 3.10 or newer
- [PySide6](https://pypi.org/project/PySide6/) 6.5 or newer

## Installation

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/) and tick *"Add Python to PATH"*.
2. Download or clone this repository.
3. Double-click **`image_slideshow_viewer.pyw`**. On first run it offers to install PySide6 (1–2 minutes), then opens the program. A `.pyw` file does not open a console window; if something goes wrong you get an error message and the details in `image-slideshow-viewer-error.log`.

From a terminal:

```
pip install -r requirements.txt
python image_slideshow_viewer.pyw                 (opens the browser)
python image_slideshow_viewer.pyw D:\Photos       (opens the browser on a folder)
python image_slideshow_viewer.pyw photo.jpg       (opens the viewer directly)
python image_slideshow_viewer.pyw comic.cbz       (opens the archive like a comic)
python image_slideshow_viewer.pyw --slideshow D:\Photos D:\Comics\vol1.cbz
python image_slideshow_viewer.pyw --rename  file1.jpg file2.jpg …
python image_slideshow_viewer.pyw --convert file1.png file2.png …
```

### Building an .exe and making it the default photo viewer

1. Double-click **`build_exe.bat`**. It creates `dist\ImageSlideShowViewer\` with `ImageSlideShowViewer.exe` inside.
   Use the exe in `dist`, not the one in `build`. The `warn-ImageSlideShowViewer.txt` file is normal and can be ignored.
2. Move the whole `dist\ImageSlideShowViewer` folder (not only the .exe, which needs the `_internal` subfolder) wherever you like, for example `C:\Programs\ImageSlideShowViewer`.
3. In Explorer right-click a .jpg, choose *Open with → Choose another app → Choose an app on your PC*, select `ImageSlideShowViewer.exe` and tick *"Always use this app"*. Repeat for .png, .gif, .cbz and so on.

From then on, double-clicking a photo opens the viewer, and **Enter** takes you to the browser on that folder, just like ACDSee.

## Explorer context menu

*Tools → Explorer context menu* adds an **Image SlideShow Viewer** submenu to Explorer:

| Right-click on | Commands |
|---|---|
| A folder, a drive or the empty area of a folder | Start slideshow |
| A `.cbz` / `.zip` archive | Start slideshow, Batch rename |
| An image | Start slideshow, Batch rename, Convert format |

- With several items selected, a single window opens with all of them (for example one slideshow over all the selected folders, one in a row).
- The entries are written only for the current user (`HKEY_CURRENT_USER\Software\Classes`): no administrator rights are needed, and unticking the same menu item removes them completely.
- On Windows 11 the submenu is under **"Show more options"** (or Shift+F10).
- If you move the program or switch from the `.pyw` to the `.exe`, the entries are updated the next time you open the program. Changing the language updates them too.

## Browser

- On the left is the folder tree, on the right the grid: subfolders first (showing the first image inside), then images. Double-click or Enter on a folder to open it, Backspace to go up.
- Thumbnails are cached on disk, so the second time a folder opens they appear immediately.
- Sort by name (natural order: photo2 comes before photo10), date or size, also descending.
- The *Thumbnails* slider changes the preview size. The folder refreshes on its own when files change.
- **Right-click** on the thumbnails: view, *Slideshow on "folder"* (only that folder or archive), slideshow, rename, convert, copy, move, delete, show in Explorer.
- **ZIP / CBZ archives** appear as light-blue folders with their cover. Double-click to open them, or select them and start the slideshow: the folder jump (↓/↑) and *Include subfolders* treat them like folders. Images inside the archive's subfolders are shown in order. Single images inside an archive cannot be renamed or deleted; RAR/CBR and 7Z are not supported.
- **Network:** type `\\192.168.0.2` (or the computer name) in the path bar to see its shared folders, or directly `\\192.168.0.2\Photos`. *Up* from a share goes back to the list of shares. If the computer asks for a password, sign in once from Explorer first.

| Key | Action |
|---|---|
| Enter / double-click | Open the folder or image |
| F5 | Slideshow |
| F2 | Batch rename |
| Ctrl+Shift+C | Convert format |
| Ctrl+Shift+K / M | Copy to… / Move to… |
| Del | Move to the Recycle Bin |
| Backspace, Alt+↑ / Alt+← | Parent folder / Back |
| F1 | List of shortcuts |

## Slideshow

The options are on the second toolbar: **Interval**, **Random**, **Loop** and **Include subfolders**.

- With **one folder selected**, the slideshow starts from it and continues with the other folders in the view. Right-click → *Slideshow on "folder"* plays only that one.
- With **several folders selected** (Ctrl+click or Shift+click), the slideshow shows only those, one after another.
- ↓/↑ always go to the folder after/before the one you are looking at, even after browsing images with →/←. A folder containing only subfolders is played through all of its subfolders.
- If nothing is selected and the current folder contains only subfolders, the slideshow plays all of them.
- With **several images selected**, only those are shown; with **one image selected**, it starts from that one.
- With **Include subfolders**, the slideshow walks the folder and all its subfolders, one after another. With *Random* too, both the folder order and the photos inside each folder are shuffled. ↓/↑ stay inside the starting tree.
- Without subfolders, the slideshow repeats the current folder (if *Loop* is on). ↓/↑ move to the nearest folder on disk that contains images, and the slideshow continues from there. The jump stops at the top-level folder of the drive (for example `D:\Photos`) or at the Pictures folder.

| Key | Action |
|---|---|
| → ← , PgDn/PgUp, wheel | Next / previous image |
| **↓ ↑** , Ctrl+→ / Ctrl+← | **Next / previous folder** |
| Space / P | Start or stop the slideshow (also in the normal viewer) |
| S | Stop the slideshow |
| O | Options: folder name on/off, colours, control bar |
| + / − | Longer / shorter interval |
| Home / End | First / last image of the folder |
| F, F11, double-click | Full screen |
| Z, * | Fit to window ↔ 100% |
| Ctrl+wheel | Zoom (drag to pan) |
| I | Information (name, size, folder, status) |
| Del | Move to the Recycle Bin |
| Enter | Back to the browser on this image |
| Esc | Close |

Moving the mouse shows a **control bar** at the bottom with *Start/Stop*, previous/next image and folder, interval and *Options*. While the slideshow is stopped, a "Paused" badge stays in the top right corner. Right-clicking the image opens a menu with all the commands.

### Options (O key, or Tools → Viewer and slideshow options)

- Folder name when it changes: on or off, position (top, centre, bottom) and duration.
- Other messages (pause, interval, zoom) and "Paused" badge: on or off.
- Text colour, background colour and opacity, text size, with a preview on light and dark backgrounds and quick presets (for example yellow on black).
- Control bar on mouse movement: on or off.

## Batch rename

Select the files (images and also CBZ/ZIP archives) and press **F2**, or use the right-click menu in the browser or in Explorer. As in ACDSee, the rename is a **list of operations** applied in order: tick the ones you need, change their order with ↑ / ↓, add more with **+** (even several of the same kind) and remove them with **−**. The preview shows the new names immediately.

| Operation | What it does |
|---|---|
| **Template** | New name from a template. `*` = original name, `#` = counter (`###` → 001, 002…, or aa, ab… with letters). Fields: `{name}`, `{folder}`, `{date}`, `{time}`, `{year}`, `{month}`, `{day}`, `{width}`, `{height}` (the Italian names `{nome}`, `{cartella}`, `{data}`… work too). *Start at*: fixed value or **auto detect**, which continues a numbering already present in the folder (Photo_001…Photo_012 → starts from 013). |
| **Search and replace** | Replaces every occurrence. Options: case sensitive, include extension, regular expression (with `\1`, `\2` in the replacement). |
| **Case change** | Name: lowercase, UPPERCASE, Title Case, Sentence case. Extension: lowercase or uppercase (to unify .JPG and .jpg). |
| **Insert text** | Prefix, suffix, after N characters, after or before a text. Options: right to left, overwrite characters, include extension, case sensitive. The text may contain the template fields. |
| **Remove text** | Starts from a position or a delimiter and removes a number of characters, up to a delimiter or to the end. Options: right to left, remove the delimiters too, include extension, case sensitive. |
| **Strip spaces** | Remove all spaces, remove leading and trailing spaces, collapse double spaces, or replace spaces with a character. |

**Advanced**

- *If the new name already exists*: rename nothing and mark them in red, skip those files, or add a number (`name (2)`, `name (3)`…).
- *If the extension changes*: allow or skip those files.

Invalid names for Windows (characters `< > : " / \ | ? *`, trailing dot or space, reserved names such as `CON`) are always marked. Swaps such as 1→2, 2→3 are handled correctly, and case-only changes (`IMG.JPG` → `img.jpg`) work too. The operations you used are remembered for next time.

## Other batch operations

- **Convert**: saves as JPEG, PNG, WebP, BMP or TIFF, with adjustable quality and long-side reduction, into a subfolder, another folder or next to the originals. Photos are straightened according to EXIF, but EXIF data is not copied.
- **Copy / Move** (whole folders too): if a file already exists in the destination you can add a number to the name, overwrite it or skip it.
- **Delete**: moves files or folders to the Recycle Bin, so they can be recovered.

## Language

*Tools → Lingua / Language*: **Automatic** (same as Windows), **Italiano** or **English**. The program offers to restart to apply the change.

Translations live in `isv/lang_en.py`: the keys are the Italian strings used in the code. To add a language, create a similar dictionary and register it in `LANGUAGES` in `isv/i18n.py`.

## Formats

JPEG, PNG, GIF (also animated), BMP, WebP, TIFF, ICO and TGA. Photos are rotated automatically according to EXIF.
HEIC and AVIF are recognised only if a Qt plugin for those formats is installed. RAW files are not supported.

Archives: ZIP and CBZ (read only).

## Project structure

```
image_slideshow_viewer.pyw   launcher (double-click)
build_exe.bat                builds the .exe with PyInstaller
isv/__init__.py              name, version, author
isv/app.py                   startup, command line, window coordination, dark theme
isv/browser.py               main window (tree + thumbnails, menus)
isv/thumbs.py                thumbnails and disk cache
isv/viewer.py                viewer and slideshow
isv/navigator.py             image and folder navigation logic
isv/batch.py                 rename / convert / copy / move / delete dialogs
isv/rename.py                batch rename engine (no Qt, testable on its own)
isv/shell.py                 Explorer context menu (registry)
isv/single.py                gathers into one window the files selected in Explorer
isv/about.py                 About window
isv/i18n.py, lang_en.py      translations
isv/archive.py               ZIP / CBZ archives
isv/loader.py                image loading and preloading
isv/worker.py                background work
isv/utils.py                 file lists, sorting, folder navigation
```

Settings are saved automatically in the Windows registry under `HKCU\Software\LainX84\ImageSlideShowViewer`. On first start, the settings of the previous version (FotoVista) are imported.

## Author

**LainX84** — [github.com/LainX84](https://github.com/LainX84)

## License

[MIT](LICENSE)
