"""Local server backing the VMIC editor.

Serves:
  GET  /                                   the viewer page
  GET  /static/<path>                      static assets (JS/CSS/OpenSeadragon)
  POST /api/open  {slot, path}             open a VMIC into slot 'A' or 'B'
  GET  /slide/<slot>/image.dzi             DeepZoom descriptor for a slot
  GET  /slide/<slot>/image_files/L/c_r.ext one tile (read lazily)
  POST /api/screenshot {shots, outdir}     save per-slide TIFF screenshots
  POST /api/save_rotated {slot, angle, outPath}  write a rotated copy as VMIC
"""

import io
import os
import re
import sys
import base64

from flask import Flask, Response, request, jsonify, send_from_directory

from vmic_reader import VmicReader
import export

def _base_dir():
    # When frozen by PyInstaller, bundled data is unpacked to sys._MEIPASS.
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


HERE = _base_dir()
STATIC = os.path.join(HERE, 'static')

app = Flask(__name__, static_folder=None)
SLIDES = {}          # slot -> VmicReader
TILE_NAME_RE = re.compile(r'(\d+)_(\d+)\.(\w+)$')


@app.route('/')
def index():
    return send_from_directory(STATIC, 'index.html')


@app.route('/static/<path:p>')
def static_files(p):
    return send_from_directory(STATIC, p)


@app.route('/api/open', methods=['POST'])
def api_open():
    data = request.get_json(force=True)
    slot = data.get('slot', 'A')
    path = data.get('path')
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'file not found: %s' % path}), 400
    if slot in SLIDES:
        try:
            SLIDES[slot].close()
        except Exception:
            pass
        SLIDES.pop(slot, None)
    try:
        reader = VmicReader(path)
    except Exception as e:
        return jsonify({'error': 'could not open VMIC: %s' % e}), 500
    SLIDES[slot] = reader
    return jsonify({
        'slot': slot,
        'name': os.path.basename(path),
        'path': path,
        'width': reader.width,
        'height': reader.height,
        'tileSize': reader.tile_size,
        'overlap': reader.overlap,
        'format': reader.fmt,
        'maxLevel': reader.max_level,
        'dzi': '/slide/%s/image.dzi' % slot,
    })


@app.route('/slide/<slot>/image.dzi')
def slide_dzi(slot):
    r = SLIDES.get(slot)
    if not r:
        return ('no slide', 404)
    return Response(r.dzi_xml(), mimetype='application/xml')


@app.route('/slide/<slot>/image_files/<int:level>/<tile>')
def slide_tile(slot, level, tile):
    r = SLIDES.get(slot)
    if not r:
        return ('no slide', 404)
    m = TILE_NAME_RE.match(tile)
    if not m:
        return ('bad tile name', 400)
    data = r.tile_bytes(level, int(m.group(1)), int(m.group(2)))
    if data is None:
        return ('', 404)
    mt = 'image/jpeg' if r.fmt in ('jpg', 'jpeg') else 'image/' + r.fmt
    return Response(data, mimetype=mt)


@app.route('/api/screenshot', methods=['POST'])
def api_screenshot():
    data = request.get_json(force=True)
    outdir = data.get('outdir') or os.path.join(os.path.expanduser('~'), 'VMIC_screenshots')
    os.makedirs(outdir, exist_ok=True)
    saved = []
    for shot in data.get('shots', []):
        reader = SLIDES.get(shot.get('slot'))
        if not reader or not shot.get('corners'):
            continue
        name = re.sub(r'[^\w.-]', '_', shot.get('name', 'view')) + '.tif'
        path = os.path.join(outdir, name)
        export.region_to_tiff(reader, shot['corners'], path)
        saved.append(path)
    return jsonify({'saved': saved, 'outdir': outdir})


@app.route('/api/save_rotated', methods=['POST'])
def api_save_rotated():
    data = request.get_json(force=True)
    slot = data.get('slot', 'A')
    angle = float(data.get('angle', 0) or 0)
    out_path = data.get('outPath')
    r = SLIDES.get(slot)
    if not r:
        return jsonify({'error': 'no slide in slot %s' % slot}), 400
    if not out_path:
        base = os.path.splitext(os.path.basename(r.path))[0]
        out_path = os.path.join(os.path.dirname(r.path), base + '_rotated.vmic')
    try:
        export.save_rotated_vmic(r, angle, out_path)
    except Exception as e:
        return jsonify({'error': 'save failed: %s' % e}), 500
    return jsonify({'saved': out_path})


# Pillow is imported lazily here so a missing dependency surfaces clearly.
from PIL import Image  # noqa: E402


def run_server(port):
    app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False)
