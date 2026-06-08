"""Export helpers: save a rotated slide back out as a new VMIC file.

The rotated full-resolution image is re-tiled into a fresh DeepZoom pyramid and
packaged in the same container shape PreciPoint uses (Image.vmici holding the
pyramid, stored uncompressed inside the outer .vmic).

Caveats:
  * This stitches the full-resolution image in memory and rotates it, so it is
    memory-hungry. Fine for moderate slides; for multi-gigabyte slides this
    should be reimplemented with pyvips (vips rotate + dzsave, streaming).
  * The output is valid DeepZoom and re-opens in this tool, but whether
    PreciPoint ViewPoint accepts the regenerated container is unverified.
"""

import io
import math
import zipfile

from PIL import Image

TILE = 256
OVERLAP = 0
FMT = 'jpg'
JPEG_QUALITY = 88
DESC_NAME = 'dzc_output.xml'
TILE_DIR = 'dzc_output_files'
INNER_NAME = 'Image.vmici'


def _descriptor(width, height):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\r\n'
        '<Image TileSize="%d" Overlap="%d" Format="%s" '
        'xmlns="http://schemas.microsoft.com/deepzoom/2008">'
        '<Size Width="%d" Height="%d"/></Image>'
        % (TILE, OVERLAP, FMT, width, height)
    )


def _write_pyramid(inner_zip, full_img):
    """Write a complete DeepZoom pyramid of full_img into inner_zip."""
    w, h = full_img.size
    n_max = max(w, h)
    max_level = n_max.bit_length() - 1
    if (1 << max_level) < n_max:
        max_level += 1

    inner_zip.writestr(DESC_NAME, _descriptor(w, h))

    for level in range(max_level + 1):
        scale = 2 ** (max_level - level)
        lw = max(1, math.ceil(w / scale))
        lh = max(1, math.ceil(h / scale))
        level_img = full_img if scale == 1 else full_img.resize((lw, lh), Image.LANCZOS)
        cols = math.ceil(lw / TILE)
        rows = math.ceil(lh / TILE)
        for r in range(rows):
            for c in range(cols):
                left, upper = c * TILE, r * TILE
                box = (left, upper, min(left + TILE, lw), min(upper + TILE, lh))
                tile = level_img.crop(box)
                buf = io.BytesIO()
                tile.save(buf, format='JPEG', quality=JPEG_QUALITY)
                inner_zip.writestr('%s/%d/%d_%d.%s' % (TILE_DIR, level, c, r, FMT),
                                   buf.getvalue())
        if level_img is not full_img:
            level_img.close()


def save_rotated_vmic(reader, angle_deg, out_path):
    """Render `reader`'s slide rotated by angle_deg (clockwise-positive),
    fill the exposed corners with white, and write a new VMIC at out_path."""
    full = reader.stitch_level(reader.max_level)
    # PIL rotates counter-clockwise for positive angle; negate for a
    # clockwise-positive convention matching the viewer's rotation control.
    # Keep the SAME canvas size as the source so the saved slide matches the
    # original's dimensions (overlays 1:1); rotation gaps are filled white,
    # and only the extreme corners (normally blank glass) are clipped.
    rotated = full.rotate(-angle_deg, expand=False, resample=Image.BICUBIC,
                          fillcolor=(255, 255, 255))
    full.close()

    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, 'w', zipfile.ZIP_DEFLATED) as inner:
        _write_pyramid(inner, rotated)
        # carry over PreciPoint metadata / associated images if present
        for name in reader.vmcf_entries():
            try:
                inner.writestr(name, reader.read_inner(name))
            except Exception:
                pass
    rotated.close()

    with zipfile.ZipFile(out_path, 'w') as outer:
        # inner container stored uncompressed, matching the storage-only outer
        outer.writestr(INNER_NAME, inner_buf.getvalue(), compress_type=zipfile.ZIP_STORED)
        # preserve any other outer entries (e.g. editable settings)
        for name in reader.outer_entries():
            try:
                outer.writestr(name, reader.read_outer(name))
            except Exception:
                pass
    return out_path


def region_to_tiff(reader, corners, out_path, size_cap=6000):
    """Render the viewed region of a slide to a TIFF, sampled from the real tiles.

    `corners` is the viewport's four corners (TL, TR, BR, BL) expressed in the
    slide's IMAGE pixel coordinates (as produced by OpenSeadragon, so any per-slide
    rotation is already baked in). Areas outside the slide are filled white.
    """
    from PIL import Image

    def dist(a, b):
        return math.hypot(a['x'] - b['x'], a['y'] - b['y'])

    tl, tr, br, bl = corners[0], corners[1], corners[2], corners[3]
    out_w = max(1, int(round(dist(tl, tr))))
    out_h = max(1, int(round(dist(tl, bl))))

    # cap output size; pick a pyramid level near the output scale to bound memory
    f = min(1.0, float(size_cap) / max(out_w, out_h))
    out_w = max(1, int(round(out_w * f)))
    out_h = max(1, int(round(out_h * f)))

    inv = (1.0 / f) if f > 0 else 1.0
    d_exp = int(math.floor(math.log2(inv))) if inv >= 1 else 0
    d_exp = max(0, min(d_exp, reader.max_level))
    level = reader.max_level - d_exp
    d = 2 ** d_exp

    lvl_w = max(1, math.ceil(reader.width / d))
    lvl_h = max(1, math.ceil(reader.height / d))

    xs = [c['x'] / d for c in corners]
    ys = [c['y'] / d for c in corners]
    minx = max(0, int(math.floor(min(xs))))
    miny = max(0, int(math.floor(min(ys))))
    maxx = min(lvl_w, int(math.ceil(max(xs))))
    maxy = min(lvl_h, int(math.ceil(max(ys))))

    if maxx <= minx or maxy <= miny:        # nothing of the slide is in view
        img = Image.new('RGB', (out_w, out_h), (255, 255, 255))
        img.save(out_path, format='TIFF', compression='tiff_lzw')
        img.close()
        return out_path

    src = reader.read_region(level, minx, miny, maxx, maxy)
    # PIL QUAD source order = output UL, LL, LR, UR = viewport TL, BL, BR, TR
    order = [0, 3, 2, 1]
    quad = []
    for i in order:
        quad.append(corners[i]['x'] / d - minx)
        quad.append(corners[i]['y'] / d - miny)
    out = src.transform((out_w, out_h), Image.QUAD, tuple(quad),
                        resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    src.close()
    out.save(out_path, format='TIFF', compression='tiff_lzw')
    out.close()
    return out_path
