#!/usr/bin/env python3
"""make_markdown_from_epub — leest een EPUB van stdin, schrijft Markdown naar stdout.

2026-11-18: https://claude.ai/chat/738569a2-ea45-4bc3-82f9-41c805139fce
OLDER:	    https://claude.ai/chat/1b7744ad-e47d-48fa-86cc-a717e252e9a5

gebruik:  make_markdown_from_epub < boek.epub > boek.md
          make_markdown_from_epub --extract-media=media < boek.epub > boek.md
          make_markdown_from_epub --geen-voetnoten < boek.epub > boek.md

Extra argumenten gaan ongewijzigd door naar pandoc (op --geen-voetnoten na).
Vereist: pandoc (brew install pandoc).

Uitgangspunt: niets uit het boek mag ongemerkt wegvallen. Pandoc laat uit
zichzelf wél dingen weg, dus het script maakt de epub eerst 'pandoc-vast' en
controleert achteraf of alle tekst is aangekomen:

  1. stdin inlezen (de hele epub, het is een zip);
  2. OPF: staat die in een submap (OEBPS/, EPUB/, ...) en verwijst hij met
     '../' naar bestanden daarbuiten, dan gaat de OPF naar de root van de zip,
     met alle href's genormaliseerd en container.xml aangepast — pandoc plakt
     zulke paden letterlijk aan elkaar ("OEBPS/../x.html") en vindt dan niets
     ("No entry on path"). Verder tellen onderdelen met linear="no" of
     media-type text/html gewoon mee; pandoc slaat die zonder melding over;
  3. noten: pandoc haalt alles wat als noot gemarkeerd is (role="doc-endnotes",
     epub:type="footnote", ...) uit de tekst en zet het alleen terug als de
     verwijzing in hetzelfde bestand staat. Staan de noten in een eigen bestand
     (eindnoten!), dan verdwijnen ze geruisloos. Daarom zoekt het script zelf
     bij elke verwijzing de noot en zet die in het bestand van de verwijzing,
     in de ene vorm die pandoc in alle versies als voetnoot leest. Resultaat:
     [^1] in de tekst en de noten onderaan het bestand (of vlak bij de tekst,
     met --reference-location=block). Wat niet te koppelen is, blijft als
     gewone tekst staan. Met --geen-voetnoten blijft álles staan waar het stond;
  4. titelpagina en inhoudsopgave blijven staan (pandoc gooit ze weg);
  5. tabellen: cellen met meer dan één regel tekst worden platgeslagen (pandoc
     schrijft anders alleen '[TABLE]') en rowspan/colspan wordt uitgeschreven
     als lege cellen (anders verschuiven de kolommen);
  6. BOM eraf en alles naar UTF-8 (iets anders leest pandoc niet);
  7. pandoc -f epub -t gfm-raw_html --wrap=none erop loslaten;
  8. controle: staat elk stuk tekst uit de epub ook in de uitvoer? Zo niet,
     dan meldt het script op stderr uit welk bestand er hoeveel ontbreekt.

Waarom gfm-raw_html: anders blijven <div class="..."> en <span class="...">
van de uitgeversopmaak als ruwe HTML in de Markdown staan.
Waarom --wrap=none: elke alinea op één regel, anders knipt pandoc op 72 tekens.
"""

import bisect
import html
import io
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote

NAAM = "make_markdown_from_epub"
PANDOC_ARGS = ["-f", "epub", "-t", "gfm-raw_html", "--wrap=none"]
CONTAINER = "META-INF/container.xml"
NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
HREF_RE = re.compile(r"""(\s(?:href|full-path)\s*=\s*)(["'])([^"']*)\2""")


def meld(msg):
    sys.stderr.write(f"{NAAM}: {msg}\n")


def die(msg, code=1):
    meld(msg)
    sys.exit(code)


# ───────────────────────────── OPF ─────────────────────────────

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


def spine_documenten(opfdir, opf_bytes, names):
    """Zip-paden van de (x)html-bestanden in leesvolgorde, ook die met linear="no"."""
    root = ET.fromstring(opf_bytes)
    lokaal = lambda el: el.tag.rsplit("}", 1)[-1]
    manifest = {el.get("id"): (normalize(opfdir, unquote(el.get("href"))), el.get("media-type") or "")
                for el in root.iter() if lokaal(el) == "item" and el.get("id") and el.get("href")}
    paden = []
    for el in root.iter():
        if lokaal(el) != "itemref":
            continue
        pad, mime = manifest.get(el.get("idref"), (None, ""))
        if pad in names and pad not in paden and ("html" in mime or pad.lower().endswith((".xhtml", ".html", ".htm"))):
            paden.append(pad)
    return paden


