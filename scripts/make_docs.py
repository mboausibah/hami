#!/usr/bin/env python3
"""Generate the presentation: docs/Hami.pptx (python-pptx) and docs/Hami.pdf (exported by PowerPoint if installed).

    python tasks.py docs                 (= python scripts/make_docs.py)
    python scripts/make_docs.py --png DIR   also export one PNG per slide (visual QA)

Content comes from the real system: screenshots in docs/screenshots (fictional test sites), metrics of the live
model (backend/models/<current>/metrics.json), figures and sources from docs/proposal, team from docs/team.txt.
Scam domains are defanged. The PDF needs Microsoft PowerPoint (Windows); without it only the .pptx is written.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
SHOTS = DOCS / "screenshots"
OUT = DOCS / "Hami.pptx"
ICON = REPO / "clients" / "extension" / "dist" / "icons" / "icon128.png"

GREEN, GREEN2, MINT = RGBColor(0x0B, 0x5D, 0x4B), RGBColor(0x14, 0x7A, 0x63), RGBColor(0xE7, 0xF3, 0xEF)
RED, AMBER, OK = RGBColor(0xB4, 0x23, 0x18), RGBColor(0xC2, 0x8A, 0x00), RGBColor(0x1A, 0x7F, 0x37)
INK, MUTED, LINE = RGBColor(0x1D, 0x29, 0x39), RGBColor(0x5B, 0x67, 0x7A), RGBColor(0xD6, 0xDE, 0xE3)
WHITE, PALE = RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xF4, 0xF7, 0xF6)
FONT, AR_FONT = "Calibri", "Arial"
W, H = Inches(13.333), Inches(7.5)


# ---- helpers -------------------------------------------------------------------------------------------------
def _arabic(run) -> None:
    rpr = run._r.get_or_add_rPr()
    rpr.set("lang", "ar-AE")
    for tag in ("a:cs",):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", AR_FONT)


def text(slide, x, y, w, h, content, size=16, bold=False, color=INK, align=PP_ALIGN.LEFT, rtl=False,
         anchor=MSO_ANCHOR.TOP, italic=False, name="text", space_after=0, font=FONT):
    """content: str (one paragraph per line) or list of paragraphs; a paragraph is str or list of (text, opts)."""
    box = slide.shapes.add_textbox(x, y, w, h)
    box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = content.split("\n") if isinstance(content, str) else content
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.RIGHT if rtl else align
        if rtl:
            p._p.get_or_add_pPr().set("rtl", "1")
        if space_after:
            p.space_after = Pt(space_after)
        runs = [(para, {})] if isinstance(para, str) else para
        for t, o in runs:
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = o.get("font", font)
            f.size = Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", italic)
            f.color.rgb = o.get("color", color)
            if rtl or re.search(r"[؀-ۿ]", t):
                _arabic(r)
    return box


def box(slide, x, y, w, h, fill=PALE, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name="card", radius=0.08):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    s.name = name
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.text_frame.text = ""
    return s


def circle(slide, x, y, d, glyph, fill=GREEN, color=WHITE, size=18, name="badge"):
    s = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, d, d)
    s.name = name
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    s.line.fill.background()
    s.shadow.inherit = False
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = glyph
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), True, color, FONT
    return s


def arrow(slide, x1, y1, x2, y2, color=MUTED, width=1.75):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    c.line.color.rgb = color
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    return c


def picture(slide, path, x, y, w=None, h=None, crop_bottom=0.0, crop_top=0.0, name="screenshot", border=True,
            max_h=None):
    pic = slide.shapes.add_picture(str(path), x, y, w, h)
    pic.name = name
    if max_h is not None and pic.height > max_h:
        crop_bottom = 1 - max_h / pic.height
    if crop_bottom or crop_top:
        # keep the shape's width; shorten it by the cropped fraction
        full_h = pic.height
        pic.crop_bottom, pic.crop_top = crop_bottom, crop_top
        pic.height = int(full_h * (1 - crop_bottom - crop_top))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(0.75)
    return pic


def title(slide, t, sub=None, dark=False):
    text(slide, Inches(0.6), Inches(0.42), Inches(12.1), Inches(0.75), t, size=34, bold=True,
         color=WHITE if dark else GREEN, name="title")
    if sub:
        text(slide, Inches(0.6), Inches(1.12), Inches(12.1), Inches(0.45), sub, size=16,
             color=MINT if dark else MUTED, name="subtitle")


def blank(prs, dark=False):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = GREEN if dark else WHITE
    return s


def footer(slide, n, dark=False):
    text(slide, Inches(0.6), Inches(7.02), Inches(8), Inches(0.3), "Hami حامي · ScamShield AI", size=10,
         color=MINT if dark else MUTED, name="footer")
    text(slide, Inches(11.9), Inches(7.02), Inches(0.83), Inches(0.3), str(n), size=10,
         color=MINT if dark else MUTED, align=PP_ALIGN.RIGHT, name="page")


def team() -> list[tuple[str, str]]:
    f = DOCS / "team.txt"
    out = []
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "—" in line:
                name, role = [x.strip() for x in line.split("—", 1)]
                out.append(("" if name.startswith("[") else name, role))
    return out


def metrics() -> dict:
    reg = json.loads((REPO / "backend/models/registry.json").read_text(encoding="utf-8"))
    return json.loads((REPO / "backend/models" / reg["current"] / "metrics.json").read_text(encoding="utf-8")) | {
        "_version": reg["current"]}


# ---- slides --------------------------------------------------------------------------------------------------
def s_title(prs, team_rows):
    s = blank(prs, dark=True)
    if ICON.is_file():
        s.shapes.add_picture(str(ICON), Inches(0.8), Inches(1.15), Inches(1.15), Inches(1.15))
    text(s, Inches(0.8), Inches(2.55), Inches(6), Inches(1.3), "Hami", size=80, bold=True, color=WHITE, name="brand")
    text(s, Inches(6.4), Inches(2.55), Inches(6.1), Inches(1.3), "حامي", size=80, bold=True, color=WHITE, rtl=True,
         name="brand-ar")
    text(s, Inches(0.8), Inches(4.05), Inches(11.7), Inches(0.6),
         "Warns people about fraudulent websites before they pay", size=26, color=WHITE, name="tagline")
    text(s, Inches(0.8), Inches(4.7), Inches(11.7), Inches(0.6), "يحذّرك من المواقع الاحتيالية قبل أن تدفع", size=24,
         color=MINT, rtl=True, name="tagline-ar")
    roles = " · ".join(n or r for n, r in team_rows) if team_rows else ""
    text(s, Inches(0.8), Inches(6.05), Inches(11.7), Inches(0.4),
         "ScamShield AI hackathon · AD Police × 42 Abu Dhabi", size=16, bold=True, color=WHITE, name="event")
    if roles:
        text(s, Inches(0.8), Inches(6.5), Inches(11.7), Inches(0.4), roles, size=13, color=MINT, name="team")
    s.notes_slide.notes_text_frame.text = ("Hami means protector. A Chrome extension plus an analysis server that "
                                            "warns people about scam websites before they pay, in Arabic and English.")


def s_problem(prs, n):
    s = blank(prs)
    title(s, "Scams in the UAE move faster than reports",
          "2024 national survey by the UAE Cybersecurity Council and TRENDS Research & Advisory")
    stats = [("56%", "receive a scam attempt\nat least once a month"), ("27%", "have lost money"),
             ("USD 2,194", "average loss"), ("~50%", "of scams completed within\n24 hours of first contact"),
             ("30%", "report scams to\nlaw enforcement"), ("9%", "of victims recovered\ntheir losses in full")]
    cw, ch, gx, gy = Inches(3.85), Inches(2.1), Inches(0.28), Inches(0.28)
    for i, (big, label) in enumerate(stats):
        x = Inches(0.6) + (cw + gx) * (i % 3)
        y = Inches(1.85) + (ch + gy) * (i // 3)
        box(s, x, y, cw, ch, fill=MINT if i not in (1, 5) else RGBColor(0xFB, 0xEA, 0xE8), name=f"stat-{i}")
        text(s, x + Inches(0.3), y + Inches(0.25), cw - Inches(0.6), Inches(0.95), big, size=48, bold=True,
             color=RED if i in (1, 5) else GREEN, name=f"stat-num-{i}")
        text(s, x + Inches(0.3), y + Inches(1.2), cw - Inches(0.6), Inches(0.85), label, size=16, color=INK,
             name=f"stat-label-{i}")
    text(s, Inches(0.6), Inches(6.62), Inches(12.1), Inches(0.35),
         "Sources: Gulf News (2024 State of Scams survey; Abu Dhabi Police on search-engine links, 2026); Khaleej Times "
         "(Dubai Police on part-time job offers, Oct 2026); The National (short-lived fake sites).",
         size=10, color=MUTED, name="sources")
    footer(s, n)
    s.notes_slide.notes_text_frame.text = ("Scam contact is routine and money moves within a day. Police also warn "
                                            "about fraudulent links in search results and fake recruitment sites.")


def s_scam(prs, n):
    s = blank(prs)
    title(s, "How task and deposit scams take the money",
          "The pattern behind most job, task, gambling and investment portals targeting the UAE")
    steps = [("1", "The offer", "WhatsApp, Telegram or a search ad offers easy part-time work: rate products, complete orders."),
             ("2", "Small wins", "The victim registers and earns small commissions, so the portal looks real."),
             ("3", "Recharge to unlock", "Higher VIP levels and bigger tasks need deposits: AED 500, then 1,500, then 5,000."),
             ("4", "No way out", "Withdrawals stay blocked until more fees are paid. Then the site disappears.")]
    cw, gap = Inches(2.75), Inches(0.37)
    for i, (num, head, body) in enumerate(steps):
        x = Inches(0.6) + (cw + gap) * i
        box(s, x, Inches(1.95), cw, Inches(2.6), fill=PALE, name=f"step-{num}")
        circle(s, x + Inches(0.25), Inches(2.18), Inches(0.62), num, fill=RED if num == "3" else GREEN, size=20)
        text(s, x + Inches(0.25), Inches(2.98), cw - Inches(0.5), Inches(0.45), head, size=19, bold=True,
             name=f"step-head-{num}")
        text(s, x + Inches(0.25), Inches(3.45), cw - Inches(0.5), Inches(1.05), body, size=14, color=MUTED,
             name=f"step-body-{num}")
        if i < 3:
            arrow(s, x + cw + Inches(0.04), Inches(3.25), x + cw + gap - Inches(0.04), Inches(3.25))
    box(s, Inches(0.6), Inches(4.95), Inches(12.1), Inches(1.75), fill=GREEN, name="why-hard")
    text(s, Inches(0.95), Inches(5.12), Inches(11.4), Inches(0.45), "Why existing checks miss it", size=19,
         bold=True, color=WHITE, name="why-head")
    text(s, Inches(0.95), Inches(5.6), Inches(11.4), Inches(1.0),
         [[("Behind a sign-in wall: ", {"bold": True}), ("the public page is just a login form.", {})],
          [("Days-old domains, constant rebrands: ", {"bold": True}), ("blocklists are always behind.", {})],
          [("Arabic and English: ", {"bold": True}), ("URL-only classifiers never read what the page asks for.", {})]],
         size=15, color=WHITE, name="why-body")
    footer(s, n)


def s_what(prs, n):
    s = blank(prs)
    title(s, "Hami reads what a page asks you to do with money", "One result: a tier, the evidence behind it, what to do now")
    picture(s, SHOTS / "01_result_card_en.png", Inches(0.6), Inches(1.75), w=Inches(2.55), max_h=Inches(4.95))
    picture(s, SHOTS / "02_result_card_ar.png", Inches(3.35), Inches(1.75), w=Inches(2.55), max_h=Inches(4.95))
    rows = [("!", "Behavior, not just the URL", "Deposit to unlock, advance fees, gambling deposits, investment promises, credential requests, in Arabic and English."),
            ("⌂", "Sees through sign-in walls", "Fingerprints the software a site delivers and reads its own code, without ever signing in."),
            ("⌕", "Where links are met", "Toolbar and right-click checks, Google Search shields, Google Maps listing vs. website."),
            ("✓", "Explains every decision", "Up to three clues citing the sentence, file or confirmed case behind them.")]
    for i, (g, head, body) in enumerate(rows):
        y = Inches(1.8) + Inches(1.02) * i
        circle(s, Inches(6.35), y, Inches(0.58), g, size=18)
        text(s, Inches(7.15), y - Inches(0.03), Inches(5.55), Inches(0.4), head, size=18, bold=True, name=f"row-h-{i}")
        text(s, Inches(7.15), y + Inches(0.36), Inches(5.55), Inches(0.62), body, size=13, color=MUTED, name=f"row-b-{i}")
    box(s, Inches(6.35), Inches(5.95), Inches(6.35), Inches(0.82), fill=MINT, name="ar-quote")
    text(s, Inches(6.6), Inches(6.05), Inches(5.85), Inches(0.62),
         "هذه الصفحة تطلب دفع مبلغ لفتح المهام المدفوعة. لا تدفع.\nتحقق من جهة العمل عبر قناة رسمية.",
         size=15, color=GREEN, rtl=True, anchor=MSO_ANCHOR.MIDDLE, name="ar-warning")
    footer(s, n)


def s_arch(prs, n):
    s = blank(prs)
    title(s, "Architecture: capture once, analyze offline", "Runs on the user's computer today; the same stack moves to a server with one command")
    box(s, Inches(0.6), Inches(1.9), Inches(3.0), Inches(3.3), fill=MINT, name="ext")
    text(s, Inches(0.85), Inches(2.05), Inches(2.5), Inches(0.45), "Chrome extension", size=18, bold=True, color=GREEN)
    text(s, Inches(0.85), Inches(2.55), Inches(2.6), Inches(2.6),
         ["On-device pre-filter", "Local confirmed list", "Consent, badge, banner", "Search shields · Maps check",
          "Idle snapshot (metadata)", "Investigator mode (.har)"], size=13, color=INK, space_after=4)
    arrow(s, Inches(3.65), Inches(3.55), Inches(4.25), Inches(3.55), color=GREEN, width=2.25)
    box(s, Inches(4.3), Inches(1.9), Inches(8.4), Inches(3.3), fill=PALE, line=LINE, name="api")
    text(s, Inches(4.55), Inches(2.05), Inches(7.9), Inches(0.45), "Hami API (FastAPI) · local or hosted", size=18,
         bold=True, color=GREEN)
    stages = [("Capture", "Playwright, fresh context, at most 20 s, never signs in"),
              ("Sanitize", "Removes cookies, tokens, e-mails and phones; hashes every body"),
              ("Analyze", "Page text, delivered code and delivered files (kit)"),
              ("Score", "Rules decide the tier; a calibrated model confirms")]
    sw = Inches(1.83)
    for i, (head, body) in enumerate(stages):
        x = Inches(4.55) + (sw + Inches(0.2)) * i
        box(s, x, Inches(2.65), sw, Inches(1.45), fill=WHITE, line=LINE, name=f"stage-{i}")
        text(s, x + Inches(0.15), Inches(2.75), sw - Inches(0.3), Inches(0.4), head, size=16, bold=True, color=GREEN)
        text(s, x + Inches(0.15), Inches(3.15), sw - Inches(0.3), Inches(0.9), body, size=12, color=MUTED)
        if i < 3:
            arrow(s, x + sw + Inches(0.02), Inches(3.37), x + sw + Inches(0.18), Inches(3.37))
    text(s, Inches(4.55), Inches(4.35), Inches(7.9), Inches(0.7),
         [[("Stored: ", {"bold": True, "color": INK}),
           ("database (SQLite, or PostgreSQL with --profile postgres) · content-addressed artifacts (HAR, HTML, "
            "screenshots) · every artifact hashed", {})]], size=13, color=MUTED)
    lower = [("Reviewer console", "labels, link approval, alerts,\nclusters, case briefs"),
             ("Discovery worker", "certificate-transparency logs →\nsafe capture → review queue"),
             ("Training pipeline", "dataset version → candidate →\nkit-grouped CV → promotion rule")]
    lw = Inches(3.9)
    for i, (head, body) in enumerate(lower):
        x = Inches(0.6) + (lw + Inches(0.2)) * i
        box(s, x, Inches(5.5), lw, Inches(1.3), fill=GREEN, name=f"lower-{i}")
        text(s, x + Inches(0.25), Inches(5.6), lw - Inches(0.5), Inches(0.4), head, size=16, bold=True, color=WHITE)
        text(s, x + Inches(0.25), Inches(6.0), lw - Inches(0.5), Inches(0.75), body, size=12, color=MINT)
    footer(s, n)


def s_kit(prs, n):
    s = blank(prs)
    title(s, "Sign-in walls: one scam kit, many brands", "Hami matches the software a site delivers, so a new login page is caught at once")
    # three sites
    sites = [("aed99[.]com", "confirmed by our review", RED, Inches(0.6), Inches(1.95)),
             ("betnala[.]com", "never reviewed", AMBER, Inches(0.6), Inches(4.1)),
             ("betfugu[.]com", "never reviewed", AMBER, Inches(4.35), Inches(4.1))]
    for host, sub, col, x, y in sites:
        box(s, x, y, Inches(3.3), Inches(1.15), fill=WHITE, line=col, name=host)
        circle(s, x + Inches(0.2), y + Inches(0.27), Inches(0.6), "!" if col == RED else "?", fill=col, size=20)
        text(s, x + Inches(0.95), y + Inches(0.2), Inches(2.25), Inches(0.42), host, size=18, bold=True)
        text(s, x + Inches(0.95), y + Inches(0.64), Inches(2.25), Inches(0.35), sub, size=12, color=MUTED)
    arrow(s, Inches(2.25), Inches(3.12), Inches(2.25), Inches(4.08), color=RED, width=2.25)
    arrow(s, Inches(3.4), Inches(3.05), Inches(5.6), Inches(4.08), color=RED, width=2.25)
    text(s, Inches(2.45), Inches(3.35), Inches(1.6), Inches(0.5), "26 identical\nfiles", size=12, bold=True, color=RED)
    text(s, Inches(4.75), Inches(3.2), Inches(1.7), Inches(0.5), "13 identical\nfiles", size=12, bold=True, color=RED)
    text(s, Inches(0.6), Inches(5.5), Inches(7.1), Inches(1.4),
         [[("Same build: ", {"bold": True, "color": INK}),
           ("21 JS/CSS files byte-identical across all three in our captures, incl. views-vipNew, views-luckyspin and "
            "the en-US language pack.", {})],
          [("Their own code says it: ", {"bold": True, "color": INK}),
           ("the language pack mentions “withdraw” 38× and “deposit” 16×.", {})],
          [("Result: ", {"bold": True, "color": INK}),
           ("a fresh install rates both new brands High risk from the seeded kit, with no private data.", {})]],
         size=13, color=MUTED, space_after=5)
    picture(s, SHOTS / "07_signin_wall_kit_match.png", Inches(8.25), Inches(1.75), w=Inches(2.25), max_h=Inches(3.1))
    picture(s, SHOTS / "03_toolbar_badge.png", Inches(8.25), Inches(5.1), w=Inches(4.45))
    text(s, Inches(8.25), Inches(5.95), Inches(4.45), Inches(0.6),
         "Automatic check on the login wall: red badge and banner, no click needed.", size=12, color=MUTED)
    text(s, Inches(10.7), Inches(1.8), Inches(2.0), Inches(2.9),
         "Same idea on the fictional test kit: a login wall (Quorvia) running the build of a confirmed scam "
         "(NovaMart VIP) is High risk, and the banner appears without a click.", size=12, color=MUTED)
    footer(s, n)
    s.notes_slide.notes_text_frame.text = ("SHA-256, build-hashed file names and near-identical sketches; common libraries "
                                            "and files seen on legitimate sites never count. Strong match = 3+ distinctive files.")


def s_privacy(prs, n):
    s = blank(prs)
    title(s, "Automatic checking that does not watch people", "Decided on the device; only the least that answers the question goes to Hami's own server")
    cols = [("On the device, nothing sent", GREEN, ["Banks, government, health and well-known sites skipped",
                                                    "Confirmed sites: red banner from the local list",
                                                    "Kit file names matched locally"]),
            ("Sent only after consent", AMBER, ["Candidate page URLs: at most 30 an hour",
                                                "Idle snapshot: resource URLs without queries, timings, redacted text",
                                                "Search: result hostnames only, if turned on"]),
            ("Never sent", RED, ["Browsing history or search queries", "Cookies, headers, bodies, storage",
                                 "Anything to third parties"])]
    cw = Inches(3.9)
    for i, (head, col, items) in enumerate(cols):
        x = Inches(0.6) + (cw + Inches(0.2)) * i
        box(s, x, Inches(1.85), cw, Inches(2.3), fill=PALE, name=f"priv-{i}")
        circle(s, x + Inches(0.25), Inches(2.05), Inches(0.5), "✓" if i == 0 else ("i" if i == 1 else "✕"), fill=col,
               size=16)
        text(s, x + Inches(0.9), Inches(2.1), cw - Inches(1.1), Inches(0.45), head, size=17, bold=True)
        text(s, x + Inches(0.25), Inches(2.75), cw - Inches(0.5), Inches(1.8), items, size=13, color=INK, space_after=6)
    text(s, Inches(0.6), Inches(4.4), Inches(12.1), Inches(1.0),
         [[("Investigator mode ", {"bold": True, "color": INK}),
           ("(off by default): full HAR via chrome.debugger only after optional permissions; sanitized on the device, "
            "saved as .har with SHA-256, uploaded only if the user agrees; never on skipped sites.", {})],
          [("Capture browser ", {"bold": True, "color": INK}),
           ("never signs in, submits forms, pays, downloads or follows discovered links.", {})]],
         size=14, color=MUTED, space_after=6)
    picture(s, SHOTS / "05_search_shields.png", Inches(0.6), Inches(5.45), h=Inches(1.4), border=True)
    text(s, Inches(5.65), Inches(5.9), Inches(7.05), Inches(0.6),
         "Search shields: red from the local list, green from a hostname lookup, grey when unknown.", size=12,
         color=MUTED)
    footer(s, n)


def s_model(prs, n, m):
    s = blank(prs)
    ho, cv, bl = m["held_out"]["overall"], m["kit_cv"]["overall"], m["baselines"]
    title(s, "Model choices and real metrics",
          f"Rules decide the tier, a calibrated logistic regression confirms · live model {m['_version']}")
    stats = [(f"{ho['precision']:.3f}", "precision"), (f"{ho['recall']:.3f}", "recall"),
             (f"{ho['fpr_legit'] * 100:.1f}%", "false alarms on\nlegitimate pages")]
    for i, (big, lab) in enumerate(stats):
        x = Inches(0.6) + Inches(2.05) * i
        box(s, x, Inches(1.85), Inches(1.9), Inches(1.65), fill=MINT, name=f"m-{i}")
        text(s, x + Inches(0.2), Inches(1.98), Inches(1.6), Inches(0.75), big, size=34, bold=True, color=GREEN)
        text(s, x + Inches(0.2), Inches(2.75), Inches(1.6), Inches(0.7), lab, size=12, color=INK)
    text(s, Inches(0.6), Inches(3.62), Inches(6.0), Inches(0.35),
         f"Held-out test: {ho['n']} pages, kits never seen in training. Kit-grouped {m['kit_cv']['folds']}-fold CV "
         f"({m['kit_cv']['kits']:,} kits): {cv['precision']:.3f} / {cv['recall']:.3f} / {cv['fpr_legit'] * 100:.1f}%.",
         size=12, color=MUTED)
    pst = m["kit_cv"]["per_scam_type"]
    rows = [("Task scam", pst["task_scam"]), ("Phishing", pst["phishing"]), ("Gambling deposit", pst["gambling_deposit"]),
            ("Fake shop · investment · other", {"recall": 1.0, "n": pst["fake_shop"]["n"] + pst["investment"]["n"] + pst["other"]["n"]})]
    text(s, Inches(0.6), Inches(4.2), Inches(6.0), Inches(0.4), "Recall by scam type (kit-grouped CV)", size=15, bold=True)
    for i, (name, r) in enumerate(rows):
        y = Inches(4.65) + Inches(0.42) * i
        text(s, Inches(0.6), y, Inches(3.3), Inches(0.35), name, size=13)
        bar_w = Inches(2.1) * r["recall"]
        box(s, Inches(3.9), y + Inches(0.05), Inches(2.1), Inches(0.26), fill=PALE, shape=MSO_SHAPE.RECTANGLE, name=f"bg-{i}")
        box(s, Inches(3.9), y + Inches(0.05), int(bar_w), Inches(0.26), fill=GREEN2, shape=MSO_SHAPE.RECTANGLE, name=f"bar-{i}")
        text(s, Inches(6.08), y, Inches(0.9), Inches(0.35), f"{r['recall']:.2f}", size=13, bold=True, color=GREEN)
    text(s, Inches(0.6), Inches(6.42), Inches(6.2), Inches(0.5),
         "Unseen legitimate pages: 0 of 50 flagged (95% bound ≈ 6%); sign-up pages: 0 High, 2 Caution of 31. "
         "Brand-new scam family: 1 of 1 flagged (Caution).", size=11, color=MUTED)
    cd = CategoryChartData()
    cd.categories = ["URL only", "URL + page text", "Full detector"]
    cd.add_series("Recall", [bl["url_only"]["recall"], bl["url_plus_text"]["recall"], bl["full_model"]["recall"]])
    cd.add_series("False-alarm rate", [bl["url_only"]["fpr_legit"], bl["url_plus_text"]["fpr_legit"],
                                       bl["full_model"]["fpr_legit"]])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(7.2), Inches(1.75), Inches(5.5), Inches(4.65), cd)
    gf.name = "baseline-chart"
    ch = gf.chart
    ch.has_title = True
    ch.chart_title.text_frame.text = f"Same test pages (n = {bl['n_test_with_url']}): reading the page matters"
    tp = ch.chart_title.text_frame.paragraphs[0]
    tp.runs[0].font.size, tp.runs[0].font.bold, tp.runs[0].font.color.rgb, tp.runs[0].font.name = Pt(13), True, INK, FONT
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size, ch.legend.font.name, ch.legend.font.color.rgb = Pt(12), FONT, INK
    for ser, col in zip(ch.series, (GREEN, RED)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = col
    plot = ch.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = "0.00", False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size, dl.font.name, dl.font.color.rgb = Pt(12), FONT, INK
    va = ch.value_axis
    va.maximum_scale, va.minimum_scale = 1.0, 0
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = LINE
    va.tick_labels.font.size, va.tick_labels.font.color.rgb = Pt(11), MUTED
    va.format.line.fill.background()
    ca = ch.category_axis
    ca.tick_labels.font.size, ca.tick_labels.font.color.rgb, ca.tick_labels.font.name = Pt(12), INK, FONT
    ca.format.line.color.rgb = LINE
    footer(s, n)
    s.notes_slide.notes_text_frame.text = ("Logistic regression on TF-IDF word and character n-grams plus structured "
                                            "indicators; Arabic normalized first; all variants of a kit stay in one split; "
                                            "thresholds tuned out-of-fold; promotion rule: recall not lower and FPR not higher.")


def s_investigator(prs, n):
    s = blank(prs)
    title(s, "Investigator view: leads with evidence, not guesses", "Reviewer console, linked sites and an exportable case brief")
    picture(s, SHOTS / "09_console_case_kit_match.png", Inches(0.6), Inches(1.75), w=Inches(5.9), max_h=Inches(3.4))
    picture(s, SHOTS / "10_case_brief.png", Inches(6.8), Inches(1.75), w=Inches(5.9), max_h=Inches(3.4))
    items = [("1", "Clusters", "Same kit, shared infrastructure, redirect/invite gateways, registration-page template reuse; reviewers approve each link."),
             ("2", "Case brief", "Defanged URLs, first/last seen, evidence with SHA-256, observations kept apart from inferences."),
             ("3", "Investigator mode", "A sanitized .har from the browser, hashed on the device and verified by the server.")]
    for i, (num, head, body) in enumerate(items):
        x = Inches(0.6) + Inches(4.1) * i
        circle(s, x, Inches(5.45), Inches(0.5), num, size=16)
        text(s, x + Inches(0.65), Inches(5.43), Inches(3.3), Inches(0.4), head, size=16, bold=True)
        text(s, x + Inches(0.65), Inches(5.85), Inches(3.3), Inches(1.0), body, size=12, color=MUTED)
    footer(s, n)


def s_live(prs, n):
    s = blank(prs)
    title(s, "Live results on real UAE scam sites", "Server-side checks with the repository's code and seed, no private data · scans in 5–17 seconds · 23–24 Nov 2026")
    rows = [("Site", "What Hami saw", "Result"),
            ("betnala[.]com", "Login wall · 26 files identical to confirmed aed99 · own code mentions deposits 51×, withdrawals 34×", "High risk"),
            ("betfugu[.]com", "Login wall · 13 identical files with the confirmed kit", "High risk"),
            ("cs.aed99[.]com", "Support subdomain of the confirmed aed99.com", "High risk"),
            ("app.u340cbye[.]xyz", "Never-seen family behind a bot challenge · invite code in the address · first certificate 87 days ago", "Caution"),
            ("bayt.com", "Legitimate UAE job board", "No strong signals"),
            ("50 unseen legitimate pages", "Job boards, shops, gig and micro-task platforms not in training", "0 High · 0 Caution"),
            ("38 legitimate sign-up pages", "Banks, telecoms, shops, job boards, gig, government, 5 referral links (31 loaded)", "0 High · 2 Caution")]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.75), Inches(12.1), Inches(4.4)).table
    for j, wdt in enumerate((Inches(3.0), Inches(6.6), Inches(2.5))):
        tbl.columns[j].width = wdt
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(0.55 if i else 0.45)
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = GREEN if i == 0 else (PALE if i % 2 else WHITE)
            cell.margin_left = cell.margin_right = Inches(0.15)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = val
            col = WHITE if i == 0 else INK
            if i and j == 2:
                col = RED if val == "High risk" else (AMBER if val == "Caution" else OK)
            r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(15 if j != 1 else 13), (i == 0 or j != 1), col, FONT
    text(s, Inches(0.6), Inches(6.3), Inches(12.1), Inches(0.6),
         "betnala and betfugu were never reviewed by us: they are caught by the seeded fingerprint of one confirmed case. "
         "Scam domains are defanged.", size=12, color=MUTED)
    footer(s, n)


def s_roadmap(prs, n):
    s = blank(prs)
    title(s, "Roadmap", "This submission: Chrome extension + local backend, hosted database one command away")
    phases = [("1", "Phones", "iOS and Android apps with share-to-app from WhatsApp and Messages, same bilingual card."),
              ("2", "Hosted service", "UAE North deployment, shared reviewer decisions, push alerts, role-based access."),
              ("3", "Coverage", "Screenshot OCR, more labeled kits (gambling, investment, parcel), Arabic look-alikes."),
              ("4", "Police integration", "Intake from reporting channels such as Aman, STIX export, campaign briefs.")]
    line_y = Inches(2.62)
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1.0), line_y, Inches(12.3), line_y)
    ln.line.color.rgb, ln.line.width = LINE, Pt(3)
    cw = Inches(2.9)
    for i, (num, head, body) in enumerate(phases):
        x = Inches(0.6) + (cw + Inches(0.17)) * i
        circle(s, x + Inches(0.1), Inches(2.25), Inches(0.74), num, size=22)
        box(s, x, Inches(3.3), cw, Inches(2.15), fill=PALE, name=f"phase-{num}")
        text(s, x + Inches(0.25), Inches(3.5), cw - Inches(0.5), Inches(0.45), head, size=19, bold=True, color=GREEN)
        text(s, x + Inches(0.25), Inches(4.05), cw - Inches(0.5), Inches(1.75), body, size=14, color=INK)
    text(s, Inches(0.6), Inches(5.8), Inches(12.1), Inches(0.5),
         "Deployment is documented (docs/DEPLOY.md): docker compose --profile postgres --profile https up on a cloud VM.",
         size=13, color=MUTED)
    footer(s, n)


def s_team(prs, n, team_rows):
    s = blank(prs, dark=True)
    title(s, "Team", dark=True)
    for i, (name, role) in enumerate(team_rows[:5]):
        y = Inches(1.6) + Inches(0.78) * i
        circle(s, Inches(0.6), y, Inches(0.55), str(i + 1), fill=WHITE, color=GREEN, size=16)
        text(s, Inches(1.35), y + Inches(0.08), Inches(6.5), Inches(0.45), [[(name + " · " if name else "", {"bold": True}),
                                                                              (role, {})]], size=18, color=WHITE)
    text(s, Inches(0.6), Inches(5.75), Inches(7.5), Inches(0.4), "github.com/mboausibah/hami", size=18, bold=True,
         color=WHITE)
    text(s, Inches(0.6), Inches(6.2), Inches(7.5), Inches(0.4), "Development used Claude Code (Anthropic).", size=13,
         color=MINT)
    text(s, Inches(8.3), Inches(2.4), Inches(4.4), Inches(1.4), "شكرًا", size=72, bold=True, color=WHITE, rtl=True)
    text(s, Inches(8.3), Inches(3.9), Inches(4.4), Inches(0.6), "Thank you", size=28, color=MINT, align=PP_ALIGN.RIGHT)
    footer(s, n, dark=True)


def export_pdf(pptx: Path, pdf: Path, png_dir: Path | None) -> bool:
    if os.name != "nt":
        return False
    png = ""
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)
        png = (f"$i = 1; foreach ($sl in $pres.Slides) {{ $sl.Export('{png_dir}\\slide-' + $i.ToString('00') + '.png', "
               f"'PNG', 1600, 900); $i++ }}")
    ps = (f"$pp = New-Object -ComObject PowerPoint.Application; "
          f"$pres = $pp.Presentations.Open('{pptx}', $true, $false, $false); "
          f"$pres.SaveAs('{pdf}', 32); {png}; $pres.Close(); $pp.Quit()")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0 or not pdf.is_file():
        print("PDF export skipped (needs Microsoft PowerPoint):", (r.stderr or r.stdout).strip()[:300])
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", help="also export one PNG per slide into this folder (visual QA)")
    args = ap.parse_args()
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    prs.core_properties.title = "Hami حامي - ScamShield AI"
    prs.core_properties.author = "Hami team"
    team_rows = team()
    m = metrics()
    s_title(prs, team_rows)
    for i, fn in enumerate((s_problem, s_scam, s_what, s_arch, s_kit, s_privacy), start=2):
        fn(prs, i)
    s_model(prs, 8, m)
    s_investigator(prs, 9)
    s_live(prs, 10)
    s_roadmap(prs, 11)
    s_team(prs, 12, team_rows)
    prs.save(OUT)
    pdf = OUT.with_suffix(".pdf")
    ok = export_pdf(OUT, pdf, Path(args.png).resolve() if args.png else None)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {len(prs.slides)} slides)"
          + (f" and {pdf} ({pdf.stat().st_size / 1e6:.1f} MB)" if ok else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
