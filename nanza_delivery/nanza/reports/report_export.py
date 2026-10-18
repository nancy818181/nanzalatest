from __future__ import annotations

import os
import tempfile
from datetime import datetime

import functools as _functools

# openpyxl and reportlab take a noticeable time to load. They are loaded the first time an export is
# made (not when the program opens), which makes opening Nanza Accounting faster.
_LIBRARIES_LOADED = False


def _load_libraries():
    global _LIBRARIES_LOADED, Workbook, Alignment, Font, PatternFill, get_column_letter, colors, A4, landscape
    global getSampleStyleSheet, mm, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    if _LIBRARIES_LOADED: return
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    _LIBRARIES_LOADED = True

NAVY = "071B2E"

# ---------------------------------------------------------------- Arabic in PDF
# Amiri (SIL Open Font License, assets/fonts/Amiri-OFL.txt) is used for any text that contains Arabic.
import re as _re
import sys as _sys
from pathlib import Path as _Path
from xml.sax.saxutils import escape as _escape

_ARABIC = _re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_FONTS = {"ready": None}


def _font_folder():
    import nanza_paths  # 2.9.117
    base = nanza_paths.ROOT
    for folder in (base / "assets" / "fonts", base / "assets" / "Fonts", base / "Assets" / "fonts"):
        if folder.is_dir(): return folder
    return base / "assets" / "fonts"


def arabic_fonts():
    """Register Amiri once; returns (regular, bold) or (None, None) when the font files are missing."""
    if _FONTS["ready"] is None:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            folder = _font_folder()
            pdfmetrics.registerFont(TTFont("Amiri", str(folder / "Amiri-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("Amiri-Bold", str(folder / "Amiri-Bold.ttf")))
            _FONTS["ready"] = ("Amiri", "Amiri-Bold")
        except Exception:
            _FONTS["ready"] = (None, None)
    return _FONTS["ready"]


def has_arabic(text):
    return bool(_ARABIC.search(str(text or "")))


def shape_arabic(text):
    """Join the Arabic letters and put the line in visual (right-to-left) order for the PDF."""
    text = str(text or "")
    if not has_arabic(text): return text
    try:
        import arabic_reshaper
        shaped = arabic_reshaper.reshape(text)
    except Exception:
        shaped = text
    try:
        from bidi.algorithm import get_display
        return get_display(shaped)
    except Exception:
        return " ".join(reversed(shaped.split(" ")))


def pdf_paragraph(text, style, bold=False):
    """A Paragraph that renders Arabic with the Arabic font, and anything else with the style's font."""
    regular, bold_font = arabic_fonts()
    if has_arabic(text) and regular:
        from reportlab.lib.styles import ParagraphStyle
        size = style.fontSize * 1.2
        arabic_style = ParagraphStyle(f"ar-{style.name}-{bold}", parent=style, fontName=bold_font if bold else regular, fontSize=size, leading=size * 1.4,
                                      alignment=style.alignment if style.alignment == 1 else 2 if not _re.search(r"[A-Za-z]{3}", str(text)) else style.alignment)  # 2.9.83: centred stays centred
        return Paragraph(_escape(shape_arabic(text)), arabic_style)
    text = _escape(str(text or ""))
    return Paragraph(f"<b>{text}</b>" if bold and text else text, style)

# ---------------------------------------------------------------- 2.9.119: reports in Arabic (right to left)
# When the program is in Arabic (arabic_ui switched on), the exports show their titles, headings, column titles and the
# fixed words of the rows in Arabic, the Excel sheets read from right to left and the PDF tables start from the right.
# In English nothing changes.
def arabic_reports():
    module = _sys.modules.get("arabic_ui")
    return bool(module is not None and module.active())


def _ar(text):
    if not isinstance(text, str) or not arabic_reports(): return text
    return _sys.modules["arabic_ui"].translate(text)


def _arabic_sections(title, meta, sections):
    """Title, meta lines and sections with their fixed texts in Arabic (amounts and names stay as they are)."""
    if any(section.get("report_language") in ("ar","en","fr") for section in sections): return title,meta,sections
    if not arabic_reports() or is_financial_pack(title): return title, meta, sections
    translated = []
    for section in sections:
        copy = dict(section)
        copy["heading"] = _ar(section.get("heading"))
        copy["headers"] = [_ar(h) for h in section.get("headers") or []]
        copy["rows"] = [[_ar(v) if isinstance(v, str) else v for v in row] for row in section.get("rows") or []]
        translated.append(copy)
    return _ar(title), [_ar(line) for line in meta or []], translated


def _report_rtl(sections):
    language=next((section.get("report_language") for section in sections if section.get("report_language") in ("ar","en","fr")),None)
    return language=="ar" if language else arabic_reports()


def _right_to_left(workbook, rtl=None):
    selected=arabic_reports() if rtl is None else bool(rtl)
    for sheet in workbook.worksheets: sheet.sheet_view.rightToLeft = selected


def export_excel(path, title, headers, rows):
    if arabic_reports():  # 2.9.119
        title = _ar(title); headers = [_ar(h) for h in headers]; rows = [[_ar(v) if isinstance(v, str) else v for v in row] for row in rows]
    wb = Workbook(); ws = wb.active; ws.title = _safe_sheet_title(title) if arabic_reports() else title[:31]
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    cell = ws.cell(1, 1, title); cell.font = Font(size=16, bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=NAVY); cell.alignment = Alignment(horizontal="center")
    ws.cell(2, 1, f"Generated: {datetime.now():%d-%m-%Y %H:%M}")
    for c, header in enumerate(headers, 1):
        h = ws.cell(4, c, header); h.font = Font(bold=True, color="FFFFFF")
        h.fill = PatternFill("solid", fgColor=NAVY); h.alignment = Alignment(horizontal="center")
    for r, values in enumerate(rows, 5):
        for c, value in enumerate(values, 1): ws.cell(r, c, value)
    for index, column in enumerate(ws.columns, 1):
        width = min(35, max(12, max(len(str(c.value or "")) for c in column) + 2))
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A5"; ws.auto_filter.ref = f"A4:{ws.cell(4, len(headers)).coordinate}"
    _right_to_left(wb); wb.save(path)

def export_pdf(path, title, headers, rows):
    if arabic_reports():  # 2.9.119: Arabic words, the first column on the right
        title = _ar(title); headers = [_ar(h) for h in headers][::-1]
        rows = [[_ar(v) if isinstance(v, str) else v for v in row][::-1] for row in rows]
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    from reportlab.lib.styles import ParagraphStyle
    story = [pdf_paragraph(title, styles["Title"], True), Paragraph(f"Generated: {datetime.now():%d-%m-%Y %H:%M}", styles["Normal"]), Spacer(1, 6*mm)]
    cell = ParagraphStyle("plain-cell", parent=styles["Normal"], fontSize=7, leading=8.5)
    head = ParagraphStyle("plain-head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    data = [[pdf_paragraph(h, head, True) if has_arabic(h) else h for h in headers]] + \
           [[pdf_paragraph(value, cell) if has_arabic(value) else ("" if value is None else str(value)) for value in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#071B2E")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 7),
        ("GRID", (0,0), (-1,-1), .25, colors.grey), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F3F6F8")]),
        ("ALIGN", (2,1), (-1,-1), "RIGHT"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,0), 7), ("TOPPADDING", (0,0), (-1,0), 7),
    ]))
    story.append(table); doc.build(story)

def print_rows(title, headers, rows):
    handle = tempfile.NamedTemporaryFile(prefix="NanzaAccounting_", suffix=".pdf", delete=False)
    handle.close(); export_pdf(handle.name, title, headers, rows)
    if os.name != "nt": raise RuntimeError("Printing is available in the Windows application")
    os.startfile(handle.name, "print")
    return handle.name