def opf_meetellen(opf_text):
    """linear="no" en media-type text/html eruit: pandoc slaat zulke onderdelen over."""
    geteld = [0]

    def fix(m):
        tag, n = re.subn(r"""\s+linear\s*=\s*(["'])no\1""", "", m.group(0))
        geteld[0] += n
        return tag

    opf_text = re.sub(r"<(?:\w+:)?itemref\b[^>]*>", fix, opf_text)
    opf_text = re.sub(r"""(media-type\s*=\s*)(["'])text/html\2""", r"\1\2application/xhtml+xml\2", opf_text)
    return opf_text, geteld[0]


# ─────────────────── (x)html als boom met bronposities ───────────────────

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
INLINE = frozenset("a abbr b bdi bdo big cite code del em font i ins kbd label mark q s samp small span "
                   "strong sub sup time tt u var".split())
STIL = frozenset("head script style template title math".split())      # geen leestekst
HEEL = frozenset("img svg math picture video audio object canvas iframe".split())   # niet in knippen
NOOT_TAGS = frozenset("aside li p div dd section blockquote".split())   # hierin kan één noot zitten
KOPTAG_RE = re.compile("h[1-6]")
TAG_RE = re.compile(r"<[^>]*>")
ONZICHTBAAR_RE = re.compile("[­​‌‍⁠﻿]")
SPATIE = r"(?:\s| |&nbsp;|&#160;|&#xa0;)*"
SCHEIDING = "\x1e"          # tussen twee blokken leestekst (alinea's, cellen, koppen)


def platte_tekst(fragment):
    """Stuk html -> de zichtbare tekst ervan."""
    return ONZICHTBAAR_RE.sub("", html.unescape(TAG_RE.sub("", fragment))).replace(" ", " ").strip()


def render(text, edits, a, b):
    """text[a:b] met alle wijzigingen die er helemaal binnen vallen. Een wijziging is
    (start, eind, nieuwe tekst); zit er één in een andere, dan wint de buitenste."""
    out, pos = [], a
    for s, e, nieuw in sorted((x for x in edits if a <= x[0] and x[1] <= b), key=lambda x: (x[0], -x[1])):
        if s < pos:
            continue
        out += [text[pos:s], nieuw]
        pos = e
    out.append(text[pos:b])
    return "".join(out)


class Node:
    __slots__ = ("tag", "attrs", "parent", "children", "start", "start_end", "end_start", "end")

    def __init__(self, tag, attrs, parent, start, start_end):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []
        self.start, self.start_end = start, start_end       # de starttag: text[start:start_end]
        self.end_start = self.end = start_end                # de eindtag:  text[end_start:end]

    def tokens(self, attr):
        return set((self.attrs.get(attr) or "").lower().split())

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


class Doc(HTMLParser):
    """Eén (x)html-bestand als boom van elementen, elk met zijn plek in de brontekst.
    Zo kunnen wijzigingen als knip-en-plakwerk op de oorspronkelijke tekst en blijft
    al het andere letterlijk staan. html.parser struikelt niet over slordige html."""

    def __init__(self, path, text):
        super().__init__(convert_charrefs=True)
        self.path, self.text = path, text
        self.edits = []                     # (start, eind, nieuwe tekst)
        self.ok = True                      # kloppen de posities?
        self.ids, self.links, self.nodes, self.body = {}, [], [], None
        self._tekst = []
        self._lines = [0] + [m.end() for m in re.finditer("\n", text)]
        self.root = Node("#root", {}, None, 0, 0)
        self._stack = [self.root]
        try:
            self.feed(text)
            self.close()
        except Exception:
            self.ok = False
        for n in self._stack:               # wat nog openstaat, loopt tot het eind
            n.end_start = n.end = len(text)
        self.starts = [n.start for n in self.nodes]
        self.link_starts = [a.start for a in self.links]
        # de leestekst per blok, voor de controle achteraf
        self.blokken = [b for b in map(woorden, "".join(self._tekst).split(SCHEIDING)) if b]

    def _pos(self):
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def _grens(self, tag):
        self._tekst.append(SCHEIDING if tag not in INLINE else " " if tag in ("a", "sup", "sub") else "")

    def handle_starttag(self, tag, attrs):
        start, raw = self._pos(), self.get_starttag_text() or ""
        if not raw or not self.text.startswith(raw, start):
            self.ok = False
        node = Node(tag, {k: v or "" for k, v in attrs}, self._stack[-1], start, start + len(raw))
        node.parent.children.append(node)
        self.nodes.append(node)
        for naam in (node.attrs.get("id"), node.attrs.get("name") if tag == "a" else None):
            if naam:
                self.ids.setdefault(naam, node)
        if tag == "a" and node.attrs.get("href"):
            self.links.append(node)
        if tag == "body" and self.body is None:
            self.body = node
        self._grens(tag)
        if tag not in VOID and not raw.endswith("/>"):
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        pos = self._pos()
        self._grens(tag)
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                for n in self._stack[i + 1:]:               # impliciet gesloten
                    n.end_start = n.end = pos
                node = self._stack[i]
                node.end_start = pos
                node.end = self.text.find(">", pos) + 1 or len(self.text)
                del self._stack[i:]
                return

    def handle_data(self, data):
        if not any(n.tag in STIL or verborgen(n) for n in self._stack):
            self._tekst.append(data.replace(SCHEIDING, " "))

    def binnen(self, node):
        """Alle elementen binnen node, in documentvolgorde."""
        return self.nodes[bisect.bisect_right(self.starts, node.start):bisect.bisect_left(self.starts, node.end)]

    def links_in(self, node):
        return self.links[bisect.bisect_left(self.link_starts, node.start):bisect.bisect_left(self.link_starts, node.end)]

    def blok(self, node):
        """Het dichtstbijzijnde niet-inline element om node heen (of node zelf)."""
        while node.tag in INLINE and node.parent is not None:
            node = node.parent
        return node

    def vooraan(self, blok, node):
        """Staat node helemaal aan het begin van blok, hooguit met een haakje ervoor?"""
        return not platte_tekst(self.text[blok.start_end:node.start]).strip("[(")


