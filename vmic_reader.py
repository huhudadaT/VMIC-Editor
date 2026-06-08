"""Lazy reader for PreciPoint VMIC whole-slide images.

VMIC structure (reverse-engineered, confirmed against real files in this project):

    outer .vmic ZIP   (storage-only: inner container stored uncompressed)
      |- Image.vmici   (inner ZIP)
            |- dzc_output.xml                              (DeepZoom descriptor)
            |- dzc_output_files/<level>/<col>_<row>.jpg    (DeepZoom tile pyramid)
            |- VMCF/...                                    (PreciPoint metadata/images)

Tiles are read on demand. The whole slide is never loaded into memory, so this
scales to multi-gigabyte files (unlike the in-browser prototype).
"""

import io
import os
import re
import struct
import zipfile
import tempfile
import threading
import xml.etree.ElementTree as ET

TILE_RE = re.compile(r'(.*_files)/(\d+)/(\d+)_(\d+)\.([A-Za-z]+)$')


class _SubStream(io.RawIOBase):
    """Seekable, read-only view into a [offset, offset+length) slice of a base file.

    Lets us open the inner (uncompressed) ZIP in place, without extracting it.
    Callers must serialise access (see VmicReader._lock).
    """

    def __init__(self, base, offset, length):
        self._base = base
        self._offset = offset
        self._length = length
        self._pos = 0

    def seek(self, pos, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self._pos = pos
        elif whence == io.SEEK_CUR:
            self._pos += pos
        elif whence == io.SEEK_END:
            self._pos = self._length + pos
        return self._pos

    def tell(self):
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._length - self._pos
        n = max(0, min(n, self._length - self._pos))
        if n == 0:
            return b''
        self._base.seek(self._offset + self._pos)
        data = self._base.read(n)
        self._pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def readable(self):
        return True

    def seekable(self):
        return True


def _stored_data_span(outer_path, info):
    """(data_offset, data_length) of a STORED zip entry within the outer file."""
    with open(outer_path, 'rb') as f:
        f.seek(info.header_offset)
        if f.read(4) != b'PK\x03\x04':
            raise ValueError('bad local header signature for inner container')
        rest = f.read(26)
        name_len, extra_len = struct.unpack('<HH', rest[22:26])
        data_offset = info.header_offset + 30 + name_len + extra_len
    return data_offset, info.compress_size


class VmicReader:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._outer = zipfile.ZipFile(path, 'r')
        self._base_file = None
        self._inner = None
        self._tmp = None
        self._open_inner()
        self._parse_descriptor()

    # ------------------------------------------------------------------ inner
    def _open_inner(self):
        inner_info = None
        candidates = self._outer.infolist()[:40]
        for info in candidates:
            base = os.path.basename(info.filename)
            looks = base.startswith('Image') or info.filename.lower().endswith('.vmici')
            if not looks:
                continue
            with self._outer.open(info) as fh:
                if fh.read(4) == b'PK\x03\x04':
                    inner_info = info
                    break
        if inner_info is None:  # fallback: any stored zip-looking entry
            for info in candidates:
                try:
                    with self._outer.open(info) as fh:
                        if fh.read(4) == b'PK\x03\x04':
                            inner_info = info
                            break
                except Exception:
                    continue
        if inner_info is None:
            raise ValueError('no inner .vmici ZIP container found')
        self.inner_name = inner_info.filename

        if inner_info.compress_type == zipfile.ZIP_STORED:
            data_offset, data_len = _stored_data_span(self.path, inner_info)
            self._base_file = open(self.path, 'rb')
            sub = _SubStream(self._base_file, data_offset, data_len)
            self._inner = zipfile.ZipFile(sub, 'r')
        else:
            # compressed inner: extract once to a temp file, then random-access it
            self._tmp = tempfile.NamedTemporaryFile(suffix='.vmici', delete=False)
            with self._outer.open(inner_info) as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    self._tmp.write(chunk)
            self._tmp.flush()
            self._tmp.close()
            self._inner = zipfile.ZipFile(self._tmp.name, 'r')

    # ------------------------------------------------------------- descriptor
    def _parse_descriptor(self):
        names = self._inner.namelist()

        # detect tile folder + format + deepest level from real tile entries
        self.prefix = None
        self.fmt = None
        self.max_folder = -1
        for n in names:
            m = TILE_RE.match(n)
            if m:
                self.prefix = m.group(1) + '/'
                self.fmt = m.group(5).lower()
                lvl = int(m.group(2))
                if lvl > self.max_folder:
                    self.max_folder = lvl

        # locate the DeepZoom descriptor (.dzi, or an .xml containing <Image TileSize>)
        desc_name, desc_text = None, None
        for n in names:
            if n.lower().endswith('.dzi'):
                desc_name = n
                break
        if desc_name is None:
            for n in names:
                if n.lower().endswith('.xml'):
                    t = self._inner.read(n).decode('utf-8', 'ignore')
                    if '<Image' in t and 'TileSize' in t:
                        desc_name, desc_text = n, t
                        break
        if desc_name is None:
            raise ValueError('no DeepZoom descriptor (.dzi/.xml) found in VMIC')
        if desc_text is None:
            desc_text = self._inner.read(desc_name).decode('utf-8', 'ignore')
        self.descriptor_name = desc_name

        root = ET.fromstring(desc_text)
        self.tile_size = int(root.get('TileSize'))
        self.overlap = int(root.get('Overlap') or 0)
        declared_fmt = (root.get('Format') or 'jpeg').lower()
        if not self.fmt:
            self.fmt = declared_fmt
        size_el = next((c for c in root if c.tag.endswith('Size')), None)
        if size_el is None:
            raise ValueError('descriptor has no <Size> element')
        self.width = int(size_el.get('Width'))
        self.height = int(size_el.get('Height'))

        if self.prefix is None:
            base = re.sub(r'\.(dzi|xml)$', '', desc_name, flags=re.I)
            self.prefix = base + '_files/'

        n_max = max(self.width, self.height)
        self.max_level = n_max.bit_length() - 1
        if (1 << self.max_level) < n_max:
            self.max_level += 1
        if self.max_folder >= 0:
            self.max_level = max(self.max_level, self.max_folder)

    # ------------------------------------------------------------------ tiles
    def tile_entry(self, level, col, row):
        return '%s%d/%d_%d.%s' % (self.prefix, level, col, row, self.fmt)

    def tile_bytes(self, level, col, row):
        with self._lock:
            try:
                return self._inner.read(self.tile_entry(level, col, row))
            except KeyError:
                return None

    def dzi_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Image TileSize="%d" Overlap="%d" Format="%s" '
            'xmlns="http://schemas.microsoft.com/deepzoom/2008">'
            '<Size Width="%d" Height="%d"/></Image>'
            % (self.tile_size, self.overlap, self.fmt, self.width, self.height)
        )

    # ----------------------------------------------------------- export utils
    def stitch_level(self, level):
        """Stitch every tile of a pyramid level into one PIL RGB image."""
        from PIL import Image
        scale = 2 ** (self.max_level - level)
        lw = max(1, -(-self.width // scale))
        lh = max(1, -(-self.height // scale))
        cols = -(-lw // self.tile_size)
        rows = -(-lh // self.tile_size)
        out = Image.new('RGB', (lw, lh), (255, 255, 255))
        for r in range(rows):
            for c in range(cols):
                data = self.tile_bytes(level, c, r)
                if not data:
                    continue
                try:
                    tile = Image.open(io.BytesIO(data)).convert('RGB')
                except Exception:
                    continue
                out.paste(tile, (c * self.tile_size, r * self.tile_size))
        return out

    def vmcf_entries(self):
        """Inner entries that are metadata/associated images (not tiles, not descriptor)."""
        out = []
        for n in self._inner.namelist():
            if TILE_RE.match(n) or n == self.descriptor_name:
                continue
            out.append(n)
        return out

    def read_inner(self, name):
        with self._lock:
            return self._inner.read(name)

    def outer_entries(self):
        return [i.filename for i in self._outer.infolist() if i.filename != self.inner_name]

    def read_outer(self, name):
        return self._outer.read(name)

    def read_region(self, level, x0, y0, x1, y1):
        """Stitch the tiles covering box [x0,x1) x [y0,y1) at `level` into a PIL RGB image."""
        from PIL import Image
        ts = self.tile_size
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        out = Image.new('RGB', (w, h), (255, 255, 255))
        c0, c1 = x0 // ts, (x1 - 1) // ts
        r0, r1 = y0 // ts, (y1 - 1) // ts
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                data = self.tile_bytes(level, c, r)
                if not data:
                    continue
                try:
                    tile = Image.open(io.BytesIO(data)).convert('RGB')
                except Exception:
                    continue
                out.paste(tile, (c * ts - x0, r * ts - y0))
        return out

    # ------------------------------------------------------------------- misc
    def close(self):
        for obj in (self._inner, self._outer):
            try:
                obj.close()
            except Exception:
                pass
        if self._base_file:
            try:
                self._base_file.close()
            except Exception:
                pass
        if self._tmp:
            try:
                os.unlink(self._tmp.name)
            except Exception:
                pass
