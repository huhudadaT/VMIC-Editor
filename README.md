# VMIC Editor

A cross-platform desktop application for viewing and editing **PreciPoint VMIC**
whole-slide images. Open a slide, pan/zoom/rotate, overlay and align up to five
slides at once, export the viewed region to TIFF, and save rotated copies back
out as VMIC.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

> **Disclaimer.** This software is for research and educational use only. It is
> **not** a medical device and must **not** be used for clinical diagnosis or
> primary review.

---

## Why

PreciPoint scanners (M8, O8, Fritz) save slides in the proprietary `.vmic`
format, which most tooling can't open without first converting to enormous
BigTIFFs. VMIC Editor reads `.vmic` files **directly and lazily** — streaming
only the tiles currently on screen from disk — so it opens multi-gigabyte slides
instantly without loading them into memory.

## Features

- **Direct VMIC viewing** — smooth pan, zoom, and rotation, powered by
  OpenSeadragon, with tiles read on demand straight from the `.vmic` container.
- **Typed zoom** — enter an exact zoom factor relative to the opening view
  (`1×` = how the slide first appeared).
- **Multi-slide overlay (up to 5)** — open several slides at once, adjust each
  one's opacity, and drag / scroll / rotate / nudge any of them to align serial
  sections or compare stains by eye.
- **Region export to TIFF** — save the currently viewed region of each open
  slide as a TIFF, reconstructed from the source tiles (not a screen grab),
  with areas outside the slide filled white.
- **Save rotated copies** — bake a slide's rotation into a new `.vmic` file at
  the original dimensions, filling the rotation gaps with white.
- **Memory-friendly** — RAM scales with what's on screen, not with file size or
  the number of slides open.

## Requirements

- Python 3.8+
- A desktop OS with a system webview (Windows 10/11, macOS, or Linux with
  `webkit2gtk`)
- Python packages (installed below): Flask, pywebview, Pillow, NumPy

## Installation

```bash
git clone https://github.com/<your-username>/vmic-editor.git
cd vmic-editor

# (recommended) create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

**Add OpenSeadragon (one time).** Download a 4.x build from
<https://openseadragon.github.io/#download>, unzip it, and copy
`openseadragon.min.js` into:

```
static/vendor/openseadragon/openseadragon.min.js
```

(OpenSeadragon is BSD-licensed, so you may also commit it to your fork.)

## Running

```bash
python3 app.py          # Windows: py app.py
```

A desktop window opens. Click **Open slide**, choose a `.vmic` file, and it
appears in the viewer.

## Usage

| Control | What it does |
|---|---|
| **Open slide** | Loads a `.vmic` into the next free slot (A–E). |
| **Zoom** | Type a factor relative to the first view (`1×` = as opened) and press Enter. |
| **Active** | Selects which slide the mouse and the edit controls act on (or *View* for plain pan/zoom). |
| **Drag / scroll** | On an active slide: drag to move it, scroll to resize it. |
| **Size / Nudge / Rotate / Opacity** | Precise edits to the active slide. |
| **Remove** | Removes the active slide from the view. |
| **Screenshot** | Saves each open slide's viewed region as a TIFF (one file per slide). |
| **Save as VMIC → A / B / …** | Saves a slide with its current rotation as a new `.vmic`. |

**Typical alignment workflow:** open slide A, open slide B, set B's opacity to
~50%, choose B as *Active*, then drag / scroll / rotate B until it lines up with
A. Repeat for additional slides.

## How it works

VMIC is a ZIP-in-ZIP container around a standard DeepZoom tile pyramid:

```
slide.vmic                       (outer ZIP, inner container stored uncompressed)
└── Image.vmici                  (inner ZIP)
    ├── dzc_output.xml           (DeepZoom descriptor)
    ├── dzc_output_files/<level>/<col>_<row>.jpg   (tile pyramid)
    └── VMCF/...                 (PreciPoint metadata / associated images)
```

Because the inner container is stored uncompressed, the reader seeks into it in
place and extracts individual tiles on demand. A small local Flask server
exposes those tiles as a standard DeepZoom source, which OpenSeadragon renders in
its native tiled mode. A pywebview window wraps the whole thing as a desktop app.

## Project structure

```
vmic-editor/
├── app.py              # entry point: starts the server, opens the window
├── server.py           # Flask routes: viewer, tiles, screenshot, save
├── vmic_reader.py      # lazy VMIC / DeepZoom reader
├── export.py           # region-to-TIFF and rotated-VMIC writer
├── requirements.txt
├── README.md
├── LICENSE
└── static/
    ├── index.html
    ├── viewer.js
    ├── style.css
    └── vendor/openseadragon/openseadragon.min.js   (you add this)
```

## Packaging a standalone executable

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --add-data "static:static" app.py
# Windows uses a semicolon:  --add-data "static;static"
```

## Limitations & notes

- **Rotated-VMIC compatibility.** Saved files are valid DeepZoom and re-open in
  this tool, but acceptance by PreciPoint ViewPoint is unverified — test on a
  copy. Saving keeps the original dimensions, so tissue in the extreme corners
  can be clipped when rotated.
- **Saving large slides** stitches and re-tiles the full-resolution image, which
  is memory-intensive. A future version should stream this with `pyvips`.
- **Screenshots** are capped at ~6000 px on the long edge and sampled from the
  pyramid level matching the current zoom.

## Roadmap

- Automated serial-section registration (feature-based / intensity-based).
- `pyvips`-backed export for very large slides.
- Calibrated scale bar (µm) from slide metadata.
- Per-slide annotation overlays.

## Contributing

Issues and pull requests are welcome. Please keep changes focused and include a
short description of what you tested.

## License

Released under the [MIT License](LICENSE).

## Acknowledgments

- Written by Claude Opus 4.8