def verborgen(n):
    """<nav hidden>: de landmarks en paginalijst van een epub, geen tekst van het boek."""
    return n.tag == "nav" and "hidden" in n.attrs


# ─────────── wat pandoc uit de tekst haalt of lelijk overneemt ───────────

WEG_TYPE = {"noteref", "footnote", "footnotes", "rearnote", "rearnotes", "endnote", "endnotes", "toc"}
WEG_ROLE = {"doc-noteref", "doc-footnote", "doc-endnote", "doc-endnotes", "doc-backlink"}
ATTR_RE = re.compile(r"""\s+(epub:type|role)\s*=\s*(["'])(.*?)\2""", re.S | re.I)
SPAN_RE = re.compile(r"""\s+(?:rowspan|colspan)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>"']+)""", re.I)


def ontdoe(starttag):
    """Starttag zonder de markeringen waardoor pandoc inhoud weglaat (noten, titelpagina,
    inhoudsopgave); de rest van de tag blijft zoals hij was."""
    def fix(m):
        weg = WEG_ROLE if m.group(1).lower() == "role" else WEG_TYPE
        houd = [t for t in m.group(3).split() if t.lower() not in weg and "titlepage" not in t.lower()]
        return f" {m.group(1)}={m.group(2)}{' '.join(houd)}{m.group(2)}" if houd else ""
    return ATTR_RE.sub(fix, starttag)


def tabellen(doc):
    """Wat er aan tabellen moet gebeuren om ze heel in Markdown te krijgen. Geeft terug:
    plat — elementen in cellen die weg moeten: pandoc schrijft '[TABLE]' zodra één cel
           meer bevat dan een regel tekst (twee alinea's, een <br>, een lijst);
    voor, na — lege cellen die vóór of na een cel of rij moeten komen, zodat een
           rowspan/colspan een gewoon raster wordt en de kolommen niet verschuiven."""
    plat, voor, na = set(), {}, {}
    for tabel in doc.nodes:
        if tabel.tag != "table":
            continue
        cellen = [n for n in doc.binnen(tabel) if n.tag in ("td", "th")]
        for cel in cellen:
            blokken, tot = [], 0
            for n in doc.binnen(cel):
                if n.start < tot:
                    continue
                if n.tag in HEEL:
                    tot = n.end
                elif n.tag not in INLINE:
                    blokken.append(n)
            if blokken and not (len(blokken) == 1 and blokken[0].tag == "p" and blokken[0].parent is cel):
                plat.update(id(n) for n in blokken)
        if (not any(SPAN_RE.search(doc.text[c.start:c.start_end]) for c in cellen)
                or any(c.end == c.end_start for c in cellen)):
            continue

        def span(cel, attr):
            try:
                return max(1, min(int(cel.attrs.get(attr, "1")), 100))
            except ValueError:
                return 1

        bezet = set()                                       # (rij, kolom) onder een rowspan van hierboven
        rijen = [n for n in doc.binnen(tabel)
                 if n.tag == "tr" and next(x for x in n.ancestors() if x.tag == "table") is tabel]
        for r, tr in enumerate(rijen):
            k, laatste = 0, "td"
            for cel in (c for c in tr.children if c.tag in ("td", "th")):
                lege, laatste = 0, cel.tag
                while (r, k) in bezet:
                    lege, k = lege + 1, k + 1
                breed = span(cel, "colspan")
                bezet.update((r + dr, k + dk) for dr in range(1, span(cel, "rowspan")) for dk in range(breed))
                k += breed
                leeg = f"<{cel.tag}></{cel.tag}>"
                voor[id(cel)], na[id(cel)] = leeg * lege, leeg * (breed - 1)
            lege = 0
            while (r, k) in bezet:
                lege, k = lege + 1, k + 1
            na[id(tr)] = f"<{laatste}></{laatste}>" * lege
    return plat, voor, na


