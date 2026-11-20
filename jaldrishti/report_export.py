import base64
import html
import io
import os
import zipfile
from xml.sax.saxutils import escape

COLORS = {"ok": ("#e6f4ea", "#1e7e34"), "info": ("#e8f1fb", "#1a5fb4"), "warn": ("#fff4e0", "#b45f06"), "bad": ("#fde8e8", "#b42318")}


def to_html(R, title="JalDrishti water-quality report"):
    out = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>%s</title><style>" % html.escape(title),
           "body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1b1b1b;line-height:1.45}",
           "h1{font-size:20px;border-bottom:2px solid #1a5fb4;padding-bottom:4px;margin-top:28px}h2{font-size:16px;margin-top:18px}",
           "table{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}th,td{border:1px solid #c8c8c8;padding:4px 6px;vertical-align:top;text-align:left}th{background:#e8f1fb}",
           ".c{padding:8px 10px;border-left:5px solid;margin:10px 0;border-radius:3px}img{max-width:100%}.cap{font-size:11px;color:#555;margin-bottom:10px}.meta td{border:none;padding:2px 8px 2px 0}",
           "@media print{body{margin:0}}</style></head><body>"]
    for b in R.doc:
        t = b["t"]
        if t == "title":
            out.append("<h1 style='font-size:26px;border:none'>%s</h1>" % html.escape(b["text"]))
        elif t == "meta":
            out.append("<table class='meta'>" + "".join("<tr><td><b>%s</b></td><td>%s</td></tr>" % (html.escape(k), html.escape(v)) for k, v in b["items"]) + "</table>")
        elif t == "h1":
            out.append("<h1>%s</h1>" % html.escape(b["text"]))
        elif t == "h2":
            out.append("<h2>%s</h2>" % html.escape(b["text"]))
        elif t == "p":
            out.append("<p>%s</p>" % html.escape(b["text"]))
        elif t == "bullets":
            out.append("<ul>" + "".join("<li>%s</li>" % html.escape(i) for i in b["items"]) + "</ul>")
        elif t == "table":
            w = b.get("widths") or [1] * len(b["columns"])
            tot = float(sum(w))
            cols = "".join("<col style='width:%.1f%%'>" % (100 * x / tot) for x in w)
            head = "".join("<th>%s</th>" % html.escape(c) for c in b["columns"])
            rows = "".join("<tr>" + "".join("<td>%s</td>" % html.escape(str(c)) for c in r) + "</tr>" for r in b["rows"])
            out.append("<table><colgroup>%s</colgroup><tr>%s</tr>%s</table>" % (cols, head, rows))
        elif t == "img":
            out.append("<img src='data:image/png;base64,%s'><div class='cap'>%s</div>" % (base64.b64encode(b["bytes"]).decode(), html.escape(b.get("caption", ""))))
        elif t == "callout":
            bg, fg = COLORS[b["level"]]
            out.append("<div class='c' style='background:%s;border-color:%s'>%s</div>" % (bg, fg, html.escape(b["text"])))
    out.append("</body></html>")
    return "\n".join(out)


def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        import matplotlib
        d = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        pdfmetrics.registerFont(TTFont("JDSans", os.path.join(d, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("JDSans-Bold", os.path.join(d, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("JDSans", normal="JDSans", bold="JDSans-Bold", italic="JDSans", boldItalic="JDSans-Bold")
        return "JDSans", "JDSans-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def to_pdf(R):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    base, bold = _fonts()
    st_p = ParagraphStyle("p", fontName=base, fontSize=9, leading=12, spaceAfter=4)
    st_title = ParagraphStyle("t", fontName=bold, fontSize=20, leading=24, spaceAfter=8, textColor=colors.HexColor("#1a5fb4"))
    st_h1 = ParagraphStyle("h1", fontName=bold, fontSize=13, leading=16, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#1a5fb4"), keepWithNext=1)
    st_h2 = ParagraphStyle("h2", fontName=bold, fontSize=10.5, leading=13, spaceBefore=8, spaceAfter=3, keepWithNext=1)
    st_cap = ParagraphStyle("cap", fontName=base, fontSize=7.5, leading=9, textColor=colors.HexColor("#555555"), spaceAfter=6)
    page_w = A4[0] - 3 * cm
    flow = []
    for b in R.doc:
        t = b["t"]
        if t == "title":
            flow.append(Paragraph(escape(b["text"]), st_title))
        elif t == "meta":
            rows = [[Paragraph("<b>%s</b>" % escape(k), st_p), Paragraph(escape(v), st_p)] for k, v in b["items"]]
            tb = Table(rows, colWidths=[3.2 * cm, page_w - 3.2 * cm])
            tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
            flow.append(tb)
        elif t == "h1":
            flow.append(Paragraph(escape(b["text"]), st_h1))
        elif t == "h2":
            flow.append(Paragraph(escape(b["text"]), st_h2))
        elif t == "p":
            flow.append(Paragraph(escape(b["text"]), st_p))
        elif t == "bullets":
            flow.append(ListFlowable([ListItem(Paragraph(escape(i), st_p), leftIndent=12) for i in b["items"]], bulletType="bullet", start="\u2022", leftIndent=12))
        elif t == "table":
            n = len(b["columns"])
            fs = 6.3 if n >= 10 else (7 if n >= 7 else 7.8)
            cs = ParagraphStyle("c", fontName=base, fontSize=fs, leading=fs + 2)
            hs = ParagraphStyle("hc", fontName=bold, fontSize=fs, leading=fs + 2)
            w = b.get("widths") or [1] * n
            tot = float(sum(w))
            cw = [page_w * x / tot for x in w]
            data = [[Paragraph(escape(c), hs) for c in b["columns"]]] + [[Paragraph(escape(str(c)), cs) for c in r] for r in b["rows"]]
            tb = Table(data, colWidths=cw, repeatRows=1)
            tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1fb")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8c8c8")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            flow.append(tb)
            flow.append(Spacer(1, 5))
        elif t == "img":
            iw, ih = ImageReader(io.BytesIO(b["bytes"])).getSize()
            w = page_w
            flow.append(KeepTogether([Image(io.BytesIO(b["bytes"]), width=w, height=w * ih / iw), Paragraph(escape(b.get("caption", "")), st_cap)]))
        elif t == "callout":
            bg, fg = COLORS[b["level"]]
            tb = Table([[Paragraph(escape(b["text"]), ParagraphStyle("co", parent=st_p, fontName=bold))]], colWidths=[page_w])
            tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)), ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(fg)),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            flow.append(Spacer(1, 3))
            flow.append(tb)
            flow.append(Spacer(1, 3))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(base, 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawCentredString(A4[0] / 2, 0.8 * cm, "JalDrishti water-quality report - page %d" % doc.page)
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                      title="JalDrishti water-quality report").build(flow, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def to_zip(R):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in R.tables.items():
            z.writestr(name + ".csv", df.to_csv(index=False).encode("utf-8-sig"))
    return buf.getvalue()
