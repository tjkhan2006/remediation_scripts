"""Small local launcher for the read-only analyzer."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser


def main():
    window = tk.Tk()
    window.title('PDF Tag Link Diagnostic')
    window.geometry('750x340')
    source, destination = tk.StringVar(), tk.StringVar()
    full_report, all_objects = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    status = tk.StringVar(value='Choose a PDF and report folder. The PDF is opened for analysis only.')
    def choose_source(): source.set(filedialog.askopenfilename(filetypes=[('PDF documents', '*.pdf')]) or source.get())
    def choose_destination(): destination.set(filedialog.askdirectory() or destination.get())
    tk.Label(window, text='PDF to inspect').pack(anchor='w', padx=16, pady=(16, 0))
    tk.Entry(window, textvariable=source, width=100).pack(padx=16, fill='x')
    tk.Button(window, text='Choose PDF…', command=choose_source).pack(anchor='w', padx=16)
    tk.Label(window, text='Save reports in').pack(anchor='w', padx=16)
    tk.Entry(window, textvariable=destination, width=100).pack(padx=16, fill='x')
    tk.Button(window, text='Choose report folder…', command=choose_destination).pack(anchor='w', padx=16)
    tk.Checkbutton(window, text='Export full document HTML report (JSON and JSONL are always exported)', variable=full_report).pack(anchor='w', padx=16)
    tk.Checkbutton(window, text='Fingerprint all current indirect objects for before/after comparison', variable=all_objects).pack(anchor='w', padx=16)
    def run():
        path, folder = Path(source.get()), Path(destination.get())
        if not source.get() or not path.is_file() or not destination.get() or not folder.is_dir():
            messagebox.showerror('Choose files', 'Choose an existing PDF and report folder.')
            return
        output = folder/('audit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        output.mkdir(exist_ok=False)
        args = [sys.executable, str(Path(__file__).with_name('diagnostic.py')), 'audit', str(path),
                '--out', str(output/'audit.json'), '--jsonl', str(output/'events.jsonl')]
        if full_report.get(): args += ['--html', str(output/'report.html')]
        if all_objects.get(): args += ['--objects']
        button.config(state='disabled')
        status.set('Analyzing all pages. Reports can take a few minutes for large structure trees.')
        def finish(proc):
            button.config(state='normal')
            if proc.returncode:
                status.set('Analysis failed. Review console.txt in the report folder.')
                messagebox.showerror('Analysis failed', proc.stderr[-1500:])
            else:
                data = json.loads((output/'audit.json').read_text())
                status.set(f"Done: {data['summary']['pages']} pages, {data['summary']['reachable_tags']} reachable tags. Saved in {output}")
                if (output/'report.html').exists(): webbrowser.open((output/'report.html').as_uri())
        def worker():
            try:
                proc = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
                (output/'console.txt').write_text(proc.stdout+'\n'+proc.stderr, encoding='utf-8')
            except Exception as e:
                proc = subprocess.CompletedProcess(args, 1, '', str(e))
            window.after(0, lambda: finish(proc))
        threading.Thread(target=worker, daemon=True).start()
    button = tk.Button(window, text='Analyze PDF', command=run)
    button.pack(anchor='w', padx=16, pady=8)
    tk.Label(window, textvariable=status, wraplength=710, justify='left').pack(anchor='w', padx=16)
    window.mainloop()

if __name__ == '__main__': main()