def neutraliseer(doc):
    """Zet per element klaar wat er aan de start- en eindtag moet veranderen:
    - markeringen eruit waardoor pandoc inhoud weglaat (zie ontdoe);
    - <nav> en <aside> worden <div>: pandoc zet die tags anders letterlijk in de Markdown;
    - een <br> in een kop wordt een spatie: anders maakt pandoc er een ===-kop van twee regels van;
    - tabellen: zie tabellen()."""
    plat, voor, na = tabellen(doc)
    for n in doc.nodes:
        raw, slot = doc.text[n.start:n.start_end], doc.text[n.end_start:n.end]
        nieuw, nieuw_slot = raw, slot
        if verborgen(n):
            doc.edits.append((n.start, n.end, ""))
            continue
        if id(n) in plat:
            nieuw, nieuw_slot = " • " if n.tag == "li" else " ", " "
        else:
            if "epub:type" in raw.lower() or "role" in raw.lower():
                nieuw = ontdoe(raw)
            if n.tag in ("nav", "aside") and (slot or raw.endswith("/>")):
                nieuw, nieuw_slot = "<div" + nieuw[1 + len(n.tag):], "</div>"
            elif n.tag == "br" and any(KOPTAG_RE.fullmatch(x.tag) for x in n.ancestors()):
                nieuw = " "
            elif n.tag in ("td", "th") and id(n) in voor:
                nieuw, nieuw_slot = voor[id(n)] + SPAN_RE.sub("", nieuw), slot + na[id(n)]
            elif n.tag == "tr" and id(n) in na:
                nieuw_slot = na[id(n)] + slot
        if nieuw != raw:
            doc.edits.append((n.start, n.start_end, nieuw))
        if slot and nieuw_slot != slot:
            doc.edits.append((n.end_start, n.end, nieuw_slot))


# ───────────────────────────── noten ─────────────────────────────

# hoe een nootcijfer eruitziet: 12, [12], (3), *, †, iv, a
MARKER_RE = re.compile(r"[\[(]?\s*(\d{1,4}[a-z]?|[*†‡§¶‖#]{1,4}|[ivxlcdm]{1,7}|[a-z])\s*[\])]?[.:]?", re.I)
BLOK_RE = re.compile(r"<(?:p|div|ul|ol|dl|table|blockquote|pre|h[1-6]|figure|section|aside|hr)\b", re.I)
KOP_RE = re.compile(r"<h[1-6]\b.*?</h[1-6]\s*>", re.S | re.I)
INHOUD_RE = re.compile(r"<(?:img|svg|math|table|video|audio|object|iframe|canvas)\b", re.I)
URL_ATTR_RE = re.compile(r"""(\s(?:src|href|xlink:href|poster|data)\s*=\s*)(["'])([^"']*)\2""", re.I)
EXTERN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
TERUG = "\x00terug\x00"     # staat tijdelijk op de plek van een weggehaalde terugverwijzing


def is_noteref(a):
    return "noteref" in a.tokens("epub:type") or "doc-noteref" in a.tokens("role")


def is_backlink(a):
    return "doc-backlink" in a.tokens("role")


def doel(doc_path, href):
    """href in bestand doc_path -> (zip-pad, fragment); None voor een externe link."""
    if EXTERN_RE.match(href):
        return None
    pad, _, frag = href.partition("#")
    pad = unquote(pad.partition("?")[0])
    if pad:
        pad = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), pad))
    return pad or doc_path, unquote(frag)


def terugverwijzingen(ndoc, noot, doc, a):
    """Links in de noot die terugwijzen naar de alinea van verwijzing a."""
    blok, terug = doc.blok(a), []
    for b in ndoc.links_in(noot):
        d = None if is_backlink(b) else doel(ndoc.path, b.attrs["href"])
        m = doc.ids.get(d[1]) if d and d[0] == doc.path else None
        if is_backlink(b) or (m is not None and (m is a or doc.blok(m) is blok)):
            terug.append(b)
    return terug


