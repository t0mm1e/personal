#!/usr/bin/env python3
"""make_markdown_from_epub — leest een EPUB van stdin, schrijft Markdown naar stdout.

gebruik:  make_markdown_from_epub < boek.epub > boek.md
          make_markdown_from_epub --extract-media=media < boek.epub > boek.md

Extra argumenten gaan ongewijzigd door naar pandoc.
Vereist: pandoc (brew install pandoc).

Wat het script doet:
  1. stdin inlezen (de hele epub, het is een zip);
  2. als de OPF in een submap staat (OEBPS/, EPUB/, ...) en met '../' naar
     bestanden daarbuiten verwijst, de epub repareren: OPF naar de root van
     de zip, alle href's genormaliseerd, container.xml aangepast — pandoc
     plakt zulke paden namelijk letterlijk aan elkaar ("OEBPS/../x.html")
     en vindt dan niets ("No entry on path");
  3. pandoc -f epub -t gfm-raw_html --wrap=none erop loslaten.

Waarom gfm-raw_html: anders blijven <div class="..."> en <span class="...">
van de uitgeversopmaak als ruwe HTML in de Markdown staan.
Waarom --wrap=none: elke alinea op één regel, anders knipt pandoc op 72 tekens.
"""

import io
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

PANDOC_ARGS = ["-f", "epub", "-t", "gfm-raw_html", "--wrap=none"]
CONTAINER = "META-INF/container.xml"
NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
HREF_RE = re.compile(r"""(\s(?:href|full-path)\s*=\s*)(["'])([^"']*)\2""")


def die(msg, code=1):
    sys.stderr.write(f"make_markdown_from_epub: {msg}\n")
    sys.exit(code)


def opf_path(container_xml):
    """Pad van de OPF volgens META-INF/container.xml."""
    root = ET.fromstring(container_xml)
    for rf in root.iter(f"{NS_CONTAINER}rootfile"):
        if rf.get("media-type") == "application/oebps-package+xml":
            return rf.get("full-path")
    return None


def normalize(opfdir, href):
    """href relatief aan de OPF-map -> pad relatief aan de zip-root."""
    if not href or href.startswith("#") or "://" in href:
        return href
    path, sep, frag = href.partition("#")
    return posixpath.normpath(posixpath.join(opfdir, path)) + sep + frag


def needs_repair(opfdir, opf_text):
    """Alleen repareren als pandoc's naïeve 'opfdir/href' ergens afwijkt."""
    if not opfdir:
        return False
    for m in HREF_RE.finditer(opf_text):
        href = m.group(3)
        if href.startswith("#") or "://" in href:
            continue
        if posixpath.join(opfdir, href) != normalize(opfdir, href):
            return True
    return False


def repair(data):
    """Geef (bytes, gerepareerd?) terug: dezelfde epub, of een met OPF op de root."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    names = zin.namelist()
    if CONTAINER not in names:
        return data, False
    opf = opf_path(zin.read(CONTAINER))
    if not opf or opf not in names:
        return data, False
    opfdir = posixpath.dirname(opf)
    opf_text = zin.read(opf).decode("utf-8", "surrogateescape")
    if not needs_repair(opfdir, opf_text):
        return data, False

    new_opf_text = HREF_RE.sub(
        lambda m: m.group(1) + m.group(2) + normalize(opfdir, m.group(3)) + m.group(2),
        opf_text,
    )
    new_opf = posixpath.basename(opf)
    if new_opf in names:
        new_opf = "pandoc-fixed.opf"
    container = zin.read(CONTAINER).decode("utf-8", "surrogateescape")
    container = container.replace(f'full-path="{opf}"', f'full-path="{new_opf}"')
    container = container.replace(f"full-path='{opf}'", f"full-path='{new_opf}'")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        if "mimetype" in names:  # moet als eerste en ongecomprimeerd
            zout.writestr("mimetype", zin.read("mimetype"), zipfile.ZIP_STORED)
        for info in zin.infolist():
            if info.filename in ("mimetype", CONTAINER, opf):
                continue
            zout.writestr(info, zin.read(info.filename), zipfile.ZIP_DEFLATED)
        zout.writestr(CONTAINER, container.encode("utf-8", "surrogateescape"), zipfile.ZIP_DEFLATED)
        zout.writestr(new_opf, new_opf_text.encode("utf-8", "surrogateescape"), zipfile.ZIP_DEFLATED)
    return out.getvalue(), True


def main():
    if shutil.which("pandoc") is None:
        die("pandoc niet gevonden (brew install pandoc)", 127)
    if sys.stdin.isatty():
        die("gebruik: make_markdown_from_epub < boek.epub > boek.md", 64)

    data = sys.stdin.buffer.read()
    if not zipfile.is_zipfile(io.BytesIO(data)):
        die("invoer is geen epub (geen zip) — Adobe-DRM levert een .acsm, geen boek", 65)
    try:
        data, fixed = repair(data)
    except Exception as e:  # reparatie is best-effort; pandoc mag het alsnog proberen
        sys.stderr.write(f"make_markdown_from_epub: reparatie overgeslagen ({e})\n")
        fixed = False
    if fixed:
        sys.stderr.write("make_markdown_from_epub: OPF-paden met '..' genormaliseerd\n")

    fd, tmp = tempfile.mkstemp(suffix=".epub")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        rc = subprocess.call(["pandoc", *PANDOC_ARGS, *sys.argv[1:], tmp])
    finally:
        os.unlink(tmp)
    sys.exit(rc)


if __name__ == "__main__":
    main()