def export_invoice_pdf(path, invoice, items, logo_path=None, company=None):
    """Professional printable sales invoice (Lebanese format): navy header band with the
    company block + document title, status badge and a Date/Number/Currency/Due info card,
    a BILL TO party card, the line-item table (Item, Description, Quantity, Unit Price,
    Net before VAT), a totals panel (Total Before VAT, VAT 11%, Total, VAT LBP rate and
    VAT in LBP, Balance), the amount in words in English and Arabic, the Arabic fiscal-stamp
    note, and a signature row. Colours and content are data-driven from company settings."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from tafqeet import amount_in_words

    NAVY_C=colors.HexColor("#0B2239"); GOLD_C=colors.HexColor("#C9A24B"); GREY=colors.HexColor("#5F6B76")
    LINE=colors.HexColor("#D5DBE1"); SOFT=colors.HexColor("#F4F6F8"); ZEBRA=colors.HexColor("#EEF2F6")
    PAGE_W,PAGE_H=A4; ML=13*mm; MR=13*mm; CONTENT_W=PAGE_W-ML-MR
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=MR,leftMargin=ML,topMargin=13*mm,bottomMargin=16*mm)
    styles=getSampleStyleSheet(); story=[]; money=lambda v: f"{float(v or 0):,.2f}"
    company=company or {}
    arabic=arabic_reports()  # 2.9.119: the invoice in Arabic, laid out from the right
    def lab(text,style,bold=False):
        """A fixed label: as before in English; in Arabic, the Arabic words with the Arabic font."""
        if not arabic: return Paragraph(text,style)
        return pdf_paragraph(_ar(_re.sub(r"<[^>]+>","",text)),style,bold)
    flip=(lambda cells: cells[::-1]) if arabic else (lambda cells: cells)

    small=ParagraphStyle("inv-small",parent=styles["Normal"],fontSize=8,leading=10.5,textColor=colors.HexColor("#243544"))
    small_r=ParagraphStyle("inv-small-r",parent=small,alignment=TA_RIGHT)
    label_s=ParagraphStyle("inv-label",parent=small,textColor=GREY,fontName="Helvetica-Bold",fontSize=7.5)
    co_style=ParagraphStyle("inv-co",parent=styles["Normal"],fontName="Helvetica-Bold",fontSize=16,textColor=colors.white,leading=18)
    co_line=ParagraphStyle("inv-co-line",parent=small,textColor=colors.HexColor("#D7E0E8"),fontSize=7.5,leading=9.5)
    title_style=ParagraphStyle("inv-title",parent=styles["Normal"],fontName="Helvetica-Bold",fontSize=20,alignment=TA_RIGHT,textColor=colors.white,leading=22)
    cell=ParagraphStyle("inv-cell",parent=styles["Normal"],fontSize=8.5,leading=10.5,textColor=colors.HexColor("#243544"))
    party_name_s=ParagraphStyle("inv-pn",parent=styles["Normal"],fontName="Helvetica-Bold",fontSize=11,textColor=NAVY_C,leading=13)
    section_s=ParagraphStyle("inv-sec",parent=label_s,textColor=GOLD_C,fontSize=8)

    subtype=str(invoice.get("doc_subtype") or "invoice"); kind=str(invoice.get("kind") or "sale")
    title=_ar("RETURN NOTE" if invoice.get("is_return") else {"credit_note":"CREDIT NOTE","debit_note":"DEBIT NOTE"}.get(subtype,"SALES INVOICE" if kind=="sale" else "PURCHASE INVOICE"))

    subtotal=float(invoice.get("subtotal") or 0); vat=float(invoice.get("vat") or 0); total=float(invoice.get("total") or subtotal+vat)
    cur=invoice.get("currency") or ""; paid=float(invoice.get("amount_paid") or 0); balance=total-paid
    status=("PAID",colors.HexColor("#1E7A46")) if paid>=total and total>0 else (("PARTIAL",GOLD_C) if paid>0 else ("DUE",colors.HexColor("#A23B2C")))

    company_name=company.get("company_name") or "SABER FOR AUDIT"
    left=[pdf_paragraph(company_name,co_style,True)]
    for key in ("company_address","company_phone","company_email","company_website"):
        if company.get(key): left.append(pdf_paragraph(str(company[key]),co_line))
    if company.get("company_mof"): left.append(pdf_paragraph(f'{_ar("VAT No.")}: {company["company_mof"]}',co_line))
    _vat_reg=str(company.get("company_vat_registered") or "").strip().lower()
    if _vat_reg in ("yes","1","true"):
        _vd=str(company.get("company_vat_date") or "").strip()
        left.append(pdf_paragraph(f'{_ar("Registered in VAT since")} {_vd}' if _vd else _ar('Registered in VAT'),co_line))
    elif _vat_reg in ("no","0","false"):
        left.append(pdf_paragraph(_ar('Not registered in VAT'),co_line))
    logo_cell=None
    if logo_path and os.path.exists(str(logo_path)):
        try: logo_cell=Image(str(logo_path),width=20*mm,height=20*mm)
        except Exception: logo_cell=None
    if logo_cell:
        left_stack=Table([[logo_cell,left]],colWidths=[22*mm,None])
        left_stack.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),4),("TOPPADDING",(0,0),
                (-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    else:
        left_stack=left
    right=[pdf_paragraph(title,title_style,True)]
    if status[0]!="DUE":
        badge=Table([[lab(status[0],ParagraphStyle("badge",parent=styles["Normal"],fontName="Helvetica-Bold",fontSize=9,textColor=colors.white,alignment=TA_CENTER))]],colWidths=[24*mm])
        badge.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),status[1]),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
        right+=[Spacer(1,2*mm),Table([[badge]],colWidths=[24*mm],hAlign="RIGHT",style=[("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
                ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)])]
    band=Table([flip([left_stack,right])],colWidths=flip([CONTENT_W*0.60,CONTENT_W*0.40]))
    band.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("BACKGROUND",(0,0),(-1,-1),NAVY_C),("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9),("LINEBELOW",(0,0),(-1,-1),2.2,GOLD_C)]))
    story.extend([band,Spacer(1,5*mm)])

    info=[["Invoice Date",invoice.get("invoice_date") or ""],["Invoice No.",invoice.get("invoice_number") or ""],
          ["Currency",invoice.get("currency") or ""],["Due Date",invoice.get("due_date") or "-"]]
    info_table=Table([flip([pdf_paragraph(_ar(k),label_s),pdf_paragraph(str(v),small_r,True)]) for k,v in info],colWidths=flip([26*mm,None]))
    info_table.setStyle(TableStyle([("LINEBELOW",(0,0),(-1,-2),.4,LINE),("BACKGROUND",(0,0),(0,-1),SOFT),
        ("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("BOX",(0,0),(-1,-1),.5,LINE)]))

    party_lines=[pdf_paragraph(invoice.get("party_name") or "",party_name_s,True)]
    for lbl,val in (("Code",invoice.get("party_code")),("Address",invoice.get("party_address")),("MOF No.",invoice.get("party_mof"))):
        if not val: continue
        if has_arabic(val) or arabic: party_lines.append(pdf_paragraph(f"{_ar(lbl)}: {val}",small))
        else: party_lines.append(Paragraph(f"<b>{_escape(lbl)}:</b> {_escape(str(val))}",small))
    party_inner=Table([[pdf_paragraph(_ar("BILL TO"),section_s,True)]]+[[p] for p in party_lines],colWidths=[None])
    party_inner.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),2),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),("TOPPADDING",(0,0),(0,0),6),("BOTTOMPADDING",(0,-1),(-1,-1),6),
        ("BOX",(0,0),(-1,-1),.5,LINE),("LINEBEFORE",(0,0),(0,-1),2.2,GOLD_C),("BACKGROUND",(0,0),(-1,-1),colors.white)]))

    two_col=Table([flip([party_inner,info_table])],colWidths=flip([CONTENT_W*0.56,CONTENT_W*0.44]))
    two_col.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("RIGHTPADDING",(1,0),(1,0),0)]))
    story.extend([two_col,Spacer(1,5*mm)])

    head_s=ParagraphStyle("inv-head",parent=styles["Normal"],fontName="Helvetica-Bold",fontSize=8.5,textColor=colors.white,leading=10)
    head_r=ParagraphStyle("inv-head-r",parent=head_s,alignment=TA_RIGHT)
    headers=[pdf_paragraph(_ar("Item"),head_s,True),pdf_paragraph(_ar("Description"),head_s,True),pdf_paragraph(_ar("Quantity"),head_r,True),
             pdf_paragraph(_ar("Unit Price"),head_r,True),pdf_paragraph(_ar("Net before VAT"),head_r,True)]
    rows=[]; net_total=0.0
    for x in items:
        qty=float(x.get("quantity") or 0); price=float(x.get("unit_price") or 0); gross=float(x.get("gross_amount") or qty*price)
        percent=float(x.get("discount_percent") or 0); discount=float(x.get("discount_amount") or 0) or gross*percent/100
        net=gross-discount; net_total+=net; unit=x.get("unit") or ""
        qty_text=f"{qty:g}"+(f" {unit}" if unit else "")
        rows.append([x.get("item_code") or "",pdf_paragraph(x.get("description",""),cell),qty_text,money(price),money(net)])
    if not rows: rows=[["",pdf_paragraph(_ar("Invoice total"),cell),"1","",money(invoice.get("subtotal"))]]; net_total=float(invoice.get("subtotal") or 0)
    col_w=[22*mm,None,26*mm,26*mm,30*mm]
    used=sum(w for w in col_w if w); col_w=[w if w else (CONTENT_W-used) for w in col_w]
    table=Table([flip(headers)]+[flip(r) for r in rows],repeatRows=1,colWidths=flip(col_w))
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),NAVY_C),("LINEBELOW",(0,0),(-1,0),1.6,GOLD_C),
        ("FONTSIZE",(0,1),(-1,-1),8.5),("ALIGN",(2,1),(-1,-1),"RIGHT") if not arabic else ("ALIGN",(0,1),(-1,-1),"RIGHT"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,0),6),("BOTTOMPADDING",(0,0),(-1,0),6),("TOPPADDING",(0,1),(-1,-1),4.5),("BOTTOMPADDING",(0,1),(-1,-1),4.5),
        ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TEXTCOLOR",(0,1),(-1,-1),colors.HexColor("#243544")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,ZEBRA]),("LINEBELOW",(0,1),(-1,-1),.3,LINE),("BOX",(0,0),(-1,-1),.5,LINE)]))
    story.extend([table,Spacer(1,5*mm)])

    export=invoice.get("vat_treatment") in ("zero_rated","exempt")
    rate_text=invoice.get("vat_rate_text") or "11%"; vat_cur=invoice.get("vat_currency") or "LBP"  # 2.9.72: the company's VAT rate and currency
    vat_label=f"VAT {rate_text}" if not export else f"<strike>VAT {rate_text}</strike> Export - zero rated (Art. 19)" if invoice.get("vat_treatment")=="zero_rated" else f"<strike>VAT {rate_text}</strike> Exempt (Art. 16-17)"
    tl=ParagraphStyle("t-l",parent=styles["Normal"],fontSize=9,alignment=TA_LEFT,textColor=colors.HexColor("#243544"))
    tr=ParagraphStyle("t-r",parent=styles["Normal"],fontSize=9,alignment=TA_RIGHT,textColor=colors.HexColor("#243544"))
    tlw=ParagraphStyle("t-lw",parent=tl,fontName="Helvetica-Bold",fontSize=10.5,textColor=colors.white)
    trw=ParagraphStyle("t-rw",parent=tr,fontName="Helvetica-Bold",fontSize=10.5,textColor=colors.white)
    tlg=ParagraphStyle("t-lg",parent=tl,textColor=GREY,fontSize=8)
    trg=ParagraphStyle("t-rg",parent=tr,textColor=GREY,fontSize=8)
    gross_total=float(invoice.get("gross_total") or subtotal); inv_discount=float(invoice.get("discount") or 0)
    disc_pct=float(invoice.get("invoice_discount_percent") or 0)
    trows=[]
    if inv_discount>0.004 or disc_pct>0:
        trows.append([lab("Total",tl),Paragraph(f"{money(gross_total)} {cur}",tr)])
        disc_label=f"Discount {disc_pct:g}%" if disc_pct else "Discount"
        trows.append([lab(disc_label,tl),Paragraph(f"-{money(inv_discount)} {cur}",tr)])
    trows+=[[lab("Total HT (before VAT)",tl),Paragraph(f"{money(subtotal)} {cur}",tr)],
           [lab(vat_label,tl),Paragraph(f"{money(vat)} {cur}",tr)],
           [lab("TOTAL",tlw,True),Paragraph(f"{money(total)} {cur}",trw)]]
    total_row=len(trows)-1; grey_rows=[]
    if invoice.get("lbp_rate"):
        rate_value=float(invoice['lbp_rate']); rate_shown=f"{rate_value:,.0f}" if rate_value>=100 else f"{rate_value:,.4f}"
        trows.append([lab(f"VAT {vat_cur} Rate",tlg),Paragraph(rate_shown,trg)]); grey_rows.append(len(trows)-1)
    if invoice.get("vat_lbp") is not None:
        amount_shown=f"{float(invoice['vat_lbp']):,.0f}" if vat_cur=="LBP" else money(float(invoice['vat_lbp']))
        trows.append([lab(f"VAT {rate_text} ({vat_cur})",tlg),Paragraph(f"{amount_shown} {vat_cur}",trg)]); grey_rows.append(len(trows)-1)
    trows.append([lab("Balance Due",tlw,True),Paragraph(f"{money(balance)} {'DB' if balance>=0 else 'CR'}",trw)])
    balance_row=len(trows)-1
    totals_table=Table([flip(r) for r in trows],colWidths=flip([42*mm,38*mm]))
    ts=[("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
        ("LINEBELOW",(0,0),(-1,1),.4,LINE),("BACKGROUND",(0,total_row),(-1,total_row),NAVY_C),("BACKGROUND",(0,balance_row),(-1,balance_row),GOLD_C),
        ("TEXTCOLOR",(0,balance_row),(-1,balance_row),NAVY_C),("BOX",(0,0),(-1,-1),.5,LINE)]
    for gr in grey_rows: ts.append(("BACKGROUND",(0,gr),(-1,gr),SOFT))
    totals_table.setStyle(TableStyle(ts))

    words=amount_in_words(total,cur)
    words_style=ParagraphStyle("words",parent=small,leading=11)
    words_flow=[pdf_paragraph(_ar("AMOUNT IN WORDS"),section_s,True),Spacer(1,1.5*mm),
                Paragraph(f"<b>{words['en']}</b>",words_style),Spacer(1,1*mm),pdf_paragraph(words["ar"],words_style)]
    if arabic: words_flow=[words_flow[0],words_flow[1],words_flow[4],words_flow[3],words_flow[2]]  # the Arabic words first
    words_box=Table([[words_flow]],colWidths=[CONTENT_W-84*mm])
    words_box.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.5,LINE),("BACKGROUND",(0,0),(-1,-1),SOFT),("LINEBEFORE",(0,0),(0,-1),2.2,GOLD_C),
        ("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    summary=Table([flip([words_box,totals_table])],colWidths=flip([CONTENT_W-84*mm+2,84*mm-2]))
    summary.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(0,0),8),("RIGHTPADDING",(1,0),(1,0),0)]))
    story.extend([summary,Spacer(1,5*mm)])

    story.append(pdf_paragraph("رسم الطابع المالي يسدد لاحقاً بموجب التصريح (20 ع)",ParagraphStyle("stamp",parent=small,textColor=GREY,fontSize=7.5))
    )
    if invoice.get("notes"): story.append(pdf_paragraph(f'{_ar("Notes")}: {invoice["notes"]}',small))
    story.append(Spacer(1,12*mm))
    sign_s=ParagraphStyle("sign",parent=small,alignment=TA_CENTER,textColor=GREY,fontSize=8)
    signs=Table([flip([pdf_paragraph(_ar("Prepared by"),sign_s),pdf_paragraph(_ar("Approved by"),sign_s),pdf_paragraph(_ar("Received by"),sign_s)])],colWidths=[CONTENT_W/3]*3)
    signs.setStyle(TableStyle([("LINEABOVE",(0,0),(-1,0),.6,GREY),("TOPPADDING",(0,0),(-1,0),5),("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
    story.append(signs)

    def _decorate(canvas, document):
        canvas.saveState()
        canvas.setFillColor(GOLD_C); canvas.rect(0, PAGE_H-3*mm, PAGE_W, 3*mm, stroke=0, fill=1)
        canvas.setStrokeColor(GOLD_C); canvas.setLineWidth(1); canvas.line(ML, 11*mm, PAGE_W-MR, 11*mm)
        canvas.setFont("Helvetica", 7); canvas.setFillColor(GREY)
        if arabic and arabic_fonts()[0]:  # 2.9.119: the footer in Arabic too
            canvas.setFont(arabic_fonts()[0], 8)
            canvas.drawRightString(PAGE_W-MR, 7*mm, shape_arabic(company_name) if has_arabic(company_name) else company_name)
            canvas.drawCentredString(PAGE_W/2, 7*mm, shape_arabic(f"{_ar('Generated')} {datetime.now():%d-%m-%Y %H:%M}"))
            canvas.drawString(ML, 7*mm, shape_arabic(f"{_ar('Page')} {document.page}"))
        else:
            canvas.drawString(ML, 7*mm, company_name)
            canvas.drawCentredString(PAGE_W/2, 7*mm, f"Generated {datetime.now():%d-%m-%Y %H:%M}")
            canvas.drawRightString(PAGE_W-MR, 7*mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)


# ---------------------------------------------------------------- multi-section official reports
def _plain(value):
    """Numbers stay numeric for Excel; Decimals become floats."""
    from decimal import Decimal
    if isinstance(value, Decimal):
        # Excel stores only 15 significant digits; preserve larger exact amounts as decimal text.
        significant=len(value.normalize().as_tuple().digits)
        return format(value,'f') if significant>15 else float(value)
    return value


def _formatted(value):
    from decimal import Decimal
    if value is None: return ""
    if isinstance(value, bool): return str(value)
    if isinstance(value, int): return f"{value:,}"
    if isinstance(value, Decimal):
        return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    if isinstance(value, float):
        number = value
        return f"{number:,.0f}" if abs(number - round(number)) < 1e-9 else f"{number:,.2f}"
    return str(value)


def _is_blank_or_zero(value):
    from decimal import Decimal
    if value is None or value == "": return True
    if isinstance(value, bool): return False
    if isinstance(value, (int, float, Decimal)): return float(value) == 0
    text = str(value).strip().replace(",", "")
    try: return float(text) == 0
    except ValueError: return text in ("", "-")


def tidy_sections(sections):
    """2.9.45 report check-up: easier to read without changing any figure.

    Only sections marked "compact" (the payroll worksheets) leave out the columns that are empty or zero on every
    line (the first two columns always stay). Every other report - financial statements, ledgers, trial balance,
    VAT, inventory - keeps all its columns exactly as before (2.9.49, owner request)."""
    tidy = []
    for section in sections or []:
        headers = list(section.get("headers") or []); rows = [list(r) for r in section.get("rows") or []]
        if not section.get("compact") or section.get("narrative") or section.get("fixed") or len(headers) <= 3 or not rows:
            tidy.append(section); continue
        keep = [i for i in range(len(headers)) if i < 2 or not all(_is_blank_or_zero(r[i] if i < len(r) else None) for r in rows)]
        if len(keep) == len(headers): tidy.append(section); continue
        dropped = [str(headers[i]).split(" | ")[0] for i in range(len(headers)) if i not in keep]
        tidy.append({**section, "headers": [headers[i] for i in keep], "rows": [[r[i] if i < len(r) else "" for i in keep] for r in rows],
                     "hidden_columns": dropped})
    return tidy


def _accounting_text(value):
    from decimal import Decimal
    if isinstance(value, (int,float,Decimal)) and not isinstance(value,bool):
        if value == 0:return "-"
        amount=f"{abs(value):,.2f}"
        return f"({amount})" if value<0 else amount
    return _cell_text(value)


def _looks_numeric(text):
    text = str(text or "").strip()
    if len(text) > 2 and text[0] == "(" and text[-1] == ")": text = text[1:-1]
    return text == "-" or (bool(text) and text.replace(",", "").replace(".", "").lstrip("-").rstrip("%").isdigit())


def _cell_text(value):
    """PDF / screen text: zero amounts show as a dash."""
    from decimal import Decimal
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and float(value) == 0: return "-"
    return _formatted(value)


def _safe_sheet_title(title):
    cleaned = "".join("-" if ch in '[]:*?/\\' else ch for ch in str(title))
    return cleaned[:31] or "Report"


def _financial_sheet_name(heading, kind=None):
    if kind:  # 2.9.109: tagged by financial_statements.build (any language)
        return {"audit": "Auditor's Report", "position": "Financial Position", "profit": "Profit or Loss", "equity": "Changes in Equity",
                "cash": "Cash Flows", "checks": "Review Points", "review": "Review Points"}.get(kind, "Notes")
    heading = str(heading or "")
    for prefix, name in (("INDEPENDENT AUDITOR", "Auditor's Report"), ("STATEMENT OF FINANCIAL POSITION", "Financial Position"),
                         ("STATEMENT OF PROFIT", "Profit or Loss"), ("STATEMENT OF CHANGES", "Changes in Equity"),
                         ("STATEMENT OF CASH", "Cash Flows"), ("PREPARER REVIEW", "Review Points")):
        if heading.startswith(prefix): return name
    return "Notes"


def export_financial_excel(path, title, meta, sections):
    """2.9.83: the financial statements pack as a print-ready workbook - a centred cover sheet, one sheet per statement,
    the notes together, A4 portrait fitted to the page width, accounting number format (negatives in brackets)."""
    from openpyxl.styles import Border, Side
    from openpyxl.worksheet.properties import PageSetupProperties
    meta = list(meta or []); company = meta[0] if meta else ""
    period = (meta[1] if len(meta) > 1 else "")
    for suffix in (" - with comparative figures", " - avec chiffres comparatifs", " - مع أرقام المقارنة"): period = period.replace(suffix, "")  # 2.9.109
    currency = next((m for m in meta if str(m).startswith(("Presentation currency", "Monnaie de présentation", "عملة العرض"))), "")
    auditor = next((str(m).split(":", 1)[1].strip() for m in meta if str(m).startswith(("Auditor: ", "Auditeur : ", "مدقق الحسابات:"))), "")
    arabic = str(title).startswith("البيانات المالية")
    import financial_statements_i18n as i18n
    words = i18n.COVER[i18n.language_of(title)]; sheet_titles = {**{v: v for v in words["sheets"].values()}, **{
        "Auditor's Report": words["sheets"]["audit"], "Financial Position": words["sheets"]["position"], "Profit or Loss": words["sheets"]["profit"],
        "Changes in Equity": words["sheets"]["equity"], "Cash Flows": words["sheets"]["cash"], "Notes": words["sheets"]["notes"],
        "Review Points": words["sheets"]["review"]}}
    navy = PatternFill("solid", fgColor=NAVY); thin = Side(style="thin", color="071B2E"); double = Side(style="double", color="071B2E")
    accounting = '#,##0;(#,##0);"-"'; accounting2 = '#,##0.00;(#,##0.00);"-"'
    wb = Workbook(); sheets = {}

    def setup(ws, widths):
        ws.sheet_view.showGridLines = False
        if arabic: ws.sheet_view.rightToLeft = True  # 2.9.109: the Arabic pack reads right to left
        ws.page_setup.orientation = "portrait"; ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True); ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
        ws.print_options.horizontalCentered = True
        ws.page_margins.left = ws.page_margins.right = 0.5; ws.page_margins.top = ws.page_margins.bottom = 0.6
        ws.oddFooter.left.text = company; ws.oddFooter.right.text = "&P / &N" if arabic else "Page &P sur &N" if words is i18n.COVER["fr"] else "Page &P of &N"
        for column, width in enumerate(widths, 1): ws.column_dimensions[get_column_letter(column)].width = width

    def centred(ws, row, text, width, size=11, bold=False, colour="071B2E", height=None):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        cell = ws.cell(row, 1, text); cell.font = Font(size=size, bold=bold, color=colour)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if height: ws.row_dimensions[row].height = height

    # ---- cover
    cover = wb.active; cover.title = words["sheets"]["cover"]; setup(cover, [14, 30, 30, 14])
    row = 8; centred(cover, row, company.upper(), 4, 20, True, height=34); row += 2
    centred(cover, row, words["title"], 4, 15, True, height=22); row += 1
    if any(s.get("kind") == "audit" for s in sections): centred(cover, row, words["sub"], 4, 12, True, height=20)  # 2.9.121: management accounts: no auditor
    row += 2
    if period: centred(cover, row, period, 4, 12); row += 1
    if currency: centred(cover, row, currency, 4, 10, colour="5F6B76"); row += 1
    if auditor: row += 4; centred(cover, row, auditor, 4, 11, True)
    from openpyxl.worksheet.pagebreak import Break
    cover.row_breaks.append(Break(id=row + 1)); row += 8  # 2.9.100: the contents on a printed page of its own
    centred(cover, row, company.upper(), 4, 14, True, height=24); row += 2
    centred(cover, row, words["contents"], 4, 11, True); cover.cell(row, 2).border = Border(top=thin); cover.cell(row, 3).border = Border(top=thin)
    for item in _contents(sections):
        row += 1; cover.cell(row, 2, item).font = Font(size=10)
        cover.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        cover.cell(row, 2).alignment = Alignment(horizontal="center")
    cover.cell(row, 2).border = Border(bottom=thin); cover.cell(row, 3).border = Border(bottom=thin)

    for section in tidy_sections(sections):
        name = _financial_sheet_name(section.get("heading"), section.get("kind"))
        headers = list(section.get("headers") or []); narrative = bool(section.get("narrative"))
        if name not in sheets:
            ws = wb.create_sheet(sheet_titles.get(name, name))
            if narrative or name == "Notes": widths = [95] if narrative else [50] + [18] * max(1, len(headers) - 1)
            elif headers[:1] == [""] and len(headers) > 1 and headers[1] in NOTES_HEADERS: widths = [52, 8] + [18] * (len(headers) - 2)
            else: widths = [44] + [17] * (len(headers) - 1)
            if name == "Notes":
                note_columns=max((len(part.get('headers') or []) for part in sections
                                  if part.get('kind') in ('notes','notes_start') and not part.get('narrative')),default=2)
                widths=[60]+[18]*max(1,note_columns-1)
            setup(ws, widths); sheets[name] = [ws, 1, len(widths)]
            centred(ws, 1, company.upper(), sheets[name][2], 13, True, height=22)
            sheets[name][1] = 3
        ws, row, width = sheets[name]
        if section.get("center"): centred(ws, row, section["heading"], width, 12, True, height=32)
        else: ws.cell(row, 1, section["heading"]).font = Font(size=11, bold=True, color=NAVY)
        row += 1
        if narrative:
            for values in section.get("rows") or []:
                for paragraph in " — ".join(str(v) for v in values).splitlines() or [""]:
                    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
                    cell = ws.cell(row, 1, paragraph)
                    bold = bool(section.get("center")) and _is_subheading(paragraph)
                    cell.font = Font(bold=bold, size=10, color="071B2E" if bold else "000000")
                    cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal="justify" if not bold else "left")
                    chars = int(sum(ws.column_dimensions[get_column_letter(c)].width for c in range(1, width + 1)) * 1.1)
                    ws.row_dimensions[row].height = max(15, 14 * (len(paragraph) // max(40, chars) + 1))
                    row += 1
            sheets[name][1] = row + 1; continue
        for column, header in enumerate(headers, 1):
            h = ws.cell(row, column, header); h.font = Font(bold=True, color="FFFFFF", size=10); h.fill = navy
            h.alignment = Alignment(horizontal="center" if column > 1 else "left", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 28; row += 1
        totals = set(section.get("total_rows") or [])
        major = set(section.get("major_total_rows") or [])
        header_row=row-1
        if ws.freeze_panes is None:ws.freeze_panes=f"B{row}"
        if not ws.print_title_rows:
            ws.print_title_rows=f"1:{header_row}" if name not in ("Notes","Review Points") else "1:1"
        for index, values in enumerate(section.get("rows") or []):
            caption = str(values[0]) if values else ""
            is_heading = len(values) > 1 and all(v in ("", None) for v in values[1:]) and caption
            grand = index in major
            for column, value in enumerate(values, 1):
                c = ws.cell(row, column, _plain(value))
                if (isinstance(c.value, (int, float)) and not isinstance(c.value, bool)) or _looks_numeric(c.value):
                    c.number_format = accounting2
                    c.alignment = Alignment(horizontal="right")
                    if index in totals: c.border = Border(top=thin, bottom=double if grand else None)
                else:
                    c.alignment = Alignment(vertical="top", wrap_text=True, horizontal="center" if column == 2 and headers[1:2] and headers[1] in NOTES_HEADERS[1:] else None)
                colour="9C2F24" if index in section.get('warning_rows',[]) else NAVY if is_heading else "000000"
                c.font = Font(size=10, bold=bool(index in totals or is_heading), color=colour)
            if is_heading:ws.row_dimensions[row].height=22
            else:
                label_width=ws.column_dimensions['A'].width
                lines=max(1,(len(caption)+max(1,int(label_width))-1)//max(1,int(label_width)))
                ws.row_dimensions[row].height=max(20,14*lines)
            row += 1
        sheets[name][1] = row + 1
    for ws, last_row, width in sheets.values():
        if not ws.print_title_rows:ws.print_title_rows="1:1"
        ws.print_area=f"A1:{get_column_letter(width)}{last_row-1}"
    wb.save(path)


FINANCIAL_TITLES = ("Financial Statements,", "États financiers,", "البيانات المالية والإيضاحات",
                    "Financial Statements and Notes", "États financiers et notes")  # 2.9.121: management accounts (no auditor's report)  # 2.9.109: the pack in English, French, Arabic


def is_financial_pack(title):
    return str(title or "").startswith(FINANCIAL_TITLES)


def export_sections_excel(path, title, meta, sections):
    if is_financial_pack(title):  # 2.9.83: the audit report pack has its own print-ready layout
        return export_financial_excel(path, title, meta, sections)
    sections = tidy_sections(sections)
    title, meta, sections = _arabic_sections(title, meta, sections)  # 2.9.119
    wb = Workbook(); ws = wb.active; ws.title = _safe_sheet_title(title)
    width = max([len(section["headers"]) for section in sections] + [2])
    navy = PatternFill("solid", fgColor=NAVY); total_fill = PatternFill("solid", fgColor="E8EDF2")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    cell = ws.cell(1, 1, title); cell.font = Font(size=15, bold=True, color="FFFFFF"); cell.fill = navy
    cell.alignment = Alignment(horizontal="center", vertical="center"); ws.row_dimensions[1].height = 26
    row = 2
    for line in list(meta or []) + [f"Generated: {datetime.now():%d-%m-%Y %H:%M}"]:
        ws.cell(row, 1, line).font = Font(italic=True, color="44546A"); row += 1
    widths = {}
    for section in sections:
        row += 1
        ws.cell(row, 1, section["heading"]).font = Font(size=12, bold=True, color=NAVY); row += 1
        if section.get("narrative"):
            import textwrap
            for values in section["rows"]:
                text = " — ".join(str(v) for v in values)
                for paragraph in text.splitlines() or [""]:
                    for chunk in textwrap.wrap(paragraph, 800) or [""]:
                        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
                        cell = ws.cell(row, 1, chunk)
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        ws.row_dimensions[row].height = max(30, 15 * ((len(chunk) // 100) + 1))
                        row += 1
            continue
        for column, header in enumerate(section["headers"], 1):
            h = ws.cell(row, column, header); h.font = Font(bold=True, color="FFFFFF"); h.fill = navy
            h.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            widths[column] = max(widths.get(column, 10), min(22, len(str(header)) + 2))
        ws.row_dimensions[row].height = 30; row += 1
        totals = set(section.get("total_rows") or [])
        for index, values in enumerate(section["rows"]):
            if len(values) > len(section["headers"]):
                raise ValueError(f"Section {section['heading']!r} has more values than headers")
            height = 15
            for column, value in enumerate(values, 1):
                c = ws.cell(row, column, _plain(value))
                if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    c.number_format = "#,##0.00;-#,##0.00;\"-\"" if isinstance(c.value, float) and abs(c.value - round(c.value)) > 1e-9 else "#,##0;-#,##0;\"-\""
                    c.alignment = Alignment(horizontal="right")
                else:
                    c.alignment = Alignment(vertical="top", wrap_text=True)
                    # Excel otherwise hides the rest of long notes behind the next column.
                    lines = str(c.value or "").splitlines() or [""]
                    cell_width = min(65, max(widths.get(column, 10), len(_formatted(value)) + 2))
                    height = max(height, 15 * sum(max(1, (len(line) + int(cell_width) - 1) // int(cell_width)) for line in lines))
                if index in totals: c.font = Font(bold=True); c.fill = total_fill
                widths[column] = max(widths.get(column, 10), min(65, len(_formatted(value)) + 2))
            ws.row_dimensions[row].height = min(400, height)
            row += 1
        if section.get("chart"):
            row = _excel_chart(ws, row, section["chart"])
    for column, value in widths.items(): ws.column_dimensions[get_column_letter(column)].width = value
    ws.sheet_view.showGridLines = True
    _right_to_left(wb,_report_rtl(sections)); wb.save(path)


def _excel_chart(ws, row, spec):
    """Chart data under the table and a native Excel 3D column chart next to it. Returns the next free row."""
    from openpyxl.chart import BarChart3D, Reference
    series = list(spec.get("series") or []); categories = list(spec.get("categories") or [])
    if not series or not categories: return row
    row += 1; first = row
    ws.cell(row, 1, "Chart data").font = Font(italic=True, color="44546A")
    for column, name in enumerate(categories, 2): ws.cell(row, column, str(name)).font = Font(bold=True)
    for index, name in enumerate(series):
        ws.cell(row + 1 + index, 1, str(name))
        values = list(spec.get("values")[index]) if index < len(spec.get("values") or []) else []
        for column in range(len(categories)):
            value = values[column] if column < len(values) else 0
            ws.cell(row + 1 + index, column + 2, float(value or 0)).number_format = "#,##0"
    last = row + len(series)
    chart = BarChart3D(); chart.title = spec.get("title") or None; chart.height = 9; chart.width = 22
    chart.add_data(Reference(ws, min_col=1, max_col=len(categories) + 1, min_row=first + 1, max_row=last), from_rows=True, titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=2, max_col=len(categories) + 1, min_row=first, max_row=first))
    ws.add_chart(chart, f"A{last + 2}")
    return last + 2 + 19


def _is_subheading(text):
    text = str(text or "").strip()
    return bool(text) and len(text) <= 110 and text == text.upper() and any(ch.isalpha() for ch in text)


def _contents(sections):
    """The statements and notes of the pack, for the cover page."""
    return [label for label, _index in _contents_entries(sections)]


NOTES_HEADERS = ("", "Notes", "إيضاح")  # 2.9.109: the "Notes" column of the statements in English / French and Arabic


def _contents_entries(sections):
    """2.9.97: (label, section index) of each item of the contents - the page of that section is printed next to it."""
    items = []
    if any(section.get("kind") for section in sections):  # 2.9.109: tagged sections, labels in the language of the pack
        import financial_statements_i18n as i18n
        heading = next((str(s.get("heading") or "") for s in sections if s.get("kind") == "position"), "")
        language = "ar" if any("\u0600" <= ch <= "\u06FF" for ch in heading) else "fr" if heading.startswith("ÉTAT") else "en"
        words = i18n.COVER[language]
        for index, section in enumerate(sections):
            kind = section.get("kind")
            if kind in ("audit", "position", "profit", "equity", "cash"): items.append((words[kind], index))
            elif kind == "notes_start": items.append((words["notes"], index)); break
        return items
    for index, section in enumerate(sections):
        heading = str(section.get("heading") or "")
        if heading.startswith("PREPARER REVIEW"): continue
        if heading.startswith("INDEPENDENT AUDITOR"): items.append(("Independent auditor's report", index))
        elif heading.startswith("STATEMENT OF"): items.append((heading.split(" as at ")[0].split(" for the ")[0].split(" (")[0].title().replace(" Or ",
                " or ").replace(" And ", " and ").replace(" Of ", " of ").replace(" In ", " in "), index))
        elif heading.startswith("NOTES TO THE FINANCIAL STATEMENTS"):
            items.append(("Notes to the financial statements", index)); break
    return items


def _financial_cover(doc, styles, regular, bold_font, meta, sections, pages=None):
    """2.9.83: front page of the financial statements, centred on the page: company, title, period, currency, contents, auditor."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak
    meta = list(meta or [])
    company = meta[0] if meta else ""; period = meta[1] if len(meta) > 1 else ""
    currency = next((m for m in meta if str(m).startswith(("Presentation currency", "Monnaie de présentation", "عملة العرض"))), "")
    auditor = next((str(m).split(":", 1)[1].strip() for m in meta if str(m).startswith(("Auditor: ", "Auditeur : ", "مدقق الحسابات:"))), "")
    import financial_statements_i18n as i18n
    heading = next((str(s.get("heading") or "") for s in sections if s.get("kind") == "position"), "")
    words = i18n.COVER["ar" if any("\u0600" <= ch <= "\u06FF" for ch in heading) else "fr" if heading.startswith("ÉTAT") else "en"]
    centre = lambda name, size, font, colour="#071B2E", space=0: ParagraphStyle(name, parent=styles["Normal"], alignment=1, fontName=font, fontSize=size,
                                                                                 leading=size * 1.3, textColor=colors.HexColor(colour), spaceAfter=space)
    story = [Spacer(1, doc.height * 0.22),
             pdf_paragraph(company.upper(), centre("cover-company", 22, bold_font, space=6*mm), True),
             pdf_paragraph(words["title"], centre("cover-title", 16, bold_font, space=2*mm), True)]
    if any(s.get("kind") == "audit" for s in sections): story.append(pdf_paragraph(words["sub"], centre("cover-sub", 12, bold_font, space=8*mm), True))  # 2.9.121
    else: story.append(Spacer(1, 8*mm))
    for suffix in (" - with comparative figures", " - avec chiffres comparatifs", " - مع أرقام المقارنة"): period = period.replace(suffix, "")
    if period: story.append(pdf_paragraph(period, centre("cover-period", 12, regular, space=2*mm)))
    if currency: story.append(pdf_paragraph(currency, centre("cover-currency", 10, regular, "#5F6B76", space=14*mm)))
    entries = _contents_entries(sections)
    if entries:
        # 2.9.97: the contents with the page of each part (pages found by a first pass of the PDF; "-" until then)
        left = ParagraphStyle("cover-item-left", parent=styles["Normal"], fontName=regular, fontSize=10, leading=13)
        right = ParagraphStyle("cover-item-right", parent=left, alignment=2)
        rows = [[pdf_paragraph(words["contents"], centre("cover-contents", 10, bold_font), True),
                 pdf_paragraph(words["page"], ParagraphStyle("cover-page-head", parent=right, fontName=bold_font), True)]]
        for label, index in entries:
            rows.append([pdf_paragraph(label, left), pdf_paragraph(str((pages or {}).get(index, "-")), right)])
        table = Table(rows, colWidths=[doc.width * 0.52, doc.width * 0.12], hAlign="CENTER")
        table.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), .6, colors.HexColor("#071B2E")), ("LINEBELOW", (0, 0), (-1, 0), .3, colors.grey),
                                   ("LINEBELOW", (0, -1), (-1, -1), .6, colors.HexColor("#071B2E")), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                   ("LINEBELOW", (0, 1), (-1, -2), .2, colors.HexColor("#D5DDE5"))]))
        contents = [Spacer(1, doc.height * 0.12), pdf_paragraph(company.upper(), centre("contents-company", 14, bold_font, space=8*mm), True), table]
    else:
        contents = []
    if auditor: story += [Spacer(1, 18*mm), pdf_paragraph(auditor, centre("cover-auditor", 11, bold_font), True)]
    story.append(PageBreak())
    if contents: story += contents + [PageBreak()]  # 2.9.100: the contents on a page of its own, after the front page
    return story