def zoek_noot(docs, doc, a):
    """De noot waar link a naar verwijst, als (notendoc, element); None als a geen
    nootverwijzing is. Liever een noot te weinig gekoppeld dan een gewone link
    ('zie hoofdstuk 3') voor een noot aangezien."""
    d = None if is_backlink(a) or a.end == a.start_end else doel(doc.path, a.attrs["href"])
    ndoc = docs.get(d[0]) if d and d[1] else None
    if ndoc is None or not ndoc.ok or d[1] not in ndoc.ids:
        return None
    doelwit = noot = ndoc.ids[d[1]]
    if noot.tag in INLINE:                              # het id zit op het nootcijfer, niet op de noot
        noot = ndoc.blok(doelwit)
        if not ndoc.vooraan(noot, doelwit):
            return None
        ouder = noot.parent                             # <div class="footnote"><p>…</p><p>…</p></div>
        if (ouder is not None and ouder.tag in NOOT_TAGS and ouder.children[0] is noot
                and re.search(r"note|noot|fn", ouder.attrs.get("class", "") + ouder.attrs.get("epub:type", ""), re.I)):
            noot = ouder
    if noot.tag not in NOOT_TAGS or (ndoc is doc and noot.start <= a.start < noot.end):
        return None
    if re.search(r"<h[1-6]\b", ndoc.text[noot.start:noot.end], re.I):
        return None
    if not is_noteref(a):                               # zonder markering: alleen op sterke aanwijzingen
        if not MARKER_RE.fullmatch(platte_tekst(doc.text[a.start_end:a.end_start])):
            return None
        if doc.vooraan(doc.blok(a), a) or not terugverwijzingen(ndoc, noot, doc, a):
            return None
    return ndoc, noot


def vervolg(ndoc, noot, nootset, refset):
    """De losse alinea's ná een <p>-noot die er nog bij horen: alles tot de volgende noot.
    Tot een kop of het eind alleen in een blok dat verder uit noten bestaat."""
    if noot.tag != "p":
        return []
    broers = noot.parent.children
    i = next(k for k, b in enumerate(broers) if b is noot)
    kop = lambda b: KOPTAG_RE.fullmatch(b.tag) or b.tag == "hr"
    alleen_noten = id(next(b for b in broers if not kop(b))) in nootset
    extra = []
    for b in broers[i + 1:]:
        if id(b) in nootset:
            return extra
        if kop(b):
            break
        if (any(n.attrs.get("id") or n.attrs.get("name") for n in [b] + ndoc.binnen(b))
                or any(id(a) in refset for a in ndoc.links_in(b))):
            return []                                   # een eigen anker of zelf een nootverwijzing: geen vervolg
        extra.append(b)
    return extra if alleen_noten else []


def verhuis(fragment, van, naar):
    """Laat relatieve links kloppen als een stuk html van bestand `van` naar `naar` gaat."""
    def fix(m):
        url = m.group(3)
        if not url or url.startswith("/") or EXTERN_RE.match(url):
            return m.group(0)
        pad, sep, frag = url.partition("#")
        absoluut = posixpath.normpath(posixpath.join(posixpath.dirname(van), pad)) if pad else van
        nieuw = "" if absoluut == naar else posixpath.relpath(absoluut, posixpath.dirname(naar) or ".")
        return m.group(1) + m.group(2) + nieuw + sep + frag + m.group(2)
    return fragment if van == naar else URL_ATTR_RE.sub(fix, fragment)


def ruim_op(doc, noten):
    """Haal ook weg wat alleen óm de verhuisde noten stond: de lege lijst, het lege
    notenblok en de kop ('Noten') erboven. Anders blijft er een kop zonder inhoud."""
    def is_leeg(a, b):
        rest = KOP_RE.sub("", render(doc.text, doc.edits, a, b))
        return not INHOUD_RE.search(rest) and not platte_tekst(rest)

    leeg, toppen = {}, {}
    for noot in noten:
        top = None
        for anc in noot.ancestors():
            if anc is doc.root or anc.tag == "html":
                break
            if id(anc) not in leeg:
                leeg[id(anc)] = is_leeg(anc.start_end, anc.end_start)
            if not leeg[id(anc)]:
                break
            top = anc
        if top is not None:
            toppen[id(top)] = top
    extra = []
    for top in toppen.values():
        if top.tag == "body":
            extra.append((top.start_end, top.end_start, ""))
            continue
        extra.append((top.start, top.end, ""))
        broers = top.parent.children
        i = next(k for k, b in enumerate(broers) if b is top)
        kop = broers[i - 1] if i else None
        if kop is not None and KOPTAG_RE.fullmatch(kop.tag):
            volgende = next((b for b in broers[i + 1:] if KOPTAG_RE.fullmatch(b.tag)), None)
            tot = volgende.start if volgende is not None else top.parent.end_start
            if is_leeg(kop.end, top.start) and is_leeg(top.end, tot):
                extra.append((kop.start, kop.end, ""))
    doc.edits += extra


