#!/usr/bin/env python3
"""Three-pane desktop interface for conservative PDF tag transfer."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import queue
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font
from PIL import Image, ImageTk
from transfer_core import Transfer, Document


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PDF Tag Transfer 0.1.1'); self.geometry('1700x980'); self.minsize(1100,700)
        self.session=None; self.output=None; self.running=False; self.busy=False; self.selected=None
        self.executor=ThreadPoolExecutor(max_workers=1); self.results=queue.Queue()
        self.temp=tempfile.TemporaryDirectory(prefix='pdf_tag_transfer_')
        self.photos=[]; self.page=tk.IntVar(value=1); self.zoom=tk.StringVar(value='Fit page')
        self.original=tk.StringVar(); self.source=tk.StringVar(); self.query=tk.StringVar()
        self.role=tk.StringVar(value='All tags'); self.state=tk.StringVar(value='All statuses')
        self.only_page=tk.BooleanVar(); self.alt=tk.BooleanVar(); self.status=tk.StringVar(value='Open the untagged original and the partially tagged reference.')
        self._build(); self.after(70,self.poll); self.protocol('WM_DELETE_WINDOW',self.close)

    def _build(self):
        style=ttk.Style(self)
        if 'vista' in style.theme_names(): style.theme_use('vista')
        elif 'clam' in style.theme_names(): style.theme_use('clam')
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont'): font.nametofont(name).configure(size=10)
        style.configure('Treeview',rowheight=25); style.configure('TButton',padding=(7,5))
        top=ttk.Frame(self,padding=10); top.pack(fill='x')
        for row,(label,var) in enumerate((('Original untagged PDF',self.original),('Partially tagged reference',self.source))):
            ttk.Label(top,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=3)
            ttk.Entry(top,textvariable=var).grid(row=row,column=1,sticky='ew')
            ttk.Button(top,text='Browse…',command=lambda v=var:self.browse(v)).grid(row=row,column=2,padx=6)
        top.columnconfigure(1,weight=1)
        actions=ttk.Frame(self,padding=(12,0,12,8)); actions.pack(fill='x')
        for text,command in [('Open / Analyze',self.open),('Start / Resume',self.start),('Pause',self.pause),('Step page',self.step),('Undo page',self.undo),('Save copy…',self.save)]:
            ttk.Button(actions,text=text,command=command).pack(side='left',padx=(0,6))
        ttk.Button(actions,text='Export report…',command=self.report).pack(side='right')
        panes=ttk.Panedwindow(self,orient='horizontal'); panes.pack(fill='both',expand=True,padx=12)
        left=ttk.Frame(panes,padding=6); views=ttk.Frame(panes); panes.add(left,weight=1); panes.add(views,weight=5)
        ttk.Label(left,text='Source structure / transfer status').pack(anchor='w')
        ttk.Entry(left,textvariable=self.query).pack(fill='x',pady=5)
        self.roles=ttk.Combobox(left,textvariable=self.role,state='readonly',values=['All tags']); self.roles.pack(fill='x')
        ttk.Combobox(left,textvariable=self.state,state='readonly',values=['All statuses','Transferred','Partial','Needs review','Pending','Empty container']).pack(fill='x',pady=5)
        ttk.Checkbutton(left,text='Current page only',variable=self.only_page,command=self.filter).pack(anchor='w')
        ttk.Checkbutton(left,text='Figures without alt text',variable=self.alt,command=self.filter).pack(anchor='w')
        frame=ttk.Frame(left); frame.pack(fill='both',expand=True,pady=6)
        self.tree=ttk.Treeview(frame,columns=('state',),selectmode='browse'); self.tree.heading('#0',text='Tag / title'); self.tree.heading('state',text='Status'); self.tree.column('#0',width=230); self.tree.column('state',width=100)
        bar=ttk.Scrollbar(frame,command=self.tree.yview); self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left',fill='both',expand=True); bar.pack(side='right',fill='y')
        self.tree.tag_configure('context',foreground='#777777'); self.tree.bind('<<TreeviewSelect>>',self.select)
        nav=ttk.Frame(views); nav.pack(fill='x',pady=5)
        ttk.Button(nav,text='◀',command=lambda:self.navigate(-1)).pack(side='left')
        ttk.Label(nav,text='Page').pack(side='left',padx=5)
        entry=ttk.Entry(nav,textvariable=self.page,width=6); entry.pack(side='left'); entry.bind('<Return>',lambda e:self.refresh())
        ttk.Button(nav,text='▶',command=lambda:self.navigate(1)).pack(side='left',padx=5)
        ttk.Label(nav,text='Linked navigation • scroll each preview independently').pack(side='left',padx=8)
        combo=ttk.Combobox(nav,textvariable=self.zoom,state='readonly',values=['Fit page','Fit width','75%','100%','150%','200%'],width=12); combo.pack(side='right'); combo.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        previews=ttk.Panedwindow(views,orient='horizontal'); previews.pack(fill='both',expand=True)
        self.canvases=[]
        for title in ('Original — matched content','Reference — selected tag','Output — applied content'):
            f=ttk.Frame(previews,padding=4); previews.add(f,weight=1); ttk.Label(f,text=title).pack(anchor='w',pady=5)
            holder=ttk.Frame(f); holder.pack(fill='both',expand=True)
            c=tk.Canvas(holder,background='#dfe3e7',highlightthickness=0)
            v=ttk.Scrollbar(holder,orient='vertical',command=c.yview); h=ttk.Scrollbar(holder,orient='horizontal',command=c.xview)
            c.configure(yscrollcommand=v.set,xscrollcommand=h.set); c.grid(row=0,column=0,sticky='nsew'); v.grid(row=0,column=1,sticky='ns'); h.grid(row=1,column=0,sticky='ew'); holder.rowconfigure(0,weight=1); holder.columnconfigure(0,weight=1)
            c.bind('<MouseWheel>',lambda e,cv=c:cv.yview_scroll(-1 if e.delta>0 else 1,'units'))
            c.bind('<Button-4>',lambda e,cv=c:cv.yview_scroll(-1,'units')); c.bind('<Button-5>',lambda e,cv=c:cv.yview_scroll(1,'units'))
            self.canvases.append(c)
        self.details=tk.Text(self,height=7,wrap='word',state='disabled'); self.details.pack(fill='x',padx=12,pady=6)
        self.progress=ttk.Progressbar(self); self.progress.pack(fill='x',padx=12)
        ttk.Label(self,textvariable=self.status,padding=10).pack(fill='x')
        for var in (self.query,self.role,self.state): var.trace_add('write',lambda *args:self.filter())

    def browse(self,var):
        path=filedialog.askopenfilename(filetypes=[('PDF','*.pdf')])
        if path: var.set(path)

    def job(self,fn,done):
        if self.busy: return False
        self.busy=True
        def work():
            try: self.results.put((done,fn(),None))
            except Exception as exc: self.results.put((done,None,exc))
        self.executor.submit(work); return True

    def poll(self):
        try:
            done,value,error=self.results.get_nowait(); self.busy=False
            if error:
                self.running=False; self.status.set(str(error)); messagebox.showerror('PDF Tag Transfer',str(error))
            else: done(value)
        except queue.Empty: pass
        self.after(70,self.poll)

    def open(self):
        if self.busy: return
        if self.session and not messagebox.askyesno('Replace session','Discard this session and open the selected PDFs?'): return
        original,source=self.original.get(),self.source.get()
        self.running=False; self.status.set('Opening and analyzing PDFs…')
        def load():
            candidate=Transfer(original,source)
            if self.output: self.output.close(); self.output=None
            if self.session: self.session.close()
            self.session=candidate
        def done(_):
            self.selected=None; self.page.set(1)
            self.roles.configure(values=['All tags']+sorted({t.role for t in self.session.reference.tags}))
            self.status.set(self.session.notice or 'Ready. Start or step through page transfers.')
            self.filter(); self.refresh()
        self.job(load,done)

    def tag_state(self,tag):
        refs=[r for t in self.session.reference.tags[tag.id:tag.end] for r in t.refs]
        if not refs: return 'Empty container'
        done=sum(not r.stream and r.mcid is not None and (r.page,r.mcid) in self.session.links for r in refs)
        if done==len(refs): return 'Transferred'
        if done: return 'Partial'
        if any(r.stream or r.mcid is None or r.page is None or self.session.states[r.page]=='Needs review' for r in refs): return 'Needs review'
        return 'Pending'

    def filter(self):
        if not self.session or self.busy: return
        tags=self.session.reference.tags
        try: page=self.page.get()-1
        except tk.TclError: return
        matches={t.id for t in tags if t.matches(self.query.get(),self.role.get(),page if self.only_page.get() else None,self.alt.get()) and (self.state.get()=='All statuses' or self.tag_state(t)==self.state.get())}
        visible=set(matches)
        for idx in list(matches):
            parent=tags[idx].parent
            while parent is not None: visible.add(parent); parent=tags[parent].parent
        self.tree.delete(*self.tree.get_children())
        for t in tags:
            if t.id in visible:
                self.tree.insert('' if t.parent is None else str(t.parent),'end',iid=str(t.id),text=f'{t.role} {t.title or t.alt[:40]}',values=(self.tag_state(t),),tags=() if t.id in matches else ('context',),open=True)

    def select(self,event=None):
        if self.busy or not self.tree.selection(): return
        self.selected=int(self.tree.selection()[0]); tag=self.session.reference.tags[self.selected]
        if tag.pages: self.page.set(min(tag.pages)+1)
        self.refresh()

    def navigate(self,delta):
        if not self.session or self.busy: return
        self.page.set(max(1,min(len(self.session.pdf.pages),self.page.get()+delta))); self.refresh()

    def refresh(self):
        if not self.session or self.busy: return
        try: page=self.page.get()-1
        except tk.TclError: return
        if not 0<=page<len(self.session.pdf.pages): return
        sizes=[(max(c.winfo_width()-12,100),max(c.winfo_height()-12,100)) for c in self.canvases]
        selected=self.selected; zoom=self.zoom.get()
        def render():
            if self.output: self.output.close()
            path=Path(self.temp.name)/'preview.pdf'; path.write_bytes(self.session.snapshot()); self.output=Document(path)
            frames=[]
            for i,doc in enumerate((self.session.base,self.session.reference,self.output)):
                p=doc.render_doc[page]; w,h=sizes[i]
                scale=min(w/p.rect.width,h/p.rect.height) if zoom=='Fit page' else w/p.rect.width if zoom=='Fit width' else float(zoom[:-1])/100
                width,height,pixels,scale=doc.render(page,scale)
                boxes=[]
                if selected is not None:
                    if i==1: boxes=self.session.reference.selection(selected,page)[0]
                    elif i==2: boxes=doc.selection(selected,page)[0]
                    else:
                        try: self.session.analyze_page(page); boxes=self.session.reference.selection(selected,page)[0]
                        except ValueError: pass
                applied=[]
                if i==2:
                    for t in doc.tags:
                        if t.refs: applied.extend(doc.selection(t.id,page)[0])
                frames.append((width,height,pixels,scale,boxes,applied))
            return frames
        def drawn(frames):
            self.photos=[]
            for i,(c,(w,h,pixels,scale,boxes,applied)) in enumerate(zip(self.canvases,frames)):
                photo=ImageTk.PhotoImage(Image.frombytes('RGB',(w,h),pixels)); self.photos.append(photo)
                c.delete('all'); c.create_image(5,5,image=photo,anchor='nw'); c.configure(scrollregion=(0,0,w+10,h+10))
                # Green outlines show all transferred regions on the output page.
                if i==2:
                    for box in applied: c.create_rectangle(*(5+v*scale for v in box),outline='#16834b',width=1)
                for box in boxes: c.create_rectangle(*(5+v*scale for v in box),outline='#086bc1',width=3)
            self.details.configure(state='normal'); self.details.delete('1.0','end')
            s=self.session
            text=f'Page {page+1}: {s.states[page]} — {s.messages[page]}\n'
            if selected is not None:
                t=s.reference.tags[selected]; text+=f'{t.path}\nStatus: {self.tag_state(t)}\nAlt: {t.alt}\nActual text: {t.actual_text}\nLanguage: {t.inherited_language}\nAttributes: {t.attributes}'
            self.details.insert('end',text); self.details.configure(state='disabled')
            self.progress.configure(maximum=len(s.states),value=sum(v!='Pending' for v in s.states))
            if self.running: self.after(100,self.step)
        self.job(render,drawn)

    def start(self):
        if self.session and not self.busy: self.running=True; self.step()
    def pause(self): self.running=False; self.status.set('Paused after the current operation.')
    def step(self):
        if not self.session or self.busy: return
        def done(page):
            if page is None: self.running=False; self.status.set('Transfer finished. Review unresolved items before saving.')
            else:
                self.page.set(page+1); self.status.set(f'Page {page+1}: {self.session.states[page]} — {self.session.messages[page]}')
            self.filter(); self.refresh()
        self.job(self.session.step,done)
    def undo(self):
        if self.session and not self.busy:
            self.running=False
            self.job(self.session.undo,lambda _: (self.filter(),self.refresh()))
    def save(self):
        if not self.session or self.busy: return
        self.running=False
        count=len(self.session.unresolved())
        if (count or 'Pending' in self.session.states) and not messagebox.askyesno('Save partial result',f'{count} source content references remain unresolved. Save this partial result?'): return
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
        if path: self.job(lambda:self.session.save(path),lambda _:self.status.set(f'Saved and checked appearance/text: {path}. Continued tagging still requires testing in your editor.'))
    def report(self):
        if not self.session or self.busy:return
        import json
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            s=self.session
            import os
            target=Path(path).resolve()
            if target.suffix.lower() != '.json' or any(target == p or (target.exists() and os.path.samefile(target,p)) for p in (s.original,s.source)):
                messagebox.showerror('Report path','Choose a separate .json report file.'); return
            Path(path).write_text(json.dumps({'original':str(s.original),'reference':str(s.source),'notice':s.notice,'pages':[{'page':i+1,'status':v,'detail':s.messages[i]} for i,v in enumerate(s.states)],'unresolved':[{'tag':i,'page':r.page+1 if r.page is not None else None,'mcid':r.mcid,'stream':r.stream} for i,r in s.unresolved()]},indent=2),encoding='utf-8')
    def close(self):
        if self.busy: self.running=False; self.status.set('Wait for the current operation before closing.'); return
        if self.session and not messagebox.askyesno('Close','Close this session? Save any wanted output first.'):return
        self.executor.shutdown(wait=False)
        if self.output:self.output.close()
        if self.session:self.session.close()
        self.temp.cleanup(); self.destroy()

if __name__=='__main__': App().mainloop()
