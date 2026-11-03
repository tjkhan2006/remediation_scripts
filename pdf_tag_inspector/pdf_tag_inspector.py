#!/usr/bin/env python3
"""Desktop PDF accessibility tag inspector and metadata editor."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont
from tkinter.scrolledtext import ScrolledText

try:
    import pikepdf
    from PIL import Image, ImageTk
    from engine import Document
except ImportError as exc:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('Dependencies needed', f'{exc}\n\nRun: python -m pip install -r requirements.txt')
    root.destroy()
    raise SystemExit(1)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PDF Tag Inspector - Accessibility Tags')
        self.geometry('1480x920')
        self.minsize(1060, 660)
        self.doc = None
        self.selected = None
        self.page_no = 0
        self.visible = []
        self.busy = False
        self.pending_render = False
        self.closing = False
        self.editor_id = None
        self.editor_original = None
        self.resize_job = self.filter_job = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.results = queue.Queue()
        self.photo = None
        self.path_var = tk.StringVar()
        self.query = tk.StringVar()
        self.role = tk.StringVar(value='All tags')
        self.page_filter = tk.StringVar(value='All pages')
        self.missing_alt = tk.BooleanVar()
        self.zoom = tk.StringVar(value='Fit page')
        self.highlight = tk.BooleanVar(value=True)
        self.page_input = tk.StringVar(value='1')
        self.status = tk.StringVar(value='Open a PDF to explore its accessibility tags.')
        self.count = tk.StringVar(value='No document open')
        self.preview_note = tk.StringVar(value='Select a tag to view its page and content outlines.')
        self.location = tk.StringVar(value='No tag selected')
        self._build()
        self.bind('<Control-o>', lambda e: self.browse())
        self.bind('<Control-s>', lambda e: self.save())
        self.bind('<Control-f>', lambda e: self.search_entry.focus_set())
        self.bind('<Command-o>', lambda e: self.browse())
        self.bind('<Command-s>', lambda e: self.save())
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(60, self.poll)

    def _build(self):
        style = ttk.Style(self)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        elif 'clam' in style.theme_names():
            style.theme_use('clam')
        family = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'
        for named_font in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            tkfont.nametofont(named_font).configure(family=family, size=10)
        self.option_add('*Font', (family, 10))
        style.configure('.', font=(family, 10))
        if style.theme_use() == 'clam':
            style.configure('.', background='#f2f3f5')
            style.configure('Treeview', background='white', fieldbackground='white', foreground='#17212f')
            style.map('Treeview', background=[('selected', '#086bc1')], foreground=[('selected', 'white')])
            style.configure('TNotebook.Tab', padding=(9, 6))
        style.configure('Treeview', rowheight=25)
        style.configure('Heading.TLabel', font=(family, 11, 'bold'))
        style.configure('TButton', padding=(8, 5))
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill='x')
        ttk.Label(top, text='PDF').pack(side='left', padx=(0, 8))
        entry = ttk.Entry(top, textvariable=self.path_var)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda e: self.open_path(self.path_var.get()))
        ttk.Button(top, text='Browse...', command=self.browse).pack(side='left', padx=6)
        ttk.Button(top, text='Open PDF', command=lambda: self.open_path(self.path_var.get())).pack(side='left')
        ttk.Button(top, text='Save edited copy...', command=self.save).pack(side='left', padx=(6, 0))
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        left, center, right = (ttk.Frame(panes, padding=8) for _ in range(3))
        panes.add(left, weight=3)
        panes.add(center, weight=5)
        panes.add(right, weight=2)
        left.configure(width=410)
        center.configure(width=660)
        right.configure(width=300)
        ttk.Label(left, text='Tags in document', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(left, text='Search tag metadata / structure path').pack(anchor='w')
        self.search_entry = ttk.Entry(left, textvariable=self.query)
        self.search_entry.pack(fill='x', pady=(3, 8))
        filters = ttk.Frame(left)
        filters.pack(fill='x')
        ttk.Label(filters, text='Tag type').grid(row=0, column=0, sticky='w')
        ttk.Label(filters, text='PDF page').grid(row=0, column=1, sticky='w', padx=(8, 0))
        self.role_combo = ttk.Combobox(filters, state='readonly', textvariable=self.role, values=['All tags'], width=19)
        self.role_combo.grid(row=1, column=0, sticky='ew')
        self.page_combo = ttk.Combobox(filters, state='readonly', textvariable=self.page_filter, values=['All pages'], width=10)
        self.page_combo.grid(row=1, column=1, sticky='ew', padx=(8, 0))
        filters.columnconfigure(0, weight=2)
        filters.columnconfigure(1, weight=1)
        ttk.Checkbutton(left, text='Figures without alt text', variable=self.missing_alt, command=self.filter_tags).pack(anchor='w', pady=(8, 4))
        ttk.Label(left, textvariable=self.count).pack(anchor='w', pady=(0, 5))
        self.list_tabs = ttk.Notebook(left)
        self.list_tabs.pack(fill='both', expand=True)
        flat_frame, tree_frame = ttk.Frame(self.list_tabs), ttk.Frame(self.list_tabs)
        self.list_tabs.add(flat_frame, text='Filtered list')
        self.list_tabs.add(tree_frame, text='Tag tree')
        self.flat = self.make_tree(flat_frame, ('role', 'pages', 'title'), 'headings')
        for key, label, width in [('role', 'Tag', 65), ('pages', 'Pages', 72), ('title', 'Title / alt text', 210)]:
            self.flat.heading(key, text=label)
            self.flat.column(key, width=width, minwidth=45)
        self.tree = self.make_tree(tree_frame, ('pages',), 'tree headings')
        self.tree.heading('#0', text='Structure')
        self.tree.heading('pages', text='Pages')
        self.tree.column('#0', width=240)
        self.tree.column('pages', width=75)
        self.tree.tag_configure('context', foreground='#777777')
        self.flat.bind('<<TreeviewSelect>>', lambda e: self.on_select(self.flat))
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select(self.tree))
        actions = ttk.Frame(left)
        actions.pack(fill='x', pady=(8, 0))
        ttk.Button(actions, text='Reset filters', command=self.reset_filters).pack(side='left')
        ttk.Button(actions, text='Export results...', command=self.export).pack(side='right')
        ttk.Label(center, text='Selected tag', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        tabs = ttk.Notebook(center)
        tabs.pack(fill='both', expand=True)
        preview, details, summary = (ttk.Frame(tabs) for _ in range(3))
        tabs.add(preview, text='Rendered preview')
        tabs.add(details, text='Tag structure & text')
        tabs.add(summary, text='Document summary')
        nav = ttk.Frame(preview, padding=(4, 8))
        nav.pack(fill='x')
        ttk.Button(nav, text='<', width=3, command=lambda: self.change_page(-1)).pack(side='left')
        ttk.Label(nav, text='Page').pack(side='left', padx=4)
        page_entry = ttk.Entry(nav, textvariable=self.page_input, width=5)
        page_entry.pack(side='left')
        page_entry.bind('<Return>', lambda e: self.goto_page())
        self.page_total = ttk.Label(nav, text='/ 0')
        self.page_total.pack(side='left', padx=4)
        ttk.Button(nav, text='>', width=3, command=lambda: self.change_page(1)).pack(side='left')
        zoom_combo = ttk.Combobox(nav, textvariable=self.zoom, values=['Fit page', 'Fit width', '50%', '75%', '100%', '125%', '150%', '200%'], width=10, state='readonly')
        zoom_combo.pack(side='right')
        zoom_combo.bind('<<ComboboxSelected>>', lambda e: self.request_render())
        ttk.Checkbutton(nav, text='Outline tag', variable=self.highlight, command=self.request_render).pack(side='right', padx=4)
        tag_nav = ttk.Frame(preview, padding=(4, 0, 4, 5))
        tag_nav.pack(fill='x')
        ttk.Label(tag_nav, text='Selected tag pages:').pack(side='left')
        self.tag_pages = ttk.Combobox(tag_nav, state='readonly', width=12)
        self.tag_pages.pack(side='left', padx=5)
        self.tag_pages.bind('<<ComboboxSelected>>', lambda e: self.goto_tag_page())
        canvas_frame = ttk.Frame(preview)
        canvas_frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(canvas_frame, background='#dfe3e7', highlightthickness=0)
        vs = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        hs = ttk.Scrollbar(canvas_frame, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind('<Configure>', self.on_resize)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        self.canvas.bind('<Button-4>', lambda e: self.canvas.yview_scroll(-1, 'units'))
        self.canvas.bind('<Button-5>', lambda e: self.canvas.yview_scroll(1, 'units'))
        self.canvas.create_text(260, 220, text='Open a PDF to get started', font=(family, 14), fill='#626c78')
        ttk.Label(preview, textvariable=self.preview_note, wraplength=600).pack(fill='x', padx=6, pady=8)
        self.detail_text = ScrolledText(details, wrap='word', font=('Consolas', 10), width=45, state='disabled')
        self.detail_text.pack(fill='both', expand=True, padx=6, pady=6)
        self.summary_text = ScrolledText(summary, wrap='word', font=(family, 10), width=45, state='disabled')
        self.summary_text.pack(fill='both', expand=True, padx=6, pady=6)
        ttk.Label(right, text='Object properties', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(right, textvariable=self.location, wraplength=300).pack(fill='x', pady=(0, 8))
        self.property_tabs = ttk.Notebook(right)
        self.property_tabs.pack(fill='both', expand=True)
        content_props, tag_props, color_props = (ttk.Frame(self.property_tabs, padding=8) for _ in range(3))
        self.property_tabs.add(content_props, text='Content')
        self.property_tabs.add(tag_props, text='Tag')
        self.property_tabs.add(color_props, text='Color')
        self.property_tabs.select(tag_props)
        self.content_info = tk.StringVar(value='No tag selected')
        ttk.Label(content_props, textvariable=self.content_info, wraplength=280).pack(fill='x', pady=(0, 10))
        self.fields = {}
        for parent, key, label, height in [(tag_props, 'role', 'Type / container tag', 1), (tag_props, 'title', 'Title', 1), (tag_props, 'actual_text', 'Actual text', 3), (tag_props, 'alt', 'Alternate text (images / links)', 5), (tag_props, 'language', 'Language (for example en-US)', 1), (content_props, 'expansion', 'Expansion text', 6)]:
            ttk.Label(parent, text=label).pack(anchor='w', pady=(6, 3))
            if height == 1:
                widget = ttk.Entry(parent, width=28)
            else:
                widget = tk.Text(parent, height=height, width=28, wrap='word', font=(family, 10), relief='solid', borderwidth=1)
                widget.bind('<Tab>', lambda e: (e.widget.tk_focusNext().focus_set(), 'break')[1])
                widget.bind('<Shift-Tab>', lambda e: (e.widget.tk_focusPrev().focus_set(), 'break')[1])
            widget.pack(fill='x')
            self.fields[key] = widget
        self.id_var = tk.StringVar()
        ttk.Label(tag_props, text='ID (read-only)').pack(anchor='w', pady=(8, 3))
        ttk.Entry(tag_props, textvariable=self.id_var, state='readonly', width=28).pack(fill='x')
        ttk.Button(tag_props, text='View attribute objects...', command=lambda: self.property_dialog('Attribute objects', 'attributes')).pack(fill='x', pady=(10, 3))
        ttk.Button(tag_props, text='View attribute classes...', command=lambda: self.property_dialog('Attribute classes', 'classes')).pack(fill='x', pady=3)
        ttk.Button(content_props, text='View full tag dictionary...', command=lambda: self.property_dialog('PDF tag dictionary', 'dictionary')).pack(fill='x', pady=12)
        ttk.Label(content_props, text='Language is edited in the Tag tab. Alternate descriptions for links use the tag\'s alternate-text property.', wraplength=280).pack(fill='x', pady=8)
        self.color_text = ScrolledText(color_props, wrap='word', width=28, height=15, state='disabled', font=(family, 10))
        self.color_text.pack(fill='both', expand=True)
        ttk.Label(color_props, text='Color information is read-only and applies to the selected PDF page. ICC conversion and profile embedding are not available.', wraplength=280).pack(fill='x', pady=8)
        ttk.Button(right, text='Apply changes to tag', command=self.apply_edit).pack(fill='x', pady=(10, 3))
        ttk.Button(right, text='Undo last applied edit', command=self.undo).pack(fill='x', pady=3)
        ttk.Label(right, text='Apply each edit, then save an edited copy. Empty fields remove that property.', wraplength=300).pack(fill='x', pady=8)
        ttk.Label(self, textvariable=self.status, relief='sunken', anchor='w', padding=(10, 5)).pack(fill='x', side='bottom')
        for variable in (self.query, self.role, self.page_filter):
            variable.trace_add('write', self.schedule_filter)
        self.set_editor(None)
        def all_buttons(widget):
            return [child for child in widget.winfo_children() if isinstance(child, ttk.Button)] + [button for child in widget.winfo_children() for button in all_buttons(child)]
        self.action_buttons = all_buttons(self)

    @staticmethod
    def make_tree(parent, columns, show):
        tree = ttk.Treeview(parent, columns=columns, show=show, selectmode='browse')
        vs = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        hs = ttk.Scrollbar(parent, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        return tree

    def submit(self, work, done, message, error=None):
        if self.busy:
            return False
        self.busy = True
        self.status.set(message)
        self.configure(cursor='watch')
        for button in self.action_buttons:
            button.state(['disabled'])
        future = self.executor.submit(work)
        future.add_done_callback(lambda f: self.results.put((f, done, error)))
        return True

    def poll(self):
        try:
            while True:
                future, done, error = self.results.get_nowait()
                self.busy = False
                self.configure(cursor='')
                for button in self.action_buttons:
                    button.state(['!disabled'])
                try:
                    result = future.result()
                except Exception as exc:
                    self.status.set(f'Error: {exc}')
                    if error:
                        error(exc)
                    else:
                        messagebox.showerror('PDF Tag Inspector', str(exc), parent=self)
                else:
                    done(result)
                if self.pending_render and not self.busy:
                    self.pending_render = False
                    self.request_render()
        except queue.Empty:
            pass
        if not self.closing:
            self.after(60, self.poll)

    def editor_values(self):
        return {k: w.get('1.0', 'end-1c') if isinstance(w, tk.Text) else w.get() for k, w in self.fields.items()}

    def editor_changed(self):
        return self.editor_id is not None and self.editor_values() != self.editor_original

    def discard_draft(self):
        if not self.editor_changed():
            return True
        return messagebox.askyesno('Unapplied field changes', 'Discard the changes in the property fields? Use "Apply changes to tag" first to keep them.', parent=self)

    def browse(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='Open tagged PDF', filetypes=[('PDF documents', '*.pdf'), ('All files', '*.*')])
        if path:
            self.open_path(path)

    def open_path(self, path, password='', retry=False):
        if self.busy or not path:
            return
        if not retry:
            if not self.discard_draft():
                return
            if self.doc and self.doc.dirty and not messagebox.askyesno('Unsaved PDF edits', 'Open another PDF and discard unsaved applied edits?', parent=self):
                return
        path = str(Path(path).expanduser())
        if not Path(path).is_file():
            messagebox.showerror('File not found', 'Choose an existing PDF file.', parent=self)
            return
        old_doc = self.doc
        def load():
            new_doc = Document(path, password)
            if old_doc:
                old_doc.close()
            return new_doc
        def failed(exc):
            if isinstance(exc, pikepdf.PasswordError):
                answer = simpledialog.askstring('Password required', 'Enter the PDF password:', show='*', parent=self)
                if answer is not None:
                    self.open_path(path, answer, retry=True)
            else:
                messagebox.showerror('Could not open PDF', str(exc), parent=self)
        self.submit(load, self.loaded, 'Reading PDF accessibility structure...', failed)

    def loaded(self, doc):
        self.doc = doc
        self.selected = None
        self.page_no = 0
        self.path_var.set(doc.path)
        self.page_total.configure(text=f'/ {doc.page_count}')
        self.set_editor(None)
        self.refresh_options()
        self.reset_filters()
        self.update_summary()
        self.title(f'PDF Tag Inspector - {Path(doc.path).name}')
        self.request_render()

    def refresh_options(self):
        roles = sorted({t.role for t in self.doc.tags} | {t.mapped_role for t in self.doc.tags})
        self.role_combo.configure(values=['All tags']+roles)
        self.page_combo.configure(values=['All pages']+[str(i+1) for i in range(self.doc.page_count)])

    def reset_filters(self):
        self.query.set('')
        self.role.set('All tags')
        self.page_filter.set('All pages')
        self.missing_alt.set(False)
        self.filter_tags()

    def schedule_filter(self, *_):
        if self.filter_job:
            self.after_cancel(self.filter_job)
        self.filter_job = self.after(180, self.filter_tags)

    def filter_tags(self):
        self.filter_job = None
        if not self.doc:
            return
        if self.busy:
            self.filter_job = self.after(180, self.filter_tags)
            return
        page = None if self.page_filter.get() == 'All pages' else int(self.page_filter.get())-1
        self.visible = self.doc.filter(self.query.get().strip(), self.role.get(), page, self.missing_alt.get())
        self.flat.delete(*self.flat.get_children())
        self.tree.delete(*self.tree.get_children())
        matches = set(self.visible)
        context = set(matches)
        for i in self.visible:
            parent = self.doc.tags[i].parent
            while parent is not None and parent not in context:
                context.add(parent)
                parent = self.doc.tags[parent].parent
        for tag in self.doc.tags:
            pages = ', '.join(str(p+1) for p in sorted(tag.pages)) or 'Unknown'
            if tag.id in matches:
                self.flat.insert('', 'end', iid=str(tag.id), values=(tag.role, pages, (tag.title or tag.alt or tag.actual_text)[:160]))
            if tag.id in context:
                self.tree.insert('' if tag.parent is None else str(tag.parent), 'end', iid=str(tag.id), text=tag.role,
                                 values=(pages,), open=len(context)<250, tags=() if tag.id in matches else ('context',))
        self.count.set(f'{len(matches):,} of {len(self.doc.tags):,} tags | {self.doc.page_count} pages')
        for view in (self.flat, self.tree):
            if self.selected is not None and view.exists(str(self.selected)):
                view.selection_set(str(self.selected))

    def on_select(self, view):
        choices = view.selection()
        if not choices or not self.doc:
            return
        tag_id = int(choices[0])
        if tag_id == self.selected:
            return
        if self.busy or not self.discard_draft():
            view.selection_remove(*choices)
            if self.selected is not None and view.exists(str(self.selected)):
                view.selection_set(str(self.selected))
            return
        self.selected = tag_id
        self.set_editor(tag_id)
        pages = sorted(self.doc.tags[tag_id].pages)
        self.tag_pages.configure(values=[str(p+1) for p in pages])
        if pages and self.page_no not in pages:
            self.page_no = pages[0]
        self.tag_pages.set(str(self.page_no+1) if self.page_no in pages else '')
        for other in (self.flat, self.tree):
            if other != view and other.exists(str(tag_id)):
                other.selection_set(str(tag_id))
                other.see(str(tag_id))
        self.request_render()

    def set_editor(self, tag_id):
        self.editor_id = tag_id
        tag = self.doc.tags[tag_id] if tag_id is not None else None
        self.location.set(f'Tag {tag.id+1} | {tag.object_ref}\n{tag.role} -> {tag.mapped_role}' if tag else 'Select a tag from the list or tree.')
        self.id_var.set(tag.identifier if tag else '')
        self.content_info.set(f'Type: Container\nContainer tag: {tag.role}\nStructure role: {tag.mapped_role}\nEffective language: {tag.inherited_language or "Not specified"}\n\n{tag.path}' if tag else 'No tag selected')
        for key, widget in self.fields.items():
            widget.configure(state='normal')
            if isinstance(widget, tk.Text):
                widget.delete('1.0', 'end')
                widget.insert('1.0', getattr(tag, key) if tag else '')
            else:
                widget.delete(0, 'end')
                widget.insert(0, getattr(tag, key) if tag else '')
            if tag is None:
                widget.configure(state='disabled')
        self.editor_original = self.editor_values()

    def property_dialog(self, title, field):
        if self.selected is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry('760x540')
        dialog.transient(self)
        box = ScrolledText(dialog, wrap='word', font=('Consolas', 10))
        box.pack(fill='both', expand=True, padx=12, pady=12)
        self.put_text(box, getattr(self.doc.tags[self.selected], field) or '(not set)')
        ttk.Button(dialog, text='Close', command=dialog.destroy).pack(anchor='e', padx=12, pady=(0, 12))

    def apply_edit(self):
        if self.busy or self.editor_id is None:
            return
        tag_id, values = self.editor_id, self.editor_values()
        self.submit(lambda: self.doc.edit(tag_id, values), lambda changed: self.after_edit(tag_id, 'Edit applied. Save an edited copy to keep it.' if changed else 'No changes to apply.'), 'Applying tag edit...')

    def after_edit(self, tag_id, message):
        self.selected = tag_id
        self.set_editor(tag_id)
        self.refresh_options()
        self.filter_tags()
        self.update_summary()
        self.title(f'PDF Tag Inspector - {Path(self.doc.path).name}' + (' *' if self.doc.dirty else ''))
        self.request_render()
        self.status.set(message)

    def undo(self):
        if self.busy or not self.doc or not self.doc.history or not self.discard_draft():
            return
        self.submit(self.doc.undo, lambda tag_id: self.after_edit(tag_id, 'Last applied edit undone.'), 'Undoing edit...')

    def save(self):
        if self.busy or not self.doc:
            return
        if self.editor_changed():
            messagebox.showinfo('Apply field changes first', 'Click "Apply changes to tag" before saving to include the current field changes.', parent=self)
            return
        path = filedialog.asksaveasfilename(title='Save edited PDF copy', defaultextension='.pdf', initialfile=Path(self.doc.path).stem+'_edited.pdf', filetypes=[('PDF document', '*.pdf')])
        if path:
            def saved(result):
                self.status.set(f'Saved edited copy: {result}')
                self.title(f'PDF Tag Inspector - {Path(self.doc.path).name}')
                self.update_summary()
            self.submit(lambda: self.doc.save_copy(path), saved, 'Saving and verifying edited PDF...')

    def export(self):
        if not self.doc or self.busy:
            return
        path = filedialog.asksaveasfilename(title='Export filtered tags', defaultextension='.csv', initialfile='pdf_tags.csv', filetypes=[('CSV spreadsheet', '*.csv'), ('JSON', '*.json')])
        if path:
            if Path(path).resolve() == Path(self.doc.path):
                messagebox.showerror('Choose another path', 'The report cannot overwrite the open PDF.', parent=self)
                return
            ids = self.visible[:]
            self.submit(lambda: self.doc.export(path, ids), lambda _: self.status.set(f'Exported {len(ids)} tags to {path}'), 'Exporting filtered tags...')

    def change_page(self, step):
        if self.doc:
            self.page_no = max(0, min(self.doc.page_count-1, self.page_no+step))
            self.request_render()

    def goto_page(self):
        if not self.doc:
            return
        try:
            page = int(self.page_input.get())
            if not 1 <= page <= self.doc.page_count:
                raise ValueError()
        except ValueError:
            self.page_input.set(str(self.page_no+1))
            return
        self.page_no = page-1
        self.request_render()

    def goto_tag_page(self):
        if self.tag_pages.get():
            self.page_no = int(self.tag_pages.get())-1
            self.request_render()

    def on_resize(self, _event):
        if self.resize_job:
            self.after_cancel(self.resize_job)
        self.resize_job = self.after(220, self.request_render)

    def request_render(self):
        self.resize_job = None
        if not self.doc or not self.doc.page_count:
            return
        if self.busy:
            self.pending_render = True
            return
        self.pending_render = False
        page_no, selected = self.page_no, self.selected
        width, height = max(150, self.canvas.winfo_width()-40), max(150, self.canvas.winfo_height()-40)
        mode = self.zoom.get()
        def work():
            page = self.doc.render_doc[page_no]
            scale = min(width/page.rect.width, height/page.rect.height) if mode == 'Fit page' else width/page.rect.width if mode == 'Fit width' else float(mode.rstrip('%'))/100
            rendered = self.doc.render(page_no, scale)
            if selected is not None:
                try:
                    boxes, text, note, color_info = self.doc.selection(selected, page_no)
                except Exception as exc:
                    boxes, text, note, color_info = [], '', f'Page rendered; content outlines unavailable: {exc}', 'Color information unavailable.'
            else:
                boxes, text, note = [], '', 'Select a tag to view its content outlines.' if self.doc.tags else 'No accessibility structure tree found. Page preview is still available.'
            if selected is None:
                color_info = 'Select a tag to inspect its content colors.'
            return rendered, boxes, text, note, color_info
        def done(result):
            if page_no != self.page_no or selected != self.selected:
                self.pending_render = True
                return
            (w, h, pixels, scale), boxes, text, note, color_info = result
            self.photo = ImageTk.PhotoImage(Image.frombytes('RGB', (w, h), pixels))
            self.canvas.delete('all')
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            x, y = max(20, (cw-w)//2), max(20, (ch-h)//2)
            self.canvas.create_rectangle(x+4, y+4, x+w+4, y+h+4, fill='#bdc4cc', outline='')
            self.canvas.create_image(x, y, image=self.photo, anchor='nw')
            if self.highlight.get():
                for a, b, c, d in boxes:
                    a, b, c, d = max(0, a*scale), max(0, b*scale), min(w, c*scale), min(h, d*scale)
                    if c >= a and d >= b:
                        self.canvas.create_rectangle(x+a, y+b, x+c, y+d, outline='#e22f3b', width=2)
            self.canvas.configure(scrollregion=(0, 0, max(cw, w+40), max(ch, h+40)))
            self.page_input.set(str(page_no+1))
            if selected is not None:
                self.tag_pages.set(str(page_no+1) if page_no in self.doc.tags[selected].pages else '')
            self.preview_note.set(note)
            self.update_details(text)
            self.put_text(self.color_text, color_info)
            self.status.set(f'Page {page_no+1} of {self.doc.page_count} | {len(self.doc.tags):,} tags' + (' | Unsaved applied edits' if self.doc.dirty else ''))
        self.submit(work, done, f'Rendering page {page_no+1}...')

    @staticmethod
    def put_text(widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.configure(state='disabled')

    def update_details(self, extracted=''):
        if self.selected is None:
            self.put_text(self.detail_text, 'Select a tag to inspect its structure and text.')
            return
        tag = self.doc.tags[self.selected]
        refs = '\n'.join(f'Page {r.page+1 if r.page is not None else "unknown"}: ' + (f'MCID {r.mcid}, stream {r.stream or "page"}' if r.mcid is not None else f'Object rectangle {r.rect}') for r in tag.refs)
        children = '\n'.join(f'  {self.doc.tags[i].role} - tag {i+1}' for i in tag.children)
        self.put_text(self.detail_text, f'{tag.path}\n\nPDF object: {tag.object_ref}\nTag: {tag.role}\nMapped role: {tag.mapped_role}\nPages: {", ".join(str(p+1) for p in sorted(tag.pages)) or "Unknown"}\nLanguage: {tag.language or "Not set on this tag"}\n\nTitle\n{tag.title or "(not set)"}\n\nAlternate text\n{tag.alt or "(not set)"}\n\nActual text\n{tag.actual_text or "(not set)"}\n\nDirect content references\n{refs or "(none)"}\n\nChild tags\n{children or "(none)"}\n\nAttributes\n{tag.attributes or "(none)"}\n\nExtracted tagged text on page {self.page_no+1}\n{extracted or "(no extractable tagged text)"}\n\nText above is grouped by content reference; it is not a screen-reader reading-order simulation.')

    def update_summary(self):
        from collections import Counter
        counts = Counter(t.role for t in self.doc.tags)
        self.put_text(self.summary_text, f'{Path(self.doc.path).name}\n\n{self.doc.page_count} PDF pages\n{len(self.doc.tags):,} structure tags\n{sum(t.mapped_role == "Figure" and not t.alt.strip() for t in self.doc.tags)} figures without /Alt text\n\nTag counts\n'+'\n'.join(f'{role}: {count:,}' for role, count in sorted(counts.items()))+'\n\nNotes\n'+'\n'.join(self.doc.warnings or ['No structure parsing warnings.'])+'\n\nPage numbers are PDF positions, beginning with 1; printed page labels may differ. Gray tree nodes are ancestors included for context. Selecting a container outlines its descendants. Outlines are bounding boxes, not exact painted shapes.\n\nEditing changes tag types and metadata only. It does not validate PDF/UA or WCAG compliance, repair reading order, or add missing tags. Saving a signed PDF changes the file and may invalidate its signatures.')

    def close_app(self):
        if self.busy:
            self.status.set('Please wait for the current operation to finish before closing.')
            return
        if not self.discard_draft():
            return
        if self.doc and self.doc.dirty and not messagebox.askyesno('Unsaved PDF edits', 'Close and discard unsaved applied edits?', parent=self):
            return
        self.closing = True
        if self.doc:
            self.doc.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    app = App()
    if len(sys.argv) > 1:
        app.after(100, lambda: app.open_path(sys.argv[1]))
    app.mainloop()


if __name__ == '__main__':
    main()