def koppel_noten(docs):
    """Zet elk paar (verwijzing, noot) om naar de vorm die pandoc als voetnoot leest:
    <a epub:type="noteref" href="#x"> met <aside epub:type="footnote" id="x"> in
    hetzelfde bestand. Geeft (omgezet, verwijzingen waar geen noot bij te vinden was)."""
    paren, mislukt = [], 0
    for doc in docs.values():
        for a in doc.links if doc.ok else ():
            gevonden = zoek_noot(docs, doc, a)
            if gevonden:
                paren.append((doc, a) + gevonden)
            elif is_noteref(a):
                mislukt += 1

    # een 'noot' waar andere noten in zitten is een notenblok; een verwijzing ín een noot blijft een link
    nootset = {id(p[3]) for p in paren}
    buitenste = {id(x) for p in paren for x in p[3].ancestors() if id(x) in nootset}
    paren = [p for p in paren if id(p[3]) not in buitenste]
    nootset = {id(p[3]) for p in paren}
    paren = [p for p in paren if not any(id(x) in nootset for x in p[1].ancestors())]

    per_noot = {}
    for doc, a, ndoc, noot in paren:
        per_noot.setdefault(id(noot), (ndoc, noot, []))[2].append((doc, a))
    # veel verwijzingen naar één groot element: dat is een heel notenblok, geen noot
    per_noot = {k: v for k, v in per_noot.items()
                if len(v[2]) < 4 or len(platte_tekst(v[0].text[v[1].start:v[1].end])) < 2000}

    refset = {id(a) for _, _, refs in per_noot.values() for _, a in refs}
    asides, weg, teller = {}, [], 0
    for ndoc, noot, refs in per_noot.values():
        # de terugverwijzing ('↩', het nootcijfer) hoort niet in de voetnoot
        terug = [(b.start, b.end, TERUG) for doc, a in refs for b in terugverwijzingen(ndoc, noot, doc, a)
                 if is_backlink(b) or len(platte_tekst(ndoc.text[b.start_end:b.end_start])) <= 20]
        inhoud = render(ndoc.text, ndoc.edits + terug, noot.start_end, noot.end_start)
        voor, sep, na = inhoud.partition(TERUG)
        if sep and not platte_tekst(voor):              # cijfer stond vooraan: ook '. ' of ') ' erachter weg
            inhoud = voor + re.sub("^" + SPATIE + r"[.:)\]]?" + SPATIE, "", na, count=1)
        inhoud = inhoud.replace(TERUG, "")
        if not platte_tekst(inhoud) and not INHOUD_RE.search(inhoud):
            continue                                    # er blijft niets over: dit was geen noot
        if noot.tag == "p" or not BLOK_RE.search(inhoud):
            inhoud = f"<p>{inhoud}</p>"
        erbij = vervolg(ndoc, noot, per_noot, refset)
        inhoud += "".join(render(ndoc.text, ndoc.edits, b.start, b.end) for b in erbij)
        weg += [(ndoc, n) for n in [noot] + erbij]
        for doc, a in refs:
            teller += 1
            label = platte_tekst(doc.text[a.start_end:a.end_start])
            anker = f'<a epub:type="noteref" href="#mdfn-{teller}">{html.escape(label) or "*"}</a>'
            hulsel = a
            if MARKER_RE.fullmatch(label):              # ook de <sup> of <span> om het cijfer heen weg
                while hulsel.parent.tag in INLINE and platte_tekst(
                        doc.text[hulsel.parent.start_end:hulsel.parent.end_start]).strip("[]() ") == label.strip("[]() "):
                    hulsel = hulsel.parent
            else:                                       # verwijzing op gewone woorden: die blijven staan
                anker = render(doc.text, doc.edits, a.start_end, a.end_start) + anker
            doc.edits.append((hulsel.start, hulsel.end, anker))
            asides.setdefault(doc.path, []).append(
                f'<aside epub:type="footnote" id="mdfn-{teller}">{verhuis(inhoud, ndoc.path, doc.path)}</aside>')

    for ndoc, n in weg:                                 # de noot weg van zijn oude plek
        ndoc.edits.append((n.start, n.end, ""))
    for ndoc in {id(d): d for d, _ in weg}.values():
        ruim_op(ndoc, [n for d, n in weg if d is ndoc])
    for pad, lijst in asides.items():
        waar = docs[pad].body.end_start if docs[pad].body is not None else len(docs[pad].text)
        docs[pad].edits.append((waar, waar, "\n" + "\n".join(lijst) + "\n"))
    return teller, mislukt


# ───────────────────────── de epub pandoc-vast maken ─────────────────────────

def lees(raw):
    """Bytes van een (x)html-bestand -> (tekst, moet het terug de zip in?). Altijd UTF-8 zonder BOM."""
    anders = raw.startswith(b"\xef\xbb\xbf")            # pandoc laat een BOM als los teken in de tekst staan
    if anders:
        raw = raw[3:]
    m = re.match(rb"""\s*<\?xml[^>]*?encoding\s*=\s*["']([\w.:-]+)""", raw)
    enc = m.group(1).decode("ascii", "replace").lower() if m else "utf-8"
    if enc not in ("utf-8", "utf8"):
        try:
            return re.sub(r"""(encoding\s*=\s*["'])[\w.:-]+""", r"\1UTF-8", raw.decode(enc), count=1), True
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", "surrogateescape"), anders