def export_sections_pdf(path, title, meta, sections):
    """2.9.97: the financial statements are built twice - the first pass finds the page of each part for the contents."""
    sections = tidy_sections(sections)
    title, meta, sections = _arabic_sections(title, meta, sections)  # 2.9.119
    if is_financial_pack(title):
        import io
        pages = {}
        _build_sections_pdf(io.BytesIO(), title, meta, sections, pages, {})
        return _build_sections_pdf(path, title, meta, sections, {}, pages)
    return _build_sections_pdf(path, title, meta, sections, {}, {})


def _page_marker(store, key):
    """A zero-size flowable that writes down the page it lands on."""
    from reportlab.platypus import Flowable
    class Marker(Flowable):
        def wrap(self, *_args): return 0, 0
        def draw(self): store[key] = self.canv.getPageNumber()
    return Marker()


def _logo_flowable(encoded, max_width, max_height):
    import base64, io
    from reportlab.lib.utils import ImageReader
    try:
        data = base64.b64decode(encoded); reader = ImageReader(io.BytesIO(data)); width, height = reader.getSize()
        scale = min(max_width / width, max_height / height)
        logo = Image(io.BytesIO(data), width=width * scale, height=height * scale); logo.hAlign = "CENTER"
        return logo
    except Exception:
        return None


