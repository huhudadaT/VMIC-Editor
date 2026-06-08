# VMIC Editor

A desktop tool to view and edit PreciPoint VMIC whole-slide images.

It reuses the proven VMIC-opening method (outer ZIP → `Image.vmici` → DeepZoom
pyramid) but reads tiles **lazily from disk**, so it scales to multi-gigabyte
slides — unlike the in-browser prototype, which loaded the whole file into memory.

## Architecture

- `vmic_reader.py` — opens the VMIC and reads DeepZoom tiles on demand. The inner
  container is read **in place** (seeking into the uncompressed outer ZIP), so the
  whole file is never loaded.
- `server.py` — a local Flask server that serves the viewer and streams tiles as a
  standard DeepZoom source (so OpenSeadragon runs in its native mode).
- `export.py` — renders a rotated slide and re-packages it as a new VMIC.
- `app.py` — starts the server and opens a native desktop window (pywebview),
  with native file dialogs.
- `static/` — the OpenSeadragon viewer (HTML/CSS/JS).

## Setup

```bash
pip install -r requirements.txt
```

Then add OpenSeadragon: download a 4.x build from
https://openseadragon.github.io/#download and copy `openseadragon.min.js` to
`static/vendor/openseadragon/openseadragon.min.js` (details in that folder).

## Run

```bash
python app.py
```

## Features

1. **Open a slide** — "Open Slide A" picks a `.vmic`; pan with drag, zoom with scroll.
2. **Magnification box** — shows the live magnification, derived from the **scan**
   objective shown in the same box. Edit that number to match how your slides were
   scanned (20×, 40×, …) and the reading rescales instantly.
3. **Two slides + overlay** — "Open Slide B" loads a second slide overlaid on the
   first at a matched footprint. Use **B opacity**, **Rotate B**, the **align**
   nudge arrows, and the **scale** buttons to lay one slide over the other by eye.
4. **Screenshot → TIFF** — saves the current view as TIFF at the current
   magnification. With two slides open, it saves **two** TIFFs (one per slide,
   captured from the same view), filling any uncovered area with white.
5. **Save rotated as VMIC** — bakes the chosen slide's rotation into a new `.vmic`,
   expanding the canvas and filling the exposed corners with white.

## Known limitations (the honest parts)

- **Save-rotated is memory-heavy.** It stitches the full-resolution image and
  rotates it in memory. Fine for moderate slides; for very large slides this should
  be reimplemented with `pyvips` (vips rotate + `dzsave`, which streams). The
  output is valid DeepZoom and re-opens in this tool, but whether PreciPoint
  ViewPoint accepts the regenerated container is **unverified** — test on a copy.
- **OpenSeadragon must be vendored** (one-time download above) so the app works
  offline.
- **Screenshots are at screen resolution** of the current view (that is what
  "current magnification" means here). For higher-resolution region exports we can
  later add backend region rendering.
- This is a first version assembled without an end-to-end test run; expect to
  iterate on the first errors you hit.

## Packaging for non-developers (later)

Use PyInstaller to produce a single executable, e.g.:

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --add-data "static:static" app.py
```

(On Windows use `--add-data "static;static"`.) The native-dependency packaging
gets trickier only once registration features (OpenCV) are added.