def maak_pandoc_vast(data, voetnoten=True):
    """Geef (epub-bytes, [(pad, blokken leestekst)] voor de controle, meldingen) terug."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    names = zin.namelist()
    if CONTAINER not in names:
        return data, [], []
    opf = opf_path(zin.read(CONTAINER))
    if not opf or opf not in names:
        return data, [], []
    opfdir = posixpath.dirname(opf)
    opf_bytes = zin.read(opf)
    opf_text = opf_bytes.decode("utf-8", "surrogateescape")
    meldingen, nieuw = [], {}                           # nieuw: zip-pad -> nieuwe inhoud

    # de (x)html-bestanden
    try:
        paden = spine_documenten(opfdir, opf_bytes, set(names))
    except ET.ParseError:
        paden = []
    docs, moet_terug = {}, set()
    for pad in paden:
        tekst, anders = lees(zin.read(pad))
        docs[pad] = Doc(pad, tekst)
        if anders:
            moet_terug.add(pad)
    for doc in docs.values():
        if doc.ok:
            neutraliseer(doc)
    if voetnoten:
        stand = {pad: list(doc.edits) for pad, doc in docs.items()}
        try:
            omgezet, mislukt = koppel_noten(docs)
            if omgezet:
                meldingen.append(f"{omgezet} noten omgezet naar voetnoten" if omgezet > 1
                                 else "1 noot omgezet naar een voetnoot")
            if mislukt:
                meldingen.append(f"{mislukt} nootverwijzingen zonder vindbare noot; die blijven een gewone link"
                                 if mislukt > 1 else "1 nootverwijzing zonder vindbare noot; die blijft een gewone link")
        except Exception as e:                          # dan liever geen voetnoten dan halve
            for pad, doc in docs.items():
                doc.edits = stand[pad]
            meldingen.append(f"noten koppelen overgeslagen ({type(e).__name__}: {e}); ze blijven als tekst staan")
    for pad, doc in docs.items():
        if doc.ok:
            tekst = render(doc.text, doc.edits, 0, len(doc.text))
        else:                                           # posities onbetrouwbaar: alleen de markeringen eruit
            tekst = re.sub(r"<[a-zA-Z][^<>]*>", lambda m: ontdoe(m.group(0)), doc.text)
        if tekst != doc.text or pad in moet_terug:
            nieuw[pad] = tekst.encode("utf-8", "surrogateescape")

    # de OPF
    opf_nieuw, n_lineair = opf_meetellen(opf_text)
    if n_lineair:
        meldingen.append(f'{n_lineair} onderde{"len" if n_lineair > 1 else "el"} met linear="no" meegenomen')
    nieuwe_opf, weg = opf, set()
    if needs_repair(opfdir, opf_text):
        opf_nieuw = HREF_RE.sub(
            lambda m: m.group(1) + m.group(2) + normalize(opfdir, m.group(3)) + m.group(2), opf_nieuw)
        nieuwe_opf = posixpath.basename(opf)
        if nieuwe_opf in names:
            nieuwe_opf = "pandoc-fixed.opf"
        container = zin.read(CONTAINER).decode("utf-8", "surrogateescape")
        container = container.replace(f'full-path="{opf}"', f'full-path="{nieuwe_opf}"')
        container = container.replace(f"full-path='{opf}'", f"full-path='{nieuwe_opf}'")
        nieuw[CONTAINER] = container.encode("utf-8", "surrogateescape")
        weg.add(opf)
        meldingen.append("OPF-paden met '..' genormaliseerd")
    if opf_nieuw != opf_text:
        nieuw[nieuwe_opf] = opf_nieuw.encode("utf-8", "surrogateescape")

    bron = [(pad, doc.blokken) for pad, doc in docs.items()]
    if not nieuw:
        return data, bron, meldingen
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        if "mimetype" in names:                         # moet als eerste en ongecomprimeerd
            zout.writestr("mimetype", zin.read("mimetype"), zipfile.ZIP_STORED)
        for info in zin.infolist():
            if info.filename != "mimetype" and info.filename not in weg:
                zout.writestr(info, nieuw.pop(info.filename, None) or zin.read(info.filename), zipfile.ZIP_DEFLATED)
        for naam, inhoud in nieuw.items():              # wat er nog niet in zat (de verplaatste OPF)
            zout.writestr(naam, inhoud, zipfile.ZIP_DEFLATED)
    return out.getvalue(), bron, meldingen


# ───────────────────────── controle achteraf ─────────────────────────

OPMAAK_RE = re.compile("[*_~`\\\\­​‌‍⁠﻿]")
WOORD_RE = re.compile(r"[^\W_]+")
LINKDOEL_RE = re.compile(r"""\]\((?:<[^>\n]*>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+"[^"\n]*")?\)""")


