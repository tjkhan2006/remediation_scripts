#!/usr/bin/env python3
"""GUI for inserting consecutive empty, text-property, or content-linked PDF tags."""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
try:
    import pikepdf
    from PIL import Image, ImageTk
    from inserter_core import Editor
    from tree_filter import filter_tree
except ImportError as error:
    root=tk.Tk(); root.withdraw()
    messagebox.showerror('Install dependencies',f'{error}\n\nRun: python -m pip install -r requirements.txt')
    raise SystemExit(1)

ROLES='Document Part Sect Div P H H1 H2 H3 H4 H5 H6 L LI Lbl LBody Table TR TH TD THead TBody TFoot Span Quote Note Reference BibEntry Code Link Annot Figure Formula Form'.split()
POSITIONS=['Before selected','After selected','First children','Last children','At child position']
MODES=['Empty tags','Text properties','Existing page content']

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PDF Tag Inserter')
        self.geometry('1500x940'); self.minsize(1120,800)
        self.editor=None; self.sources=[]; self.batch=[]; self.photo=None
        self.busy=False; self.results=queue.Queue(); self.pool=ThreadPoolExecutor(max_workers=1)
        self.tree_query=tk.StringVar(); self.tree_role=tk.StringVar(value='All tags')
        self.tree_count=tk.StringVar(value='No PDF open'); self.filter_job=None; self.highlighted=()
        self.path=tk.StringVar(); self.role=tk.StringVar(value='P'); self.count=tk.StringVar(value='1')
        self.mode=tk.StringVar(value=MODES[0]); self.position=tk.StringVar(value='Last children')
        self.child_index=tk.StringVar(value='1'); self.page=tk.StringVar(value='1')
        self.status=tk.StringVar(value='Open a PDF, select a location in the full tag tree, then insert a batch.')
        self.target=tk.StringVar(value='Insertion target: structure tree root')
        self.batch_label=tk.StringVar(value='Content batch: 0 items')
        self._build()
        self.bind('<Control-o>',lambda e:self.open_pdf())
        self.bind('<Control-s>',lambda e:self.save())
        self.tree_query.trace_add('write',self.schedule_tree_filter)
        self.tree_role.trace_add('write',self.schedule_tree_filter)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(60,self.poll)

    def _build(self):
        style=ttk.Style()
        if 'vista' in style.theme_names(): style.theme_use('vista')
        elif 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('Treeview',rowheight=24)
        top=ttk.Frame(self,padding=10); top.pack(fill='x')
        ttk.Label(top,text='PDF').pack(side='left',padx=(0,8))
        ttk.Entry(top,textvariable=self.path).pack(side='left',fill='x',expand=True)
        self.button(top,'Browse / Open...',self.open_pdf).pack(side='left',padx=6)
        self.button(top,'Save PDF copy...',self.save).pack(side='left')
        panes=ttk.Panedwindow(self,orient='horizontal'); panes.pack(fill='both',expand=True,padx=10)
        left=ttk.Frame(panes,padding=8,width=430); center=ttk.Frame(panes,padding=8,width=590); right=ttk.Frame(panes,padding=8,width=360)
        panes.add(left,weight=3); panes.add(center,weight=4); panes.add(right,weight=2)
        ttk.Label(left,text='FULL TAG TREE',font=('TkDefaultFont',11,'bold')).pack(anchor='w',pady=(0,8))
        filters=ttk.Frame(left); filters.pack(fill='x',pady=(0,6))
        ttk.Label(filters,text='Search tags / properties').pack(anchor='w')
        ttk.Entry(filters,textvariable=self.tree_query).pack(fill='x',pady=(2,5))
        row=ttk.Frame(filters); row.pack(fill='x')
        self.tree_role_combo=ttk.Combobox(row,textvariable=self.tree_role,values=['All tags'],state='readonly',width=18)
        self.tree_role_combo.pack(side='left',fill='x',expand=True)
        self.button(row,'Clear filters',self.clear_tree_filters).pack(side='left',padx=(5,0))
        ttk.Label(filters,textvariable=self.tree_count).pack(anchor='w',pady=(5,0))
        toolbar=ttk.Frame(left); toolbar.pack(fill='x',pady=(0,6))
        self.button(toolbar,'Expand all',lambda:self.expand(True)).pack(side='left')
        self.button(toolbar,'Collapse all',lambda:self.expand(False)).pack(side='left',padx=4)
        tf=ttk.Frame(left); tf.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(tf,columns=('page',),selectmode='browse')
        self.tree.heading('#0',text='Tags and content references'); self.tree.column('#0',width=300,minwidth=180)
        self.tree.heading('page',text='Page'); self.tree.column('page',width=55,stretch=False)
        vs=ttk.Scrollbar(tf,orient='vertical',command=self.tree.yview); hs=ttk.Scrollbar(tf,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        self.tree.grid(row=0,column=0,sticky='nsew'); vs.grid(row=0,column=1,sticky='ns'); hs.grid(row=1,column=0,sticky='ew')
        tf.rowconfigure(0,weight=1); tf.columnconfigure(0,weight=1)
        self.tree.tag_configure('new',foreground='#087532'); self.tree.tag_configure('content',foreground='#666666'); self.tree.tag_configure('context',foreground='#888888')
        self.tree.bind('<<TreeviewSelect>>',self.selected)
        ttk.Label(left,text='Select any tag or content reference as your insertion anchor. New tags appear in green.',wraplength=400).pack(fill='x',pady=8)
        ttk.Label(center,text='PAGE CONTENT AND PREVIEW',font=('TkDefaultFont',11,'bold')).pack(anchor='w',pady=(0,8))
        nav=ttk.Frame(center); nav.pack(fill='x')
        ttk.Label(nav,text='PDF page').pack(side='left')
        self.page_combo=ttk.Combobox(nav,textvariable=self.page,state='readonly',width=7,values=['1']); self.page_combo.pack(side='left',padx=6)
        self.button(nav,'Scan / show page',self.scan).pack(side='left')
        self.source_list=tk.Listbox(center,selectmode='extended',exportselection=False,height=7)
        self.source_list.pack(fill='x',pady=6)
        self.source_list.bind('<<ListboxSelect>>',lambda e:self.draw())
        self.button(center,'Add selected content to batch',self.add_sources).pack(anchor='w')
        self.canvas=tk.Canvas(center,bg='#dce1e6',highlightthickness=0,height=360)
        self.canvas.pack(fill='both',expand=True,pady=8)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        ttk.Label(center,textvariable=self.batch_label).pack(anchor='w')
        self.batch_list=tk.Listbox(center,selectmode='browse',exportselection=False,height=5)
        self.batch_list.pack(fill='x',pady=4)
        row=ttk.Frame(center); row.pack(fill='x')
        for label,cmd in [('Move up',lambda:self.move(-1)),('Move down',lambda:self.move(1)),('Remove',self.remove),('Clear batch',self.clear_batch)]:
            self.button(row,label,cmd).pack(side='left',padx=(0,4))
        ttk.Label(center,text='One new tag per content item, in batch order. Existing content references move; the page artwork stays the same.',wraplength=550).pack(fill='x',pady=6)
        ttk.Label(right,text='INSERT CONSECUTIVE TAGS',font=('TkDefaultFont',11,'bold')).pack(anchor='w',pady=(0,8))
        ttk.Label(right,textvariable=self.target,wraplength=320).pack(fill='x',pady=(0,8))
        self.combo(right,'Placement',self.position,POSITIONS)
        row=ttk.Frame(right); row.pack(fill='x',pady=4)
        ttk.Label(row,text='Child position (1-based)').pack(side='left')
        ttk.Entry(row,textvariable=self.child_index,width=6).pack(side='right')
        self.combo(right,'Tag type',self.role,ROLES,readonly=False)
        self.combo(right,'Populate with',self.mode,MODES)
        self.mode.trace_add('write',lambda *_:self.mode_changed())
        row=ttk.Frame(right); row.pack(fill='x',pady=8)
        ttk.Label(row,text='Number of tags').pack(side='left')
        self.count_entry=ttk.Entry(row,textvariable=self.count,width=9); self.count_entry.pack(side='right')
        ttk.Label(right,text='Empty/text mode: any positive count. Content mode: count follows the batch.',wraplength=320).pack(fill='x')
        self.fields={}
        for key,label,height in [('title','Title',1),('alt','Alternate text',3),('actual','Actual text',3),('language','Language',1),('expansion','Expansion text',2)]:
            ttk.Label(right,text=label).pack(anchor='w',pady=(5,2))
            w=ttk.Entry(right,width=30) if height==1 else tk.Text(right,width=30,height=height,wrap='word')
            w.pack(fill='x'); self.fields[key]=w
        ttk.Label(right,text='Properties repeat for each tag. Use {n} to number them (1, 2, 3...). Text properties do not add visible page text.',wraplength=320).pack(fill='x',pady=6)
        self.button(right,'Insert batch at selected location',self.insert).pack(fill='x',pady=(8,4))
        self.button(right,'Undo last insertion',self.undo).pack(fill='x',pady=4)
        ttk.Label(self,textvariable=self.status,relief='sunken',padding=8,anchor='w').pack(fill='x',pady=(6,0))
        self.rebuild()
        self.mode_changed()

    def button(self,parent,text,command):
        return ttk.Button(parent,text=text,command=command)

    def combo(self,parent,label,var,values,readonly=True):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(5,2))
        w=ttk.Combobox(parent,textvariable=var,values=values,state='readonly' if readonly else 'normal',width=30)
        w.pack(fill='x'); return w

    def mode_changed(self):
        state='disabled' if self.mode.get()=='Empty tags' else 'normal'
        for w in self.fields.values(): w.configure(state=state)
        is_content=self.mode.get()=='Existing page content'
        self.count_entry.configure(state='readonly' if is_content else 'normal')
        if is_content: self.count.set(str(len(self.batch)))
        elif self.count.get()=='0': self.count.set('1')

    def submit(self,fn,done,label,error=None):
        if self.busy: return
        self.busy=True; self.status.set(label); self.configure(cursor='watch')
        def disable(w):
            for c in w.winfo_children():
                if isinstance(c,ttk.Button): c.state(['disabled'])
                disable(c)
        disable(self)
        f=self.pool.submit(fn); f.add_done_callback(lambda f:self.results.put((f,done,error)))

    def poll(self):
        try:
            while True:
                f,done,error=self.results.get_nowait(); self.busy=False; self.configure(cursor='')
                def enable(w):
                    for c in w.winfo_children():
                        if isinstance(c,ttk.Button): c.state(['!disabled'])
                        enable(c)
                enable(self)
                try: result=f.result()
                except Exception as exc:
                    self.status.set(str(exc))
                    if error: error(exc)
                    else: messagebox.showerror('PDF Tag Inserter',str(exc),parent=self)
                else: done(result)
        except queue.Empty: pass
        self.after(60,self.poll)

    def open_pdf(self,path=None,password='',retry=False):
        if self.busy: return
        if not retry and self.editor and self.editor.dirty and not messagebox.askyesno('Unsaved insertions','Discard unsaved insertions and open another PDF?',parent=self): return
        path=path or filedialog.askopenfilename(filetypes=[('PDF files','*.pdf')])
        if not path: return
        def failed(exc):
            if isinstance(exc,pikepdf.PasswordError):
                value=simpledialog.askstring('PDF password','Enter the PDF password:',show='*',parent=self)
                if value is not None: self.open_pdf(path,value,True)
            else: messagebox.showerror('Cannot open PDF',str(exc),parent=self)
        def loaded(editor):
            old=self.editor; self.editor=editor
            if old: old.close()
            self.path.set(str(editor.path)); self.page.set('1')
            self.page_combo.configure(values=[str(i+1) for i in range(len(editor.pdf.pages))])
            self.tree_query.set(''); self.tree_role.set('All tags')
            self.sources=[]; self.batch=[]; self.photo=None; self.preview_data=None
            self.source_list.delete(0,'end'); self.refresh_batch(); self.rebuild()
            self.status.set('Select an insertion anchor in the full tag tree. Scan a page to choose visible content.')
            self.scan()
        self.submit(lambda:Editor(path,password),loaded,'Reading the full tag tree...',failed)

    def schedule_tree_filter(self,*_):
        if self.filter_job: self.after_cancel(self.filter_job)
        self.filter_job=self.after(180,self.apply_tree_filter)

    def apply_tree_filter(self):
        self.filter_job=None
        if self.busy:
            self.filter_job=self.after(180,self.apply_tree_filter)
            return
        self.rebuild(self.highlighted,preserve_selection=True)

    def clear_tree_filters(self):
        self.tree_query.set(''); self.tree_role.set('All tags')
        self.schedule_tree_filter()

    def rebuild(self,new_keys=(),preserve_selection=False):
        old=self.tree.selection()
        self.highlighted=tuple(new_keys)
        self.tree.delete(*self.tree.get_children())
        self.tree.insert('','end',iid='root',text='Structure tree root',open=True)
        if self.editor:
            roles=sorted({str(self.editor.nodes[k].obj.S).lstrip('/') for k in self.editor.order if self.editor.nodes[k].structure})
            self.tree_role_combo.configure(values=['All tags']+roles)
            matches,visible=filter_tree(self.editor,self.tree_query.get(),self.tree_role.get())
            active=bool(self.tree_query.get().strip() or self.tree_role.get()!='All tags')
            for key in self.editor.order:
                if key not in visible: continue
                n=self.editor.nodes[key]
                tags=('new',) if key in new_keys else ('context',) if active and key not in matches else ('content',) if not n.structure else ()
                self.tree.insert(self.editor.parents[key],'end',iid=key,text=n.label,values=(n.page+1 if n.page is not None else '-',),open=True,tags=tags)
            self.tree_count.set(f'{len(matches)} matches | {len(visible)-1} of {len(self.editor.order)} items shown' if active else f'{len(self.editor.order)} tree items')
        target=old[0] if preserve_selection and old and self.tree.exists(old[0]) else next((k for k in new_keys if self.tree.exists(k)),'root')
        self.tree.selection_set(target)
        self.selected()
        if target!='root': self.tree.see(target)

    def selected(self,_event=None):
        choices=self.tree.selection()
        if choices: self.target.set('Insertion anchor: '+self.tree.item(choices[0],'text'))

    def expand(self,opened):
        if self.editor:
            for key in self.editor.order:
                if self.tree.exists(key): self.tree.item(key,open=opened)
        self.tree.item('root',open=True)

    def scan(self):
        if not self.editor or self.busy: return
        page_no=int(self.page.get())-1
        editor=self.editor
        def work():
            sources=editor.scan_content(page_no)
            pix=editor.renderer[page_no].get_pixmap(matrix=__import__('pymupdf').Matrix(1.2,1.2),alpha=False)
            return sources,(pix.width,pix.height,pix.samples),page_no
        def done(result):
            self.sources,self.preview_data,self.preview_page=result
            self.source_list.delete(0,'end')
            for c in self.sources: self.source_list.insert('end',c.label)
            self.draw()
            self.status.set(f'Page {page_no+1}: {len(self.sources)} selectable content items. Ctrl/Shift-click to select several, then add them to the batch.')
        self.submit(work,done,f'Scanning content on page {page_no+1}...')

    def draw(self):
        if not getattr(self,'preview_data',None): return
        w,h,data=self.preview_data
        cw,ch=max(100,self.canvas.winfo_width()),max(100,self.canvas.winfo_height())
        scale=min((cw-20)/w,(ch-20)/h)
        nw,nh=max(1,int(w*scale)),max(1,int(h*scale))
        self.photo=ImageTk.PhotoImage(Image.frombytes('RGB',(w,h),data).resize((nw,nh),Image.Resampling.LANCZOS))
        x,y=(cw-nw)/2,(ch-nh)/2
        self.canvas.delete('all'); self.canvas.create_image(x,y,image=self.photo,anchor='nw')
        if self.editor:
            page=self.editor.renderer[self.preview_page]
            sx,sy=nw/page.rect.width,nh/page.rect.height
            for i in self.source_list.curselection():
                c=self.sources[i]
                if c.bounds:
                    a,b,d,e=c.bounds
                    self.canvas.create_rectangle(x+a*sx,y+b*sy,x+d*sx,y+e*sy,outline='#df2338',width=2)

    def add_sources(self):
        if self.busy: return
        known={(c.page,c.stream,c.mcid) for c in self.batch}
        for i in self.source_list.curselection():
            c=self.sources[i]; key=(c.page,c.stream,c.mcid)
            if key not in known: self.batch.append(c); known.add(key)
        self.mode.set('Existing page content'); self.refresh_batch()

    def refresh_batch(self):
        self.batch_list.delete(0,'end')
        for i,c in enumerate(self.batch): self.batch_list.insert('end',f'{i+1}. Page {c.page+1}: {c.label}')
        self.batch_label.set(f'Content batch: {len(self.batch)} items (in insertion order)')
        if self.mode.get()=='Existing page content': self.count.set(str(len(self.batch)))

    def move(self,direction):
        if self.busy: return
        chosen=self.batch_list.curselection()
        if chosen:
            i=chosen[0]; j=i+direction
            if 0<=j<len(self.batch):
                self.batch[i],self.batch[j]=self.batch[j],self.batch[i]
                self.refresh_batch(); self.batch_list.selection_set(j)

    def remove(self):
        if not self.busy and self.batch_list.curselection():
            del self.batch[self.batch_list.curselection()[0]]; self.refresh_batch()

    def clear_batch(self):
        if not self.busy: self.batch=[]; self.refresh_batch()

    def insert(self):
        if self.busy or not self.editor: return
        try:
            count=int(self.count.get()); child=int(self.child_index.get()) if self.position.get()=='At child position' else 1
            if count<1: raise ValueError()
        except ValueError:
            messagebox.showerror('Invalid count','Enter a positive whole number, or add content items to the batch.',parent=self); return
        selected=self.tree.selection()
        if not selected: return
        props={} if self.mode.get()=='Empty tags' else {k:w.get('1.0','end-1c') if isinstance(w,tk.Text) else w.get() for k,w in self.fields.items()}
        sources=list(self.batch) if self.mode.get()=='Existing page content' else []
        if self.mode.get()=='Existing page content' and not sources: return
        role=self.role.get(); position=self.position.get(); version=self.editor.version
        def done(keys):
            self.tree_query.set(''); self.tree_role.set('All tags')
            self.sources=[]; self.batch=[]; self.source_list.delete(0,'end'); self.refresh_batch(); self.rebuild(keys)
            self.status.set(f'Inserted {len(keys)} consecutive /{role} tags. Review the green rows, then save a PDF copy.')
        self.submit(lambda:self.editor.insert(selected[0],position,count,role,props,sources,child,version),done,f'Inserting {count} consecutive tags...')

    def undo(self):
        if not self.editor or self.busy or not self.editor.undo_data: return
        def done(_):
            self.sources=[]; self.batch=[]; self.source_list.delete(0,'end'); self.refresh_batch(); self.rebuild()
            self.status.set('Last insertion undone. Rescan the page to choose content again.')
        self.submit(self.editor.undo,done,'Undoing insertion...')

    def save(self):
        if not self.editor or self.busy: return
        path=filedialog.asksaveasfilename(defaultextension='.pdf',initialfile=self.editor.path.stem+'_inserted.pdf',filetypes=[('PDF files','*.pdf')])
        if path: self.submit(lambda:self.editor.save(path),lambda _:self.status.set('Saved PDF copy: '+path),'Saving and verifying PDF copy...')

    def close(self):
        if self.busy: self.status.set('Please wait for the current operation to finish.'); return
        if self.editor and self.editor.dirty and not messagebox.askyesno('Unsaved insertions','Close and discard unsaved insertions?',parent=self): return
        if self.editor: self.editor.close()
        self.pool.shutdown(wait=False); self.destroy()

if __name__=='__main__':
    app=App()
    if len(sys.argv)>1: app.after(100,lambda:app.open_pdf(sys.argv[1]))
    app.mainloop()
