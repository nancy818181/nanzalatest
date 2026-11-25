"""Purchase Invoice header (26-10-2026): one aligned grid of label | field pairs, sized to the visible page width.

Checked on the real program window (skipped without a display): every header control is shown inside the window,
each label is level with its field and on the correct side (left in English, right in Arabic), inputs share one height,
the buttons of each action row share one height, and a purchase typed through these fields still saves balanced."""
import tests_setup  # noqa: F401
import secrets
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

from client import ApiClient
from server import run_server

HEADER = ("Supplier", "Supplier Invoice No.", "Date", "Due Date", "Currency", "Type", "Document",
          "Cost / Asset A/C", "VAT A/C", "Paid", "Paid from A/C", "VAT Treatment")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display for the program window")
class PurchaseHeaderLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.password = secrets.token_urlsafe(24)
        database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database),
                                                    "admin_password": cls.password}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: ApiClient(cls.url).login("admin", cls.password); break
            except Exception: time.sleep(0.1)
        api = ApiClient(cls.url); api.login("admin", cls.password); cls.company = api.companies()[0]

    @classmethod
    def tearDownClass(cls):
        import gc; gc.collect(); cls.folder.cleanup()

    def open(self, language="en"):
        self.messages = []
        for name in ("showerror", "showwarning", "showinfo", "askyesno"):
            patch = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, n=name, **k: self.messages.append((n, a)) or True)
            patch.start(); self.addCleanup(patch.stop)
        import desktop, arabic_ui, gc
        self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy); self.addCleanup(arabic_ui.switch, app, "en")
        app.server.set(self.url); app.password.set(self.password); app.language.set(language); app.login()
        year = self.company["years"][0]["year"]
        app.client.select_company_year(self.company["id"], year); app.current_company = self.company; app.current_fiscal_year = int(year)
        app.geometry("1366x728+0+0"); app.update(); app.main_screen(); app.update()
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("purchases_tab")]); app.purchase_notebook.select(0)
        for _ in range(4): app.update_idletasks(); app.update()
        return app

    def header(self, app):
        widgets = app.purchase_form["header_widgets"]
        labels = {}
        for label in widgets["Supplier"].master.winfo_children():
            if isinstance(label, tk.Label): labels[label] = label
        import arabic_ui
        shown = {str(label.cget("text")): label for label in labels}
        # several English texts share one Arabic text, so look each label up by the text it should show
        by_text = {text: shown.get(arabic_ui.translate(text) if arabic_ui.active() else text) for text in HEADER}
        return widgets, by_text

    def check_layout(self, app, rtl):
        widgets, labels = self.header(app)
        self.assertEqual(sorted(widgets), sorted(HEADER))
        left, right = app.winfo_rootx(), app.winfo_rootx() + app.winfo_width()
        heights = set()
        for text in HEADER:
            with self.subTest(field=text):
                field, label = widgets[text], labels[text]
                for widget in (field, label):
                    self.assertTrue(widget.winfo_ismapped(), text)
                    self.assertGreaterEqual(widget.winfo_rootx(), left - 1, text)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right + 1, text)
                self.assertLessEqual(label.winfo_reqwidth(), label.winfo_width() + 1, f"label clipped: {text}")
                middle = lambda w: w.winfo_rooty() + w.winfo_height() / 2
                self.assertLessEqual(abs(middle(label) - middle(field)), 2, f"label not level: {text}")
                gap = (label.winfo_rootx() - field.winfo_rootx() - field.winfo_width()) if rtl else \
                      (field.winfo_rootx() - label.winfo_rootx() - label.winfo_width())
                self.assertTrue(0 <= gap <= 24, f"{text}: label {gap}px from its field (wrong side if negative)")
                heights.add(field.winfo_height())
        self.assertLessEqual(max(heights) - min(heights), 2, f"input heights differ: {sorted(heights)}")
        save = next(b for b in self.buttons(app.purchase_invoice_page) if self.english(b) == "Save Purchase")
        row = [b for b in save.master.winfo_children() if isinstance(b, tk.Button) and b.winfo_ismapped()]
        self.assertEqual(len({b.winfo_height() for b in row}), 1, [(self.english(b), b.winfo_height()) for b in row])

    def english(self, widget):
        import arabic_ui
        return arabic_ui.english(str(widget.cget("text")))

    def test_sales_summary_stays_visible_while_header_and_items_scroll(self):
        app = self.open("en")
        import arabic_ui
        app.tk.call("tk", "scaling", 2.0)
        app.state("normal"); app.geometry("1366x728+0+0")
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("sales_tab")])
        app.sales_currency.set("USD"); app.sales_items=[]
        app.sales_sheet.delete(*app.sales_sheet.get_children())
        for i in range(12):
            app.add_sales_item({"description":f"Synthetic line {i}","quantity":3,"unit_price":"1.005","vat_rate":11},update_totals=False)
        app.update_sales_totals()
        self.assertEqual(app.sales_sheet.item(app.sales_items[0]["_iid"],"values")[4],"1.005")
        self.assertEqual(app.sales_sheet.item(app.sales_items[0]["_iid"],"values")[-1],"3.02")
        for language in ("en","ar"):
            with self.subTest(language=language):
                arabic_ui.switch(app,language)
                for _ in range(4): app.update_idletasks(); app.update()
                expected={"Total":"36.24","Discount":"0.00","Total HT":"36.24","VAT":"3.96","TOTAL":"40.20 USD"}
                positions={}
                for key,label in app.sales_total_labels.items():
                    self.assertEqual(label.cget("text"),expected[key])
                    self.assertTrue(label.winfo_ismapped())
                    self.assertGreaterEqual(label.winfo_rootx(),app.winfo_rootx())
                    self.assertLessEqual(label.winfo_rootx()+label.winfo_width(),app.winfo_rootx()+app.winfo_width())
                    self.assertLessEqual(label.winfo_rooty()+label.winfo_height(),app.winfo_rooty()+app.winfo_height())
                    positions[key]=label.winfo_rooty()
                self.assertGreater(app.sales_sheet.winfo_height(),60)
                self.assertTrue(app.sales_save_button.winfo_ismapped())
                def scrolls(widget):
                    for child in widget.winfo_children():
                        if getattr(child,"_saber_scroll_page",False):child.yview_moveto(1)
                        scrolls(child)
                scrolls(app.sales_tab); app.sales_sheet.yview_moveto(1); app.update()
                self.assertEqual(positions,{key:label.winfo_rooty() for key,label in app.sales_total_labels.items()})
        self.assertFalse([m for m in self.messages if m[0]=="showerror"],self.messages)

    def test_rate_refresh_reads_change_from_a_second_session(self):
        app=self.open("en")
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("settings_tab")])
        app._load_settings_rates(force=True)
        other=ApiClient(self.url);self.addCleanup(other.close)
        other.login("admin",self.password)
        other.select_company_year(app.client.company_id,app.client.fiscal_year)
        other.save_exchange_rate({"date_from":"04-04-2024","from_currency":"EUR","to_currency":"USD","rate":"1.234567"})
        app._load_settings_rates(force=True)
        rows=[app.rates_tree.item(i,"values") for i in app.rates_tree.get_children()]
        self.assertTrue(any(r[0]=="04-04-2024" and r[1:3]==("EUR","USD") and abs(float(r[3])-1.234567)<1e-9 for r in rows),rows)

    def test_rule_updates_review_is_bilingual_read_only_and_reachable(self):
        import arabic_ui
        app=self.open("en")
        before=app.client.payroll_settings_list()
        for language in ("en", "ar"):
            app.language.set(language);arabic_ui.switch(app,language)
            window=app.open_rule_updates();app.update()
            self.assertEqual(window.title(),"تحديث القواعد" if language=="ar" else "Update Rules")
            captions=[str(b.cget("text")) for b in self.buttons(window)]
            self.assertIn("مراجعة / تحديث الفترات" if language=="ar" else "Review / update periods",captions)
            window.geometry("760x460");app.update()
            close=next(b for b in self.buttons(window) if str(b.cget("text")) in ("Close","إغلاق"))
            self.assertLessEqual(close.winfo_rooty()+close.winfo_height(),window.winfo_rooty()+window.winfo_height())
            window.destroy();app.update()
        self.assertEqual(app.client.payroll_settings_list(),before)
        self.assertFalse([m for m in self.messages if m[0]=="showerror"],self.messages)

    def test_english_save_captions_across_main_pages(self):
        """English page creation must not leak the Arabic save caption."""
        app = self.open("en")
        captions = []
        def inspect(widget):
            try:
                text = str(widget.cget("text"))
            except (tk.TclError, AttributeError):
                text = ""
            if "Save" in text or "حفظ" in text:
                captions.append(text)
                self.assertNotIn("حفظ", text, (str(widget), text))
            for child in widget.winfo_children():
                inspect(child)
        for page in list(app.main_tab_pages):
            app.select_main_tab(page)
            app.update()
            inspect(page)
        self.assertGreaterEqual(len(captions), 10, captions)

    def test_sales_save_uses_selected_language_after_reset(self):
        import arabic_ui
        app=self.open('en')
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index('sales_tab')])
        for language,caption in [('en','Save'),('ar','حفظ'),('en','Save')]:
            arabic_ui.switch(app,language)
            app.new_sales_invoice(confirm=False);app.update()
            self.assertEqual(app.sales_save_button.cget('text'),caption)

    def test_sales_five_line_edit_save_reopen_and_resize_matrix(self):
        import arabic_ui,json
        import traceback
        from decimal import Decimal
        app=self.open('en');app.select_main_tab(app.main_tab_pages[app._page_attributes.index('sales_tab')])
        app.report_callback_exception=lambda kind,value,tb:self.messages.append(('showerror',('callback',''.join(traceback.format_exception(kind,value,tb)))))
        observations=[]
        for language in ('en','ar'):
            arabic_ui.switch(app,language);app.new_sales_invoice(confirm=False)
            app.sales_items=[];app.sales_sheet.delete(*app.sales_sheet.get_children())
            app.sales_party.set('Synthetic sales matrix '+language);app.sales_currency.set('USD')
            for i in range(5):app.add_sales_item({'description':f'Unique sales item {i+1}','quantity':1,'unit_price':'10','vat_rate':11},update_totals=False)
            app.update_sales_totals()
            for scaling in (96/72,120/72,2.0):
                app.tk.call('tk','scaling',scaling)
                for width,height in ((1280,720),(1366,768),(1600,900),(1920,1080),(1366,768)):
                    app.state('normal');app.geometry(f'{width}x{height}+0+0')
                    for _ in range(5):app.update_idletasks();app.update()
                    app.after(250,app.quit);app.mainloop()
                    tree=app.sales_sheet;tree.yview_moveto(0);app.update()
                    rows=sum(bool(box:=tree.bbox(iid)) and box[1]+box[3]<=tree.winfo_height() and bool(app.sales_item_for(iid).get('description','').strip()) for iid in tree.get_children())
                    observations.append({'language':language,'requested':[width,height],'actual':app.geometry(),'tk_scaling':float(app.tk.call('tk','scaling')),'rows':rows,'table_height':tree.winfo_height(),'blocks':[(w.winfo_class(),w.winfo_height(),w.winfo_reqheight()) for w in app.sales_tab.winfo_children()]})
                    if (width,height)==(1366,768):self.assertGreaterEqual(rows,4,observations[-1])
                    total=app.sales_total_labels['TOTAL'];self.assertLessEqual(total.winfo_rooty()+total.winfo_height(),app.winfo_rooty()+app.winfo_height())
            fifth=app.sales_items[-1]['_iid'];tree.see(fifth);tree.selection_set(fifth);tree.focus(fifth);app.update()
            app.edit_sales_cell(column_index=2,iid=fifth);app.update()
            editor=next(w for w in tree.winfo_children() if isinstance(w,tk.Entry))
            editor.focus_force();editor.delete(0,'end');editor.insert(0,'2')
            if language=='en':
                editor.event_generate('<Return>');app.update()
                self.assertEqual(app.sales_total_labels['TOTAL'].cget('text'),'66.60 USD')
            number=app.sales_no.get();app.sales_save_button.invoke();app.update()
            self.assertFalse([m for m in self.messages if m[0] in ('showerror','showwarning')],self.messages)
            invoice=next(row for row in app.client.invoices() if row['invoice_number']==number)
            app.open_sales_invoice(invoice_id=invoice['id']);app.update()
            self.assertEqual(Decimal(str(app.sales_items[-1]['quantity'])),Decimal('2'))
            self.assertEqual(app.sales_total_labels['TOTAL'].cget('text'),'66.60 USD')
            self.assertEqual(app.sales_save_button.cget('text'),'حفظ' if language=='ar' else 'Save')
            for target in ('ar','en'):
                app.switch_language(target);app.update()
                self.assertEqual(app.sales_edit_id,invoice['id'])
                self.assertEqual(app.sales_total_labels['TOTAL'].cget('text'),'66.60 USD')
                self.assertEqual(Decimal(str(app.sales_items[-1]['quantity'])),Decimal('2'))
                self.assertEqual(app.sales_save_button.cget('text'),'حفظ' if target=='ar' else 'Save')
        print('PILOT_SALES_MATRIX '+json.dumps(observations))

    def test_cancel_language_change_preserves_unsaved_sales(self):
        app=self.open('en');app.select_main_tab(app.main_tab_pages[app._page_attributes.index('sales_tab')])
        app.add_sales_item({'description':'Unsaved must survive cancel','quantity':2,'unit_price':'10','vat_rate':11})
        before=app.sales_form_state()
        with mock.patch('tkinter.messagebox.askyesno',return_value=False):app.switch_language('ar')
        self.assertEqual(app.language.get(),'en')
        self.assertEqual(app.sales_form_state(),before)

    def test_purchase_first_item_is_inside_every_scroll_viewport(self):
        app=self.open("en")
        import arabic_ui
        app.state("normal");app.geometry("1366x728+0+0")
        app.purchase_item_line({"name":"Synthetic visible line","quantity":2,"unit_cost":"50","vat_flag":"Yes"})
        for language in ('en','ar'):
            with self.subTest(language=language):
                arabic_ui.switch(app,language)
                for _ in range(5):app.update_idletasks();app.update()
                tree=app.purchase_form['items_sheet'].tree
                box=tree.bbox(tree.get_children()[0]);self.assertTrue(box)
                row_top=tree.winfo_rooty()+box[1];row_bottom=row_top+box[3]
                ancestor=tree.master
                while ancestor is not None:
                    if getattr(ancestor,'_saber_scroll_page',False):
                        self.assertGreaterEqual(row_top,ancestor.winfo_rooty())
                        self.assertLessEqual(row_bottom,ancestor.winfo_rooty()+ancestor.winfo_height())
                    ancestor=ancestor.master
                self.assertLessEqual(row_bottom,app.winfo_rooty()+app.winfo_height())

    def buttons(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Button): yield child
            yield from self.buttons(child)

    def test_five_line_purchase_has_four_complete_rows_at_laptop_scaling(self):
        import arabic_ui,json
        from tkinter import ttk
        app=self.open('en');form=app.purchase_form
        sheet=form['items_sheet'];tree=sheet.tree
        for i in range(5):
            app.purchase_item_line({'name':f'Synthetic five-line item {i+1}', 'quantity':1,'unit_cost':'10','vat_flag':'Yes'})
        observations=[]
        for scaling in (96/72,120/72,2.0):
            app.tk.call('tk','scaling',scaling)
            for language in ('en','ar'):
                arabic_ui.switch(app,language)
                app.state('normal');app.geometry('1366x768+0+0')
                for _ in range(8):app.update_idletasks();app.update()
                tree.yview_moveto(0);app.update()
                visible=sum(bool(box:=tree.bbox(iid)) and box[1]+box[3]<=tree.winfo_height() for iid in tree.get_children())
                observations.append({'language':language,'tk_scaling':float(app.tk.call('tk','scaling')),'rows':visible,'table_height':tree.winfo_height(),'window':app.geometry()})
                self.assertGreaterEqual(visible,4,observations)
                fifth=tree.get_children()[-1];tree.see(fifth);tree.selection_set(fifth);app.update()
                self.assertTrue(tree.bbox(fifth))
        print('PILOT_LAYOUT '+json.dumps(observations))
        from decimal import Decimal
        for i in range(5):
            app.client.save_inventory_item({'sku':f'PILOT-R{i}','name':f'Pilot line {i+1}','unit':'unit'})
        for language in ('en','ar'):
            arabic_ui.switch(app,language);app.new_purchase()
            form=app.purchase_form;sheet=form['items_sheet'];tree=sheet.tree
            form['vars']['supplier'].set('Synthetic pilot supplier')
            form['vars']['number'].set('PILOT-FIVE-'+language)
            form['vars']['currency'].set('USD')
            for i in range(5):
                app.purchase_item_line({'item_code':f'PILOT-R{i}','name':f'Pilot line {i+1}','quantity':1,'unit_cost':'10','vat_flag':'Yes'})
            fifth=tree.get_children()[-1];tree.see(fifth);tree.selection_set(fifth);app.update()
            self.assertIsNot(app.purchase_item_changed(fifth,'quantity','2'),False)
            self.assertEqual(form['total'].cget('text'),'66.60 USD')
            next(b for b in self.buttons(app.purchase_invoice_page) if self.english(b)=='Save Purchase').invoke();app.update()
            self.assertFalse([m for m in self.messages if m[0]=='showerror'],self.messages)
            choice=next(label for label in form['find_map'] if label.startswith('PILOT-FIVE-'+language+' |'))
            form['find'].set(choice);form['find_box'].event_generate('<<ComboboxSelected>>');app.update()
            self.assertEqual(len(sheet.rows),5)
            self.assertEqual(Decimal(str(list(sheet.rows.values())[-1]['quantity'])),Decimal('2'))
            self.assertEqual(form['total'].cget('text'),'66.60 USD')
            saved_id=form.get('id') or form.get('selected_id')
            for target in ('ar','en'):
                app.switch_language(target);app.update()
                form=app.purchase_form;sheet=form['items_sheet']
                self.assertEqual(str(form.get('id') or form.get('selected_id')),str(saved_id))
                self.assertEqual(len(sheet.rows),5)
                self.assertEqual(form['total'].cget('text'),'66.60 USD')

    def test_purchase_resize_matrix_keeps_totals_and_editable_lines(self):
        import arabic_ui,json
        app=self.open('en');app.state('normal')
        for i in range(5):app.purchase_item_line({'name':f'Populated resize row {i}','quantity':1,'unit_cost':'10','vat_flag':'Yes'})
        records=[]
        for language in ('en','ar'):
            arabic_ui.switch(app,language)
            for width,height in ((1280,720),(1366,768),(1600,900),(1920,1080),(1366,768)):
                app.geometry(f'{width}x{height}+0+0');app.after(250,app.quit);app.mainloop();app.update()
                tree=app.purchase_form['items_sheet'].tree;tree.yview_moveto(0);app.update()
                rows=sum(bool(box:=tree.bbox(iid)) and box[1]+box[3]<=tree.winfo_height() for iid in tree.get_children())
                records.append({'language':language,'requested':[width,height],'actual':app.geometry(),'rows':rows,'table_height':tree.winfo_height()})
                if width==1366:self.assertGreaterEqual(rows,4,records[-1])
                total=app.purchase_form['total'];self.assertLessEqual(total.winfo_rooty()+total.winfo_height(),app.winfo_rooty()+app.winfo_height())
        print('PILOT_PURCHASE_RESIZE '+json.dumps(records))

    def test_english_header_is_aligned_and_a_purchase_still_saves(self):
        app = self.open("en")
        self.check_layout(app, rtl=False)
        widgets, _labels = self.header(app)
        v = app.purchase_form["vars"]
        widgets["Supplier"].set("Grid Supplier SARL")
        widgets["Supplier Invoice No."].insert(0, "GRID-1")
        widgets["Currency"].set("USD"); widgets["Type"].set("Purchases"); widgets["Document"].set("Invoice")
        widgets["Document"].event_generate("<<ComboboxSelected>>")
        v["taxable"].set("100"); app.purchase_amounts_changed("taxable"); app.update()
        total = app.purchase_form["total"]
        self.assertEqual(total.cget("text"), "111.00 USD")
        bottom = total.winfo_rooty() + total.winfo_height()
        self.assertLessEqual(bottom, app.winfo_rooty() + app.winfo_height())
        canvas = app.purchase_form["items_sheet"].tree
        while not getattr(canvas, "_saber_scroll_page", False):
            canvas = canvas.master
        canvas.yview_moveto(1)
        app.update_idletasks()
        self.assertEqual(total.winfo_rooty() + total.winfo_height(), bottom)
        app.save_purchase(); app.update()
        self.assertFalse([m for m in self.messages if m[0] in ("showerror", "showwarning")], self.messages)
        saved = [i for i in app.client.invoices() if i.get("invoice_number") == "GRID-1"]
        self.assertEqual(len(saved), 1, saved)
        self.assertEqual(saved[0]["party_name"], "Grid Supplier SARL")
        self.assertEqual(round(float(saved[0]["total"]), 2), 111.00)
        trial = app.client.trial_balance()
        rows = trial.get("items", trial) if isinstance(trial, dict) else trial
        debit = sum(float(r.get("debit") or 0) for r in rows); credit = sum(float(r.get("credit") or 0) for r in rows)
        self.assertAlmostEqual(debit, credit, places=2)

    def test_purchase_item_edit_and_reopen(self):
        from tkinter import ttk
        app = self.open()
        app.client.save_inventory_item({"sku": "GRID-PAPER", "name": "Layout paper", "unit": "pack"})
        form = app.purchase_form
        sheet = form["items_sheet"]
        form["vars"]["supplier"].set("Layout Line Supplier")
        form["vars"]["number"].set("GRID-LINES-1")
        form["vars"]["currency"].set("USD")
        items = sheet.tree.master.master
        next(b for b in self.buttons(items) if self.english(b) == "Add Item Line").invoke()
        app.update()
        row = sheet.tree.focus()
        pending_builders = tuple(app._pending_builders)
        self.assertIsNone(app.__dict__.get("items_tree"))
        app.purchase_item_lookup()
        app.update()
        self.assertEqual(tuple(app._pending_builders), pending_builders)
        self.assertIsNone(app.__dict__.get("items_tree"))
        dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Items - F2")
        lookup_tree = next(w for frame in dialog.winfo_children() for w in frame.winfo_children() if isinstance(w, ttk.Treeview))
        match = next(item for item in lookup_tree.get_children() if lookup_tree.item(item, "values")[0] == "GRID-PAPER")
        lookup_tree.selection_set(match)
        lookup_tree.focus_force()
        lookup_tree.event_generate("<Return>")
        app.update()
        self.assertEqual(sheet.rows[row]["item_code"], "GRID-PAPER")
        self.assertIsNot(app.purchase_item_changed(row, "unit_cost", "15.25"), False)
        self.assertEqual(sheet.rows[row]["unit_cost"], 15.25)
        next(b for b in self.buttons(items) if self.english(b) == "Add Item Line").invoke()
        app.update()
        next(b for b in self.buttons(items) if self.english(b) == "Delete Line").invoke()
        app.update()
        self.assertEqual(len(sheet.rows), 1)
        next(b for b in self.buttons(app.purchase_invoice_page) if self.english(b) == "Save Purchase").invoke()
        app.update()
        choice = next(label for label in form["find_map"] if label.startswith("GRID-LINES-1 |"))
        form["find"].set(choice)
        form["find_box"].event_generate("<<ComboboxSelected>>")
        app.update()
        saved, = sheet.rows.values()
        self.assertEqual(saved["item_code"], "GRID-PAPER")
        self.assertEqual(saved["unit_cost"], 15.25)
        self.assertFalse([m for m in self.messages if m[0] in ("showerror", "showwarning")], self.messages)

    def test_sales_menu_quotation_search_conversion_and_post(self):
        from decimal import Decimal
        from tkinter import ttk
        app = self.open()
        app.client.save_inventory_item({"sku": "QUOTE-UI-PAPER", "name": "Quotation UI paper", "unit": "ream"})
        customer = app.client.save_party({"name": "Quotation UI customer", "kind": "customer", "currency": "USD"})
        app.client.save_stock_document(
            {"doc_type": "receipt", "doc_date": app.fiscal_today(), "warehouse_id": "MAIN"},
            [{"sku": "QUOTE-UI-PAPER", "quantity": "5", "unit_cost": "3"}],
        )
        sales_menu, _ = app.side_menu_groups["Sales"]
        next(b for b in self.buttons(sales_menu) if self.english(b) == "Quotations").invoke()
        app.update()
        window = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and hasattr(w, "_commercial"))
        state = window._commercial
        tabs = state["tabs"]
        self.assertEqual([tabs.tab(tab, "text") for tab in tabs.tabs()], ["Quotation", "Search"])
        self.assertEqual(state["number"].get(), "Assigned on Save")
        state["fields"]["party"].set(next(label for label, pid in state["party_map"].items() if pid == customer["id"]))
        state["fields"]["currency"].set("USD")
        next(b for b in self.buttons(window) if self.english(b) == "Add line").invoke()
        app.update()
        line = next(w for w in window.winfo_children() if isinstance(w, tk.Toplevel))
        entries = [w for w in line.winfo_children() if isinstance(w, tk.Entry)]
        for entry, value in zip(entries, ("QUOTE-UI-PAPER", "Quotation UI paper", "2", "10", "11", "ream", "10")):
            entry.delete(0, "end")
            entry.insert(0, value)
        next(b for b in self.buttons(line) if self.english(b) == "Use line").invoke()
        next(b for b in self.buttons(window) if self.english(b) == "Save draft").invoke()
        quotation = state["document"]["number"]
        self.assertRegex(quotation, r"^QUO-\d{4}-\d{6}$")
        self.assertEqual(state["number"].get(), quotation)
        tabs.select(1)
        app.update()

        def widgets(widget):
            for child in widget.winfo_children():
                yield child
                yield from widgets(child)

        search = next(w for w in widgets(window) if isinstance(w, tk.Entry) and
                      any(isinstance(other, tk.Label) and other.cget("text") == "Find quotation"
                          for other in w.master.winfo_children()))
        results = next(w for w in widgets(window) if isinstance(w, ttk.Treeview) and "number" in w["columns"])
        search_button = next(b for b in self.buttons(window) if self.english(b) == "Search")
        for query in (quotation, "Quotation UI customer"):
            search.delete(0, "end")
            search.insert(0, query)
            search_button.invoke()
            self.assertIn(quotation, [results.set(iid, "number") for iid in results.get_children()])
        search.delete(0, "end")
        search.insert(0, "QUOTE-UI-PAPER Quotation UI paper")
        app.after(300, app.quit)
        app.mainloop()
        match = next(item for item in results.get_children() if quotation in results.item(item, "values"))
        self.assertIn("QUOTE-UI-PAPER", results.item(match, "values")[-1])
        results.selection_set(match)
        next(b for b in self.buttons(window) if self.english(b) == "Open selected").invoke()
        self.assertEqual(tabs.index(tabs.select()), 0)
        self.assertEqual(state["number"].get(), quotation)
        next(b for b in self.buttons(window) if self.english(b) == "Convert to Sales Invoice").invoke()
        app.update()
        invoice = app.client.invoice_detail(app.sales_edit_id)
        self.assertEqual(invoice["quotation_number"], quotation)
        self.assertEqual(invoice["invoice"]["status"], "review")
        self.assertEqual(Decimal(invoice["invoice"]["total"]), Decimal("19.98"))
        app.client.save_user({"username": "quote-ui-viewer", "password": "Quote-UI-Viewer-2026!", "role": "viewer"})
        viewer = ApiClient(self.url)
        self.addCleanup(viewer.close)
        viewer.login("quote-ui-viewer", "Quote-UI-Viewer-2026!")
        viewer.select_company_year(app.client.company_id, app.client.fiscal_year)
        with self.assertRaisesRegex(RuntimeError, "read-only"):
            viewer.request("POST", f"/api/commercial/{state['document']['id']}/convert",
                           {"doc_date": app.fiscal_today(), "revision": state["document"]["revision"]})
        invoice_id = app.sales_edit_id
        self.assertEqual(self.english(app.sales_save_button), "Post")
        app.sales_save_button.invoke()
        app.update()
        self.assertEqual(app.client.invoice_detail(invoice_id)["invoice"]["status"], "posted")
        self.assertFalse([m for m in self.messages if m[0] in ("showerror", "showwarning")], self.messages)

    def test_rapid_switching_keeps_input_and_refreshes_company_year(self):
        from tkinter import ttk
        app = self.open()
        source_company = app.current_company
        source_year = app.current_fiscal_year
        other = app.client.create_company({"name": "Navigation Isolation Demo", "year": source_year})
        app.client.request("POST", "/api/companies/year",
                           {"company_id": other["id"], "year": source_year + 1})

        def select(attribute):
            index = app._page_attributes.index(attribute)
            app.select_main_tab(app.main_tab_pages[index])

        def switch(company, year):
            button = next(b for b in self.buttons(app) if self.english(b) == "Switch Company / Year")
            button.invoke()
            opener = next(b for b in self.buttons(app) if self.english(b) == "Open Company")
            company_box, year_box = [w for w in opener.master.winfo_children() if isinstance(w, ttk.Combobox)]
            company_box.set(next(value for value in company_box["values"] if value.startswith(f"{company['name']} (")))
            company_box.event_generate("<<ComboboxSelected>>")
            year_box.set(str(year))
            opener.invoke()
            app.update()
            self.assertEqual((app.client.company_id, app.client.fiscal_year), (company["id"], year))

        form = app.purchase_form
        form["vars"]["supplier"].set("Navigation Demo Supplier")
        form["vars"]["number"].set("NAVIGATION-PURCHASE")
        form["vars"]["currency"].set("USD")
        form["vars"]["taxable"].set("100")
        app.purchase_amounts_changed("taxable")
        for _ in range(38):
            for route in ("dashboard_tab", "reports_tab", "sales_tab", "purchases_tab"):
                select(route)
                app.update()
            self.assertEqual(form["vars"]["number"].get(), "NAVIGATION-PURCHASE")
            self.assertEqual(form["total"].cget("text"), "111.00 USD")
        app.save_purchase()
        self.assertTrue(any(key.startswith("NAVIGATION-PURCHASE |") for key in form["find_map"]))
        for year in (source_year, source_year + 1):
            switch(other, year)
            select("purchases_tab")
            self.assertFalse(any("NAVIGATION-PURCHASE" in key for key in app.purchase_form["find_map"]))
        switch(source_company, source_year)
        select("purchases_tab")
        app.update()
        self.assertTrue(any(key.startswith("NAVIGATION-PURCHASE |") for key in app.purchase_form["find_map"]))
        self.assertFalse([m for m in self.messages if m[0] in ("showerror", "showwarning")], self.messages)

    def test_arabic_header_puts_each_label_right_of_its_field(self):
        app = self.open("ar")
        self.check_layout(app, rtl=True)

    def test_icon_and_text_buttons_of_a_row_get_one_height(self):
        """Windows draws an icon button 2 px lower than a text one with the same padding (CI 26-10-2026: 28 vs 30)."""
        from desktop_purchases import PurchasesMixin
        root = tk.Tk(); self.addCleanup(root.destroy)
        row = tk.Frame(root); row.pack()
        icon = tk.PhotoImage(master=root, width=12, height=12)
        short = tk.Button(row, text="New", image=icon, compound="left", pady=1); short.pack(side="left")
        tall = tk.Button(row, text="Cancel Purchase", pady=6); tall.pack(side="left")
        lower = tk.Button(row, text="Auto Calculate", pady=2); lower.pack(side="left")
        root.update()
        self.assertGreater(tall.winfo_reqheight(), short.winfo_reqheight())
        PurchasesMixin._even_button_heights(row); root.update()
        self.assertEqual({b.winfo_height() for b in (short, tall, lower)}, {tall.winfo_height()})

    def test_narrow_window_stacks_pairs_instead_of_hiding_fields(self):
        app = self.open("en")
        app.geometry("1024x700")
        for _ in range(4): app.update_idletasks(); app.update()
        self.check_layout(app, rtl=False)


if __name__ == "__main__":
    unittest.main()
