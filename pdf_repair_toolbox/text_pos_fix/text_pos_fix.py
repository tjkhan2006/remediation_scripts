#!/usr/bin/env python3
"""PDF text drawing-order repair desktop interface."""
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
    from repair_core import Document
except ImportError as exc:
    root = tk.Tk(); root.withdraw()
    messagebox.showerror('Dependencies needed', f'{exc}\nRun Start_Windows.bat or start.sh to set up dependencies.')
    root.destroy()
    raise SystemExit(1)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PDF Repair Toolbox - Text Position Fix')
        self.geometry('1480x920'); self.minsize(1060, 660)
        self.doc = None; self.page = 0; self.items = []; self.photo = None
        self.busy = False; self.resize_job = None; self.selection_box = None
        self.executor = ThreadPoolExecutor(max_workers=1); self.results = queue.Queue()
        self.path = tk.StringVar(); self.search = tk.StringVar()
        self.view = tk.StringVar(value='Repaired'); self.zoom = tk.StringVar(value='Fit page')
        self.page_input = tk.StringVar(value='1'); self.scope = tk.StringVar(value='All pages')
        self.page_range = tk.StringVar(); self.outlines = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Open a PDF to bring its page text in front of artwork.')
        self.note = tk.StringVar(value='No document open'); self.buttons = []
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        for event in ('<Control-o>', '<Command-o>'): self.bind(event, lambda e: self.browse())
        for event in ('<Control-s>', '<Command-s>'): self.bind(event, lambda e: self.save())
        self.search.trace_add('write', lambda *a: self.fill_text())
        self.after(60, self.poll)

    def button(self, parent, text, command, **kw):
        button = ttk.Button(parent, text=text, command=command, **kw)
        self.buttons.append(button)
        return button

    def _build(self):
        style = ttk.Style(self)
        style.theme_use('vista' if 'vista' in style.theme_names() else 'clam')
        family = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            tkfont.nametofont(name).configure(family=family, size=10)
        style.configure('.', font=(family, 10))
        if style.theme_use() == 'clam':
            style.configure('.', background='#f2f3f5')
            style.configure('Treeview', foreground='#17212f')
            style.map('Treeview', background=[('selected', '#086bc1')], foreground=[('selected', 'white')])
        style.configure('Treeview', rowheight=25, background='white', fieldbackground='white')
        style.configure('Heading.TLabel', font=(family, 11, 'bold'))
        style.configure('TButton', padding=(8, 5))
        style.configure('TNotebook.Tab', padding=(9, 6))
        top = ttk.Frame(self, padding=(12, 10)); top.pack(fill='x')
        ttk.Label(top, text='PDF').pack(side='left', padx=(0, 8))
        ttk.Entry(top, textvariable=self.path).pack(side='left', fill='x', expand=True)
        self.button(top, 'Browse...', self.browse).pack(side='left', padx=6)
        self.button(top, 'Open PDF', lambda: self.open_path(self.path.get())).pack(side='left')
        self.button(top, 'Save repaired copy...', self.save).pack(side='left', padx=(6, 0))
        panes = ttk.Panedwindow(self, orient='horizontal'); panes.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        left, center, right = [ttk.Frame(panes, padding=8) for _ in range(3)]
        for frame, weight in ((left, 3), (center, 5), (right, 2)): panes.add(frame, weight=weight)
        ttk.Label(left, text='Pages and text', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        self.pages = ttk.Treeview(left, columns=('status',), height=8, show='tree headings', selectmode='browse')
        self.pages.heading('#0', text='PDF page'); self.pages.column('#0', width=90)
        self.pages.heading('status', text='Repair status'); self.pages.column('status', width=170)
        self.pages.pack(fill='x'); self.pages.bind('<<TreeviewSelect>>', self.select_page)
        ttk.Label(left, text='Search text on current page').pack(anchor='w', pady=(10, 3))
        ttk.Entry(left, textvariable=self.search).pack(fill='x')
        listing = ttk.Frame(left); listing.pack(fill='both', expand=True, pady=6)
        self.text_list = ttk.Treeview(listing, columns=('text',), show='headings', selectmode='browse')
        self.text_list.heading('text', text='Existing text'); self.text_list.column('text', width=320)
        scroll = ttk.Scrollbar(listing, command=self.text_list.yview)
        self.text_list.configure(yscrollcommand=scroll.set)
        self.text_list.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        self.text_list.bind('<<TreeviewSelect>>', self.select_text)
        ttk.Label(center, text='Page preview', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        nav = ttk.Frame(center); nav.pack(fill='x', pady=(0, 8))
        self.button(nav, '<', lambda: self.goto(self.page - 1), width=3).pack(side='left')
        entry = ttk.Entry(nav, textvariable=self.page_input, width=5); entry.pack(side='left', padx=4)
        entry.bind('<Return>', self.goto_input)
        self.total = ttk.Label(nav, text='/ 0'); self.total.pack(side='left')
        self.button(nav, '>', lambda: self.goto(self.page + 1), width=3).pack(side='left', padx=4)
        for var, values in ((self.view, ['Original', 'Repaired']), (self.zoom, ['Fit page', 'Fit width', '50%', '75%', '100%', '125%', '150%', '200%'])):
            combo = ttk.Combobox(nav, textvariable=var, values=values, state='readonly', width=10)
            combo.pack(side='right', padx=3); combo.bind('<<ComboboxSelected>>', lambda e: self.render())
        ttk.Checkbutton(center, text='Outline selected text', variable=self.outlines, command=self.draw_outline).pack(anchor='w')
        canvas_frame = ttk.Frame(center); canvas_frame.pack(fill='both', expand=True, pady=6)
        self.canvas = tk.Canvas(canvas_frame, background='#dfe3e7', highlightthickness=0)
        vs = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        hs = ttk.Scrollbar(canvas_frame, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky='nsew'); vs.grid(row=0, column=1, sticky='ns'); hs.grid(row=1, column=0, sticky='ew')
        canvas_frame.rowconfigure(0, weight=1); canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind('<Configure>', self.resize)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        ttk.Label(center, textvariable=self.note, wraplength=600).pack(fill='x')
        ttk.Label(right, text='Text properties', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        self.details = ScrolledText(right, width=29, height=14, wrap='word', state='disabled')
        self.details.pack(fill='both', expand=True)
        ttk.Label(right, text='Repair scope').pack(anchor='w', pady=(12, 3))
        ttk.Combobox(right, textvariable=self.scope, values=['All pages', 'Current page', 'Page range'], state='readonly').pack(fill='x')
        ttk.Label(right, text='Page range (for example 1-3, 5)').pack(anchor='w', pady=(6, 3))
        ttk.Entry(right, textvariable=self.page_range).pack(fill='x')
        self.button(right, 'Bring text to front', self.repair).pack(fill='x', pady=(12, 3))
        self.button(right, 'Undo last repair', self.undo).pack(fill='x', pady=3)
        ttk.Label(right, text='Text coordinates and styling are preserved. Save a repaired copy after reviewing the preview.', wraplength=280).pack(fill='x', pady=8)
        ttk.Label(self, textvariable=self.status, relief='sunken', anchor='w', padding=(10, 5)).pack(fill='x', side='bottom')

    def submit(self, work, done, status):
        if self.busy: return
        self.busy = True; self.status.set(status)
        for button in self.buttons: button.state(['disabled'])
        future = self.executor.submit(work)
        future.add_done_callback(lambda f: self.results.put((f, done)))

    def poll(self):
        try:
            future, done = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons: button.state(['!disabled'])
            try: done(future.result())
            except pikepdf.PasswordError:
                password = simpledialog.askstring('Password', 'PDF password:', show='*', parent=self)
                if password is not None: self.open_path(self.path.get(), password)
            except Exception as exc:
                self.status.set(str(exc)); messagebox.showerror('Text Position Fix', str(exc), parent=self)
        self.after(60, self.poll)

    def discard_ok(self):
        return not self.doc or not self.doc.dirty or messagebox.askyesno('Unsaved repair', 'Discard unsaved repairs?', parent=self)

    def browse(self):
        path = filedialog.askopenfilename(filetypes=[('PDF documents', '*.pdf')])
        if path: self.open_path(path)

    def open_path(self, path, password=''):
        if self.busy or not path or not self.discard_ok(): return
        self.path.set(path)
        def opened(doc):
            if self.doc: self.doc.close()
            self.doc = doc; self.page = 0; self.items = []; self.selection_box = None
            self.details.configure(state="normal"); self.details.delete("1.0", "end"); self.details.configure(state="disabled")
            self.update_pages(); self.render()
        self.submit(lambda: Document(path, password), opened, 'Analyzing PDF drawing order...')

    def update_pages(self):
        self.pages.delete(*self.pages.get_children())
        for i, plan in enumerate(self.doc.plans): self.pages.insert('', 'end', iid=str(i), text=f'Page {i+1}', values=(plan.state,))
        self.total.configure(text=f'/ {len(self.doc.plans)}')

    def select_page(self, event=None):
        selected = self.pages.selection()
        if selected: self.goto(int(selected[0]))

    def goto_input(self, event=None):
        try: self.goto(int(self.page_input.get()) - 1)
        except ValueError: self.status.set('Enter a valid PDF page number.')

    def goto(self, page):
        if self.busy or not self.doc: return
        if 0 <= page < len(self.doc.plans):
            self.page = page; self.selection_box = None; self.render()

    def resize(self, event=None):
        if self.resize_job: self.after_cancel(self.resize_job)
        self.resize_job = self.after(250, self.render)

    def render(self):
        self.resize_job = None
        if not self.doc or self.busy: return
        page = self.page; original = self.view.get() == 'Original'; zoom = self.zoom.get()
        width, height = max(100, self.canvas.winfo_width()-30), max(100, self.canvas.winfo_height()-30)
        def work():
            with self.doc._renderer(self.doc.original) as pdf:
                rect = pdf[page].rect
                scale = min(width / rect.width, height / rect.height) if zoom == 'Fit page' else width / rect.width if zoom == 'Fit width' else float(zoom.rstrip('%')) / 100
                rotation = tuple(pdf[page].rotation_matrix)
            return self.doc.render(page, scale, original), self.doc.text_items(page), scale, rotation
        def done(result):
            (w, h, samples), self.items, self.scale, self.rotation = result
            self.photo = ImageTk.PhotoImage(Image.frombytes('RGB', (w, h), samples))
            self.canvas.delete('all'); self.canvas.create_image(10, 10, anchor='nw', image=self.photo)
            self.canvas.configure(scrollregion=(0, 0, w+20, h+20))
            self.page_input.set(str(page+1)); self.fill_text(); self.draw_outline()
            plan = self.doc.plans[page]; self.note.set(f'Page {page+1}: {plan.reason}')
            self.status.set(f'{"Original" if original else "Repaired"} preview — {len(self.items)} text spans on page {page+1}.')
            if (self.view.get() == 'Original') != original or self.zoom.get() != zoom:
                self.render()
        self.submit(work, done, 'Rendering page...')

    def fill_text(self):
        self.text_list.delete(*self.text_list.get_children())
        query = self.search.get().casefold()
        for i, item in enumerate(self.items):
            if query in item['text'].casefold(): self.text_list.insert('', 'end', iid=str(i), values=(item['text'],))

    def select_text(self, event=None):
        selected = self.text_list.selection()
        if not selected: return
        item = self.items[int(selected[0])]; self.selection_box = item['bbox']
        text = f"Text: {item['text']}\n\nPage: {self.page+1}\nBounds (points): {item['bbox']}\nFont: {item['font']}\nSize: {item['size']}\nRendering type: {item['type']}\n\nProperties are read-only."
        self.details.configure(state='normal'); self.details.delete('1.0', 'end'); self.details.insert('1.0', text); self.details.configure(state='disabled')
        self.draw_outline()

    def draw_outline(self):
        self.canvas.delete('outline')
        if not self.selection_box or not self.outlines.get() or not hasattr(self, 'scale'): return
        a,b,c,d,e,f = self.rotation
        x0,y0,x1,y1 = self.selection_box
        points = [(a*x+c*y+e, b*x+d*y+f) for x,y in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
        self.canvas.create_rectangle(10+min(x for x,y in points)*self.scale, 10+min(y for x,y in points)*self.scale, 10+max(x for x,y in points)*self.scale, 10+max(y for x,y in points)*self.scale, outline='#db3030', width=2, tags='outline')

    def selected_pages(self):
        if self.scope.get() == 'All pages': return None
        if self.scope.get() == 'Current page': return [self.page]
        pages = set()
        for part in self.page_range.get().split(','):
            bits = part.strip().split('-')
            if len(bits) > 2: raise ValueError('Use a range such as 1-3, 5.')
            start, end = int(bits[0]), int(bits[-1])
            if not 1 <= start <= end <= len(self.doc.plans): raise ValueError('Page range is outside this PDF.')
            pages.update(range(start-1, end))
        return sorted(pages)

    def repair(self):
        if not self.doc or self.busy: return
        try: pages = self.selected_pages()
        except ValueError as exc:
            messagebox.showerror('Page range', str(exc), parent=self); return
        def done(plans):
            self.update_pages(); self.view.set('Repaired'); self.render()
            changed = sum(p.state == 'Ready' for p in plans.values())
            skipped = [(i,p) for i,p in plans.items() if p.state == 'Skipped']
            messagebox.showinfo('Repair results', f'{changed} page(s) repaired. {len(skipped)} page(s) skipped.\n' + '\n'.join(f'Page {i+1}: {p.reason}' for i,p in skipped), parent=self)
        self.submit(lambda: self.doc.repair(pages), done, 'Reordering text and verifying geometry...')

    def undo(self):
        if self.doc and self.doc.history:
            self.submit(self.doc.undo, lambda _: (self.update_pages(), self.render()), 'Undoing repair...')

    def save(self):
        if not self.doc or self.busy: return
        path = filedialog.asksaveasfilename(defaultextension='.pdf', initialfile=self.doc.path.stem+'_text_front.pdf', filetypes=[('PDF documents', '*.pdf')])
        if path: self.submit(lambda: self.doc.save(path), lambda _: self.status.set(f'Saved verified copy: {path}'), 'Saving and verifying repaired PDF...')

    def close_app(self):
        if self.busy:
            self.status.set('Wait for the current operation to finish before closing.'); return
        if not self.discard_ok(): return
        if self.doc: self.doc.close()
        self.executor.shutdown(wait=False); self.destroy()


if __name__ == '__main__':
    app = App()
    if len(sys.argv) > 1: app.after(100, lambda: app.open_path(sys.argv[1]))
    app.mainloop()
