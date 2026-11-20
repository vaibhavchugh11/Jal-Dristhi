"""Turns the report blocks into a PDF, an HTML page and a ZIP of tables."""
import base64
import html as _html
import io
import os
import zipfile
from xml.sax.saxutils import escape

import pandas as pd

from . import standards as std

PRI_FILL = {"high": "#d64545", "medium": "#f28c28", "low": "#6c8ebf"}


def _lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def fg_for(fill):
    return "#ffffff" if _lum(fill) < 140 else "#222222"


def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        import matplotlib
        d = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        pdfmetrics.registerFont(TTFont("DJ", os.path.join(d, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DJ-B", os.path.join(d, "DejaVuSans-Bold.ttf")))
        return "DJ", "DJ-B"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def to_pdf(rep):
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, Image, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    reg, bold = _fonts()
    W = A4[0] - 3.4 * cm
    S = {
        "title": ParagraphStyle("title", fontName=bold, fontSize=19, leading=23, textColor=colors.HexColor("#1a5fb4"), spaceAfter=2),
        "sub": ParagraphStyle("sub", fontName=reg, fontSize=10.5, leading=13, textColor=colors.HexColor("#555555"), spaceAfter=8),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=13, leading=16, textColor=colors.HexColor("#1a5fb4"), spaceBefore=14, spaceAfter=5, keepWithNext=1),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=10.5, leading=13, spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "h3": ParagraphStyle("h3", fontName=bold, fontSize=9, leading=11.5, spaceBefore=5, spaceAfter=2, textColor=colors.HexColor("#333333"), keepWithNext=1),
        "p": ParagraphStyle("p", fontName=reg, fontSize=8.8, leading=11.8, spaceAfter=4),
        "ps": ParagraphStyle("ps", fontName=reg, fontSize=7.4, leading=9.6, spaceAfter=3, textColor=colors.HexColor("#555555")),
        "cell": ParagraphStyle("cell", fontName=reg, fontSize=8, leading=10),
        "cells": ParagraphStyle("cells", fontName=reg, fontSize=7, leading=8.8),
        "cap": ParagraphStyle("cap", fontName=reg, fontSize=7.2, leading=9, textColor=colors.HexColor("#555555"), alignment=1, spaceAfter=6),
    }

    def para(text, style):
        return Paragraph(escape(str(text)), style)

    story = []
    for b in rep.doc:
        t = b["t"]
        if t == "title":
            story += [Paragraph(escape(b["text"]), S["title"]), Paragraph(escape(b.get("sub", "")), S["sub"])]
        elif t in ("h1", "h2", "h3"):
            if t == "h1":
                story.append(CondPageBreak(5 * cm))
            story.append(Paragraph(escape(b["text"]), S[t]))
        elif t == "p":
            story.append(para(b["text"], S["ps"] if b.get("small") else S["p"]))
        elif t == "bullets":
            story.append(ListFlowable([ListItem(para(x, S["p"])) for x in b["items"]], bulletType="bullet", leftIndent=12, bulletFontSize=6))
        elif t == "img":
            if b.get("bytes"):
                w, h = PILImage.open(io.BytesIO(b["bytes"])).size
                width = W
                items = [Image(io.BytesIO(b["bytes"]), width=width, height=width * h / w)]
                if b.get("caption"):
                    items.append(Paragraph(escape(b["caption"]), S["cap"]))
                story.append(KeepTogether(items))
        elif t == "card":
            col = colors.HexColor(b["fill"])
            fg = b["fg"]
            inner = [Paragraph(f'<font color="{fg}">{escape(b["title"])}</font>', ParagraphStyle("ct", fontName=bold, fontSize=13, leading=16))]
            inner += [Paragraph(f'<font color="{fg}">{escape(x)}</font>', ParagraphStyle("cl", fontName=reg, fontSize=8.8, leading=11.5, spaceBefore=2)) for x in b["lines"]]
            tb = Table([[inner]], colWidths=[W])
            tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                                    ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
            story += [tb, Spacer(1, 6)]
        elif t == "chips":
            items = b["items"]
            per = 5
            for i in range(0, len(items), per):
                grp = items[i:i + per]
                cells = []
                for c in grp:
                    cells.append([Paragraph(f'<font color="{c["fg"]}" size="7">{escape(c["label"])}</font>', S["cell"]),
                                  Paragraph(f'<font color="{c["fg"]}"><b>{escape(c["value"])}</b></font>', ParagraphStyle("cv", fontName=bold, fontSize=10, leading=12)),
                                  Paragraph(f'<font color="{c["fg"]}" size="7">{escape(c["sub"])}</font>', S["cell"])])
                cw = W / per
                tb = Table([cells], colWidths=[cw] * len(cells))
                st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEAFTER", (0, 0), (-2, -1), 3, colors.white)]
                for j, c in enumerate(grp):
                    st.append(("BACKGROUND", (j, 0), (j, 0), colors.HexColor(c["fill"])))
                tb.setStyle(TableStyle(st))
                story += [tb, Spacer(1, 3)]
        elif t == "callout":
            col = colors.HexColor(PRI_FILL.get(b["level"], "#6c8ebf"))
            inner = [Paragraph(f"<b>{escape(b['title'])}</b>", S["p"])] + [para(x, S["p"]) for x in b["lines"]]
            tb = Table([["", inner]], colWidths=[0.22 * cm, W - 0.22 * cm])
            tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), col), ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f6f6f6")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (1, 0), (1, 0), 5), ("BOTTOMPADDING", (1, 0), (1, 0), 3)]))
            story += [Spacer(1, 6), tb, Spacer(1, 2)]
        elif t == "table":
            small = b.get("small")
            cs = S["cells"] if small else S["cell"]
            head, rows = b["head"], b["rows"]
            plain = b.get("plain")
            data = [] if plain else [[Paragraph(f"<b>{escape(str(x))}</b>", cs) for x in head]]
            off = 0 if plain else 1
            for r in rows:
                data.append([Paragraph(escape(str(x)), cs) for x in r])
            rel = b.get("widths") or [1] * len(head)
            tot = float(sum(rel))
            tb = Table(data, colWidths=[W * x / tot for x in rel], repeatRows=0 if plain else 1)
            st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9c9c9")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
            if not plain:
                st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#deeaf6")))
            for (r, c), fill in (b.get("fills") or {}).items():
                st.append(("BACKGROUND", (c, r + off), (c, r + off), colors.HexColor(fill)))
                data[r + off][c] = Paragraph(f'<font color="{fg_for(fill)}">{escape(str(rows[r][c]))}</font>', cs)
            tb.setStyle(TableStyle(st))
            story += [tb, Spacer(1, 6)]
    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawCentredString(A4[0] / 2, 0.9 * cm, f"JalDrishti water-quality report - page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.7 * cm, rightMargin=1.7 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=rep.title).build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def to_html(rep):
    e = _html.escape
    css = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:auto;padding:12px;color:#222;line-height:1.45}"
           "h1{color:#1a5fb4;font-size:1.35em;margin-top:1.6em}h2{font-size:1.1em}h3{font-size:.98em;margin-bottom:2px}"
           "table{border-collapse:collapse;width:100%;margin:8px 0;font-size:.85em}td,th{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left}"
           "th{background:#deeaf6}.wrap{overflow-x:auto}img{max-width:100%;height:auto}.cap{font-size:.8em;color:#555;text-align:center}"
           ".card{border-radius:8px;padding:12px 16px;margin:10px 0}.card b{font-size:1.15em}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}"
           ".chip{border-radius:6px;padding:6px 10px;min-width:130px;flex:1}.chip span{display:block;font-size:.78em}.chip strong{font-size:1.05em}"
           ".call{border-left:7px solid;background:#f6f6f6;padding:6px 10px;margin:14px 0 4px}.small{font-size:.8em;color:#555}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(rep.title)}</title><style>{css}</style></head><body>"]
    for b in rep.doc:
        t = b["t"]
        if t == "title":
            out.append(f"<h1 style='margin-top:0;font-size:1.7em'>{e(b['text'])}</h1><p class='small'>{e(b.get('sub', ''))}</p>")
        elif t in ("h1", "h2", "h3"):
            out.append(f"<{t}>{e(b['text'])}</{t}>")
        elif t == "p":
            out.append(f"<p{' class=small' if b.get('small') else ''}>{e(b['text'])}</p>")
        elif t == "bullets":
            out.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in b["items"]) + "</ul>")
        elif t == "img" and b.get("bytes"):
            out.append(f"<p style='text-align:center'><img src='data:image/png;base64,{base64.b64encode(b['bytes']).decode()}'></p>" + (f"<p class='cap'>{e(b['caption'])}</p>" if b.get("caption") else ""))
        elif t == "card":
            out.append(f"<div class='card' style='background:{b['fill']};color:{b['fg']}'><b>{e(b['title'])}</b>" + "".join(f"<div>{e(x)}</div>" for x in b["lines"]) + "</div>")
        elif t == "chips":
            out.append("<div class='chips'>" + "".join(f"<div class='chip' style='background:{c['fill']};color:{c['fg']}'><span>{e(c['label'])}</span><strong>{e(c['value'])}</strong><span>{e(c['sub'])}</span></div>" for c in b["items"]) + "</div>")
        elif t == "callout":
            out.append(f"<div class='call' style='border-color:{PRI_FILL.get(b['level'], '#6c8ebf')}'><b>{e(b['title'])}</b>" + "".join(f"<div>{e(x)}</div>" for x in b["lines"]) + "</div>")
        elif t == "table":
            fills = b.get("fills") or {}
            hd = "" if b.get("plain") else "<tr>" + "".join(f"<th>{e(str(x))}</th>" for x in b["head"]) + "</tr>"
            body = ""
            for r, row in enumerate(b["rows"]):
                tds = ""
                for c, x in enumerate(row):
                    f = fills.get((r, c))
                    tds += f"<td style='background:{f};color:{fg_for(f)}'>{e(str(x))}</td>" if f else f"<td>{e(str(x))}</td>"
                body += f"<tr>{tds}</tr>"
            out.append(f"<div class='wrap'><table>{hd}{body}</table></div>")
    out.append("</body></html>")
    return "".join(out)


def to_zip(rep, pdf=None, html=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(rep.base + ".pdf", pdf if pdf is not None else to_pdf(rep))
        z.writestr(rep.base + ".html", html if html is not None else to_html(rep))
        for b in rep.doc:
            if b["t"] == "table" and b.get("csv") and b["head"] and b["head"][0] != "":
                z.writestr(f"tables/{b['csv']}.csv", pd.DataFrame(b["rows"], columns=b["head"]).to_csv(index=False))
        for name, df in rep.csvs.items():
            z.writestr(f"tables/{name}.csv", df.to_csv())
    return buf.getvalue()