def _build_sections_pdf(path, title, meta, sections, found_pages, contents_pages):
    from reportlab.lib.styles import ParagraphStyle
    financial = is_financial_pack(title)
    page = A4 if financial else landscape(A4)
    doc = SimpleDocTemplate(path if hasattr(path, "write") else str(path), pagesize=page,  # 2.9.98: the first pass writes to memory, not to a file named "<_io.BytesIO ...>"
                             rightMargin=8*mm, leftMargin=8*mm, topMargin=10*mm, bottomMargin=12*mm, title=title)
    styles = getSampleStyleSheet()
    regular,bold_font=arabic_fonts() if financial else (None,None)
    regular=regular or "Helvetica";bold_font=bold_font or "Helvetica-Bold"
    import financial_statements_i18n as i18n
    report_rtl=(i18n.language_of(title)=="ar") if financial else _report_rtl(sections)
    if financial:
        for style in styles.byName.values(): style.fontName = regular
        for key in ("Title", "Heading1", "Heading2", "Heading3"): styles[key].fontName = bold_font
        styles["Normal"].fontSize=11; styles["Normal"].leading=15
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontName=bold_font,
                                  fontSize=10 if financial else 8, leading=13 if financial else 10,
                                  textColor=colors.HexColor("#071B2E") if financial else colors.white, alignment=1)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=10 if financial else 8, leading=13 if financial else 10)
    number_style = ParagraphStyle("cell-number", parent=cell_style, alignment=2)  # amounts line up on the right
    # 2.9.83: totals and headings with the bold font itself (<b> has no effect on the Arabic-capable fonts)
    cell_bold = ParagraphStyle("cell-bold", parent=cell_style, fontName=bold_font); number_bold = ParagraphStyle("cell-number-bold", parent=number_style, fontName=bold_font)
    if financial:
        story = _financial_cover(doc, styles, regular, bold_font, meta, sections, contents_pages)  # 2.9.83: centred front page
    else:
        story = [pdf_paragraph(title, styles["Title"], True)]
        for line in list(meta or []) + [f"{_ar('Generated')}: {datetime.now():%d-%m-%Y %H:%M}"]: story.append(pdf_paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 4*mm))
    centred = ParagraphStyle("centred-heading", parent=styles["Heading3"], alignment=1)
    subheading = ParagraphStyle("sub-heading", parent=styles["Normal"], fontName=bold_font, spaceBefore=4)
    # ReportLab frames add 6pt padding on each side of doc.width.
    available = doc.width - 12
    for section_index, section in enumerate(sections):
        after_cover = financial and story and type(story[-1]).__name__ == "PageBreak"
        if not after_cover and ((financial and (section["heading"].startswith(("Statement of",
                "Notes: account")) or section["heading"].endswith("DRAFT - Addressee"))) or (section.get("page_break") and story)):
            from reportlab.platypus import PageBreak
            story.append(PageBreak())
        story.append(_page_marker(found_pages, section_index))  # 2.9.97: the page of this part, for the contents
        if financial and section.get("logo_b64"):  # 2.9.97: the auditor's logo on top of the Independent Auditor's Report
            logo = _logo_flowable(section["logo_b64"], doc.width * 0.35, 22*mm)
            if logo: story += [logo, Spacer(1, 3*mm)]
        story.append(pdf_paragraph(section["heading"], centred if financial and section.get("center") else styles["Heading3"], True))
        if section.get("narrative"):
            start = len(story)
            for values in section["rows"]:
                for paragraph in " — ".join(str(v) for v in values).splitlines():
                    # 2.9.83: the sub-titles of the auditor's report (OPINION, BASIS FOR OPINION ...) in bold
                    heading_line = financial and section.get("center") and _is_subheading(paragraph)
                    story.append(pdf_paragraph(paragraph, subheading if heading_line else styles["Normal"], bool(heading_line)))
                    story.append(Spacer(1, 2*mm))
            keep = int(section.get("keep_last") or 0)
            if financial and keep and len(story) - start > 2 * (keep + 1):
                # 2.9.83: the signature block stays on the page of the last paragraph of the report
                from reportlab.platypus import KeepTogether
                block = story[-2 * (keep + 1):]; del story[-2 * (keep + 1):]; story.append(KeepTogether(block))
            story.append(Spacer(1, 3*mm))
            continue
        if section.get("chart"):  # 2.9.50: 3D bar chart drawn above the table
            import chart3d
            from reportlab.platypus import KeepTogether
            heading = story.pop()  # the heading stays on the same page as its chart
            story += [KeepTogether([heading, chart3d.reportlab_drawing(chart3d.chart_from_spec(section["chart"]), available)]), Spacer(1, 3*mm)]
        headers = section["headers"]; count = len(headers)
        if not count:
            continue
        text_of = _accounting_text if financial else _cell_text  # 2.9.83: (1,234) for negative amounts in the financial statements
        body = [[text_of(value) for value in list(values) + [""] * (count - len(values))] for values in section["rows"]]
        if any(len(row) > count for row in body):
            raise ValueError(f"Section {section['heading']!r} has more values than headers")
        def preferred_width(column):
            header = max((len(part.strip()) for part in str(headers[column]).split(" | ")), default=0)
            longest = max([header] + [len(row[column]) for row in body])
            numeric = all(not row[column] or row[column] == "-" or row[column].replace(",", "").replace(".", "").lstrip("-").isdigit() for row in body)
            return min(65*mm, max((20 if numeric else 29)*mm, longest * (4.5 if numeric else 4)))
        widths = [preferred_width(i) for i in range(count)]
        if financial and count == 5:
            weights = [13, 24, 29, 20, 23] if headers[0] == "Account" else [35, 16, 23, 16, 16]
            widths = [weight * available / sum(weights) for weight in weights]
        if financial and section.get("kind") in ("notes","notes_start") and count >= 2:
            # 2.9.83: the account tables of the notes use the whole page width like the statements
            first = available * (0.55 if count <= 3 else 0.42); widths = [first] + [(available - first) / (count - 1)] * (count - 1)
        if financial and count >= 3 and section.get("kind") in ("position","profit","cash"):
            # 2.9.69: statements - wide caption column, narrow Notes column, equal amount columns
            amounts = count - 2; first = available * (0.55 if amounts <= 2 else 0.42); notes = available * 0.08
            widths = [first, notes] + [(available - first - notes) / amounts] * amounts
        weights=section.get('column_weights')
        if weights and len(weights)==count and all(weight>0 for weight in weights):
            widths=[available*weight/sum(weights) for weight in weights]
        # Keep a readable minimum font and column width rather than shrinking the whole table.
        # Wide sections are divided into consecutive bands, repeating the identifying first column.
        bands = []
        if sum(widths) <= available:
            bands = [list(range(count))]
        else:
            current = [0]
            for column in range(1, count):
                if len(current) > 1 and sum(widths[i] for i in current) + widths[column] > available:
                    bands.append(current)
                    current = [0]
                current.append(column)
            bands.append(current)
        # A single exceptionally wide cell must still fit in the page frame.
        widths = [min(width, available - (widths[0] if i else 0) - 1) if i else min(width, available * .45)
                  for i, width in enumerate(widths)] if len(bands) > 1 else [min(width, available) for width in widths]
        def header_cell(text):
            parts = [p.strip() for p in str(text).split(" | ")]
            if len(parts) == 1: return pdf_paragraph(parts[0], header_style, True)
            return [pdf_paragraph(p, header_style, True) for p in parts]  # English above, Arabic below
        if report_rtl and len(bands) == 1: bands = [bands[0][::-1]]  # 2.9.119: the first column on the right
        for band in bands:
            if len(bands) > 1:
                story.append(pdf_paragraph(f"Columns {band[1] + 1}–{band[-1] + 1} of {count} (first column repeated)", styles["Normal"]))
            data = [[header_cell(headers[i]) for i in band]]
            bold_rows = set(section.get("total_rows") or [])
            if financial:  # 2.9.83: caption-only rows (ASSETS, CASH FLOWS FROM ...) are headings
                bold_rows |= {n for n, r in enumerate(body) if r and r[0] and len(r) > 1 and all(not v for v in r[1:])}
            for number, row in enumerate(body):
                bold = number in bold_rows
                data.append([pdf_paragraph(row[i], (number_bold if bold else number_style) if _looks_numeric(row[i]) else (cell_bold if bold else cell_style), bold) for i in band])
            table = Table(data, repeatRows=1, splitInRow=1, colWidths=[widths[i] for i in band])
            style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#071B2E")),
                     ("GRID", (0, 0), (-1, -1), .25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                     ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F8")]),
                     ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
            if financial:
                style=[("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EDF2F6")),
                       ("LINEBELOW",(0,0),(-1,0),.7,colors.HexColor("#071B2E")),
                       ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                       ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]
                for index,row in enumerate(body):
                    heading=row and row[0] and len(row)>1 and all(not value for value in row[1:])
                    if heading:
                        style += [("TEXTCOLOR",(0,index+1),(-1,index+1),colors.HexColor("#071B2E")),
                                  ("TOPPADDING",(0,index+1),(-1,index+1),7)]
            for position, column in enumerate(band):
                if any(value and _looks_numeric(value) for value in (row[column] for row in body)):
                    style.append(("ALIGN", (position, 1), (position, -1), "RIGHT"))
            for index in section.get("total_rows") or []:
                if 0 <= index < len(body):
                    if financial:
                        style += [("LINEABOVE",(0,index+1),(-1,index+1),.45,colors.HexColor("#9AAABA"))]
                        if index>0:style.append(("NOSPLIT",(0,index),(-1,index+1)))
                        if index in section.get("major_total_rows",[]):
                            style += [("LINEBELOW",(0,index+1),(-1,index+1),1,colors.HexColor("#071B2E")),
                                      ("BACKGROUND",(0,index+1),(-1,index+1),colors.HexColor("#F2F5F8"))]
                    else:style += [("BACKGROUND", (0, index + 1), (-1, index + 1), colors.HexColor("#E8EDF2"))]
            for index in section.get('warning_rows',[]):
                if 0<=index<len(body):style.append(("BACKGROUND",(0,index+1),(-1,index+1),colors.HexColor("#FFF0EB")))
            table.setStyle(TableStyle(style))
            if section.get("keep_together") and len(bands) == 1 and not section.get("chart"):
                # Keep short summary tables with their heading when they fit a page.
                # Large tables retain normal pagination instead of becoming unrenderable.
                _width, table_height = table.wrap(available, doc.height)
                heading = story[-1]
                _width, heading_height = heading.wrap(available, doc.height)
                if table_height + heading_height + 24 < doc.height:
                    from reportlab.platypus import KeepTogether
                    story.pop(); story += [KeepTogether([heading, table]), Spacer(1, 5*mm)]
                    continue
            story += [table, Spacer(1, 5*mm)]

    def footer(canvas, document):
        canvas.saveState(); canvas.setFont(regular, 7); canvas.setFillColor(colors.HexColor("#5F6B76"))
        footer_title = title.split(" | ")[0] if has_arabic(title) else title
        if has_arabic(footer_title) and arabic_fonts()[0]:  # 2.9.119: an Arabic title is drawn with the Arabic font
            canvas.setFont(arabic_fonts()[0], 8); footer_title = shape_arabic(footer_title)
        if financial and document.page>2 and meta:
            company=str(meta[0]); font=arabic_fonts()[0] if has_arabic(company) else bold_font
            company=shape_arabic(company); font=font or regular
            from reportlab.pdfbase.pdfmetrics import stringWidth
            while company and stringWidth(company,font,8)>doc.width:company=company[:-1]
            canvas.setFont(font,8);canvas.drawCentredString(page[0]/2,page[1]-6*mm,company)
        canvas.setFont(regular,7)
        canvas.drawString(8*mm, 6*mm, footer_title); canvas.setFont(regular, 7); canvas.drawRightString(page[0] - 8*mm, 6*mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _with_libraries(function):
    @_functools.wraps(function)
    def run(*args, **kwargs):
        _load_libraries(); return function(*args, **kwargs)
    return run


for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, "__module__", None) == __name__ and isinstance(_value, type(_load_libraries)) \
            and _name not in ("_load_libraries", "_with_libraries"):
        globals()[_name] = _with_libraries(_value)
del _name, _value