def woorden(tekst):
    """Tekst -> woorden, zo dat epub en Markdown hetzelfde opleveren: zonder opmaaktekens
    en zonder losse getallen (nootcijfers en lijstnummers staan in Markdown anders)."""
    tekst = unicodedata.normalize("NFKC", OPMAAK_RE.sub("", tekst))
    return [w for w in WOORD_RE.findall(tekst) if not w.isdigit()]


def getal(n):
    return f"{n:,}".replace(",", ".")


def controleer(bron, uitvoer):
    """Meld elk stuk tekst (4+ woorden op rij) uit de epub dat niet in de uitvoer staat.
    Per blok (alinea, cel, kop): een woord is aanwezig als het samen met zijn buren
    ergens in de uitvoer voorkomt. Waar het staat doet er niet toe, dus verhuisde
    noten zijn geen probleem."""
    uit = [w.casefold() for w in woorden(LINKDOEL_RE.sub("] ", html.unescape(uitvoer)))]
    een, twee, drie = set(uit), set(zip(uit, uit[1:])), set(zip(uit, uit[1:], uit[2:]))
    totaal, kwijt, regels = 0, 0, []
    for pad, blokken in bron:
        ws, aanwezig = [], []
        for blok in blokken:
            laag = [w.casefold() for w in blok]
            if len(laag) < 3:
                ok = [(laag[0] in een) if len(laag) == 1 else (tuple(laag) in twee)] * len(laag)
            else:
                raak = [t in drie for t in zip(laag, laag[1:], laag[2:])]
                ok = [any(raak[max(0, i - 2):i + 1]) for i in range(len(laag))]
            ws += blok
            aanwezig += ok
        n, mist, voorbeeld, i = len(ws), 0, "", 0
        totaal += n
        while i < n:
            j = i
            while j < n and not aanwezig[j]:
                j += 1
            if j - i >= 4:
                mist += j - i
                voorbeeld = voorbeeld or " ".join(ws[i:i + 12])
            i = j + 1
        if mist:
            kwijt += mist
            regels.append(f'  {pad}: {getal(mist)} woorden, vanaf "{voorbeeld} …"')
    if kwijt:
        meld(f"LET OP: {getal(kwijt)} van de {getal(totaal)} woorden uit de epub ontbreken in de uitvoer:")
        for regel in regels:
            meld(regel)
    else:
        meld(f"controle: geen tekst kwijtgeraakt ({getal(totaal)} woorden in de epub)")


def uitvoer_van(stdout, args):
    """De tekst die pandoc schreef: stdout, of het bestand achter -o. None als dat geen tekst is."""
    data = stdout
    if not data.strip():
        for i, a in enumerate(args):
            naam = (args[i + 1] if a in ("-o", "--output") and i + 1 < len(args)
                    else a.split("=", 1)[1] if a.startswith("--output=")
                    else a[2:] if a.startswith("-o") and not a.startswith("--") and len(a) > 2 else None)
            if naam and os.path.isfile(naam):
                with open(naam, "rb") as f:
                    data = f.read()
    if not data.strip() or data.startswith(b"PK") or b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", "replace")


def main():
    args = [a for a in sys.argv[1:] if a != "--geen-voetnoten"]
    voetnoten = len(args) == len(sys.argv) - 1
    if shutil.which("pandoc") is None:
        die("pandoc niet gevonden (brew install pandoc)", 127)
    if sys.stdin.isatty():
        die("gebruik: make_markdown_from_epub < boek.epub > boek.md", 64)

    data = sys.stdin.buffer.read()
    if not zipfile.is_zipfile(io.BytesIO(data)):
        die("invoer is geen epub (geen zip) — Adobe-DRM levert een .acsm, geen boek", 65)
    bron = []
    try:
        data, bron, meldingen = maak_pandoc_vast(data, voetnoten)
        for m in meldingen:
            meld(m)
    except Exception as e:  # voorbewerking is best-effort; pandoc mag het alsnog proberen
        meld(f"voorbewerking overgeslagen ({type(e).__name__}: {e})")

    fd, tmp = tempfile.mkstemp(suffix=".epub")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        klaar = subprocess.run(["pandoc", *PANDOC_ARGS, *args, tmp], stdout=subprocess.PIPE)
    finally:
        os.unlink(tmp)
    try:
        sys.stdout.buffer.write(klaar.stdout)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass
    if klaar.returncode == 0 and bron:
        try:
            uitvoer = uitvoer_van(klaar.stdout, args)
            if uitvoer is not None:
                controleer(bron, uitvoer)
        except Exception as e:
            meld(f"controle overgeslagen ({type(e).__name__}: {e})")
    sys.exit(klaar.returncode)


if __name__ == "__main__":
    main()
