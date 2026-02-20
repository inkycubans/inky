"""
Gratis Avinstallerare - ett alternativ till Revo Uninstaller
Kräver Python 3.6+ på Windows. Kör som administratör för bästa resultat.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import sys
import shutil
import re

# Windows-specifika moduler – importeras säkert
try:
    import winreg
    WINDOWS = True
except ImportError:
    WINDOWS = False


# ---------------------------------------------------------------------------
# Registerfunktioner
# ---------------------------------------------------------------------------

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
] if WINDOWS else []


def get_installed_programs():
    """Hämtar lista med installerade program från registret."""
    programs = []
    if not WINDOWS:
        return programs

    for hive, key_path in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue

        i = 0
        while True:
            try:
                sub_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                sub = winreg.OpenKey(key, sub_name)
                name = _reg_val(sub, "DisplayName")
                if not name:
                    winreg.CloseKey(sub)
                    continue
                programs.append({
                    "name":      name,
                    "version":   _reg_val(sub, "DisplayVersion") or "",
                    "publisher": _reg_val(sub, "Publisher") or "",
                    "uninstall": _reg_val(sub, "UninstallString") or "",
                    "quiet":     _reg_val(sub, "QuietUninstallString") or "",
                    "key_path":  key_path + "\\" + sub_name,
                    "hive":      hive,
                })
                winreg.CloseKey(sub)
            except OSError:
                pass

        winreg.CloseKey(key)

    programs.sort(key=lambda p: p["name"].lower())
    return programs


def _reg_val(key, name):
    """Läser ett registervärde säkert."""
    try:
        val, _ = winreg.QueryValueEx(key, name)
        return str(val).strip()
    except OSError:
        return None


def find_leftover_registry_keys(program_name):
    """Söker efter kvarlämnade registerposter för ett program."""
    if not WINDOWS:
        return []

    words = [w for w in re.split(r"\W+", program_name) if len(w) > 3]
    found = []

    search_roots = [
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node"),
    ]

    for hive, root_path in search_roots:
        try:
            root = winreg.OpenKey(hive, root_path)
        except OSError:
            continue

        j = 0
        while True:
            try:
                sub_name = winreg.EnumKey(root, j)
                j += 1
            except OSError:
                break
            if any(w.lower() in sub_name.lower() for w in words):
                hive_name = "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"
                found.append(f"{hive_name}\\{root_path}\\{sub_name}")

        winreg.CloseKey(root)

    return found


def delete_registry_key(path):
    """Raderar en registernyckel (rekursivt)."""
    if not WINDOWS:
        return False
    hive_name, _, sub = path.partition("\\")
    hive = winreg.HKEY_CURRENT_USER if hive_name == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    parent, _, child = sub.rpartition("\\")
    try:
        key = winreg.OpenKey(hive, parent, 0, winreg.KEY_ALL_ACCESS)
        winreg.DeleteKey(key, child)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Filsystemfunktioner
# ---------------------------------------------------------------------------

SEARCH_DIRS = [
    os.environ.get("APPDATA", ""),
    os.environ.get("LOCALAPPDATA", ""),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Low"),
    os.environ.get("PROGRAMDATA", ""),
    os.environ.get("PROGRAMFILES", ""),
    os.environ.get("PROGRAMFILES(X86)", ""),
    os.path.join(os.environ.get("USERPROFILE", ""), "AppData"),
    os.path.join(os.environ.get("USERPROFILE", ""), "Documents"),
]


def find_leftover_files(program_name):
    """Söker efter kvarlämnade filer och mappar för ett program."""
    words = [w for w in re.split(r"\W+", program_name) if len(w) > 3]
    found = []

    for base in SEARCH_DIRS:
        if not base or not os.path.isdir(base):
            continue
        try:
            for entry in os.scandir(base):
                if any(w.lower() in entry.name.lower() for w in words):
                    found.append(entry.path)
        except PermissionError:
            pass

    return found


def delete_path(path):
    """Raderar en fil eller mapp."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Avinstallation
# ---------------------------------------------------------------------------

def run_uninstaller(program, quiet=False):
    """Kör programmets egna avinstallerare."""
    cmd = program["quiet"] if quiet and program["quiet"] else program["uninstall"]
    if not cmd:
        return False, "Ingen avinstallationssträng hittades."

    # msiexec kräver /x istället för vanlig körning
    if cmd.strip().lower().startswith("msiexec"):
        if "/x" not in cmd.lower() and "/i" not in cmd.lower():
            cmd = cmd.replace("msiexec", "msiexec /x", 1)

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        return True, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Avinstallationen tog för lång tid."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class UninstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gratis Avinstallerare")
        self.geometry("950x680")
        self.minsize(750, 500)
        self.configure(bg="#f0f0f0")

        self.programs = []
        self.filtered = []
        self._build_ui()
        self._load_programs()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        # --- Rubrik ---
        header = tk.Frame(self, bg="#2d6a9f", pady=8)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="Gratis Avinstallerare",
            font=("Segoe UI", 16, "bold"), fg="white", bg="#2d6a9f"
        ).pack(side=tk.LEFT, padx=16)
        tk.Label(
            header, text="Ta bort program och alla deras kvarlämningar",
            font=("Segoe UI", 10), fg="#cce0f5", bg="#2d6a9f"
        ).pack(side=tk.LEFT, padx=4)

        # --- Sökfält ---
        search_frame = tk.Frame(self, bg="#f0f0f0", pady=6)
        search_frame.pack(fill=tk.X, padx=12)
        tk.Label(search_frame, text="Sök:", bg="#f0f0f0", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40, font=("Segoe UI", 10))
        search_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(search_frame, text="Rensa", command=lambda: self.search_var.set("")).pack(side=tk.LEFT)

        self.count_label = tk.Label(search_frame, text="", bg="#f0f0f0", font=("Segoe UI", 9), fg="#555")
        self.count_label.pack(side=tk.RIGHT, padx=8)

        # --- Programlista ---
        list_frame = tk.Frame(self, bg="#f0f0f0")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        columns = ("name", "version", "publisher")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name",      text="Programnamn",  command=lambda: self._sort("name"))
        self.tree.heading("version",   text="Version",      command=lambda: self._sort("version"))
        self.tree.heading("publisher", text="Utgivare",     command=lambda: self._sort("publisher"))
        self.tree.column("name",      width=380, minwidth=200)
        self.tree.column("version",   width=120, minwidth=80)
        self.tree.column("publisher", width=260, minwidth=120)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._start_uninstall())

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Knappar ---
        btn_frame = tk.Frame(self, bg="#f0f0f0", pady=6)
        btn_frame.pack(fill=tk.X, padx=12)

        self.uninstall_btn = ttk.Button(
            btn_frame, text="Avinstallera valt program",
            command=self._start_uninstall, state=tk.DISABLED
        )
        self.uninstall_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.quiet_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            btn_frame, text="Tyst avinstallation (om möjligt)",
            variable=self.quiet_var
        ).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Button(btn_frame, text="Uppdatera lista", command=self._load_programs).pack(side=tk.LEFT)

        self.status_label = tk.Label(btn_frame, text="", bg="#f0f0f0", font=("Segoe UI", 9), fg="#444")
        self.status_label.pack(side=tk.RIGHT, padx=8)

        # --- Logg ---
        log_label = tk.Label(self, text="Logg:", anchor="w", bg="#f0f0f0", font=("Segoe UI", 9, "bold"))
        log_label.pack(fill=tk.X, padx=12)

        self.log = scrolledtext.ScrolledText(
            self, height=8, state=tk.DISABLED, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.log.pack(fill=tk.X, padx=12, pady=(0, 8))

        # --- Kvarlämningar ---
        self.leftovers_frame = tk.LabelFrame(
            self, text="Kvarlämnade filer och registerposter",
            bg="#f0f0f0", font=("Segoe UI", 9, "bold"), fg="#333"
        )
        # (visas dynamiskt efter avinstallation)

    # ------------------------------------------------------------------ Hjälp

    def _log(self, msg, color=None):
        self.log.configure(state=tk.NORMAL)
        tag = f"c{len(self.log.tag_names())}"
        if color:
            self.log.tag_configure(tag, foreground=color)
            self.log.insert(tk.END, msg + "\n", tag)
        else:
            self.log.insert(tk.END, msg + "\n")
        self.log.configure(state=tk.DISABLED)
        self.log.see(tk.END)

    def _set_status(self, msg):
        self.status_label.configure(text=msg)

    # ------------------------------------------------------------------ Data

    def _load_programs(self):
        self._log("Läser installerade program från registret...")
        self._set_status("Läser...")

        def _do():
            progs = get_installed_programs()
            self.after(0, lambda: self._populate(progs))

        threading.Thread(target=_do, daemon=True).start()

    def _populate(self, programs):
        self.programs = programs
        self.filtered = programs[:]
        self._refresh_tree()
        self._log(f"Hittade {len(programs)} installerade program.", "#4ec9b0")
        self._set_status(f"{len(programs)} program")

    def _filter(self):
        q = self.search_var.get().lower()
        self.filtered = [
            p for p in self.programs
            if q in p["name"].lower() or q in p["publisher"].lower()
        ] if q else self.programs[:]
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for p in self.filtered:
            self.tree.insert("", tk.END, values=(p["name"], p["version"], p["publisher"]))
        self.count_label.configure(text=f"Visar {len(self.filtered)} av {len(self.programs)}")

    def _sort(self, col):
        self.filtered.sort(key=lambda p: p[col].lower())
        self._refresh_tree()

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        self.uninstall_btn.configure(state=tk.NORMAL if sel else tk.DISABLED)

    def _selected_program(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        return self.filtered[idx]

    # ------------------------------------------------------------------ Avinstallation

    def _start_uninstall(self):
        prog = self._selected_program()
        if not prog:
            return

        if not messagebox.askyesno(
            "Bekräfta", f"Vill du avinstallera:\n\n{prog['name']}\n\nDetta går inte att ångra."
        ):
            return

        self.uninstall_btn.configure(state=tk.DISABLED)
        self._log(f"\n--- Avinstallerar: {prog['name']} ---", "#569cd6")

        def _do():
            ok, out = run_uninstaller(prog, quiet=self.quiet_var.get())
            self.after(0, lambda: self._after_uninstall(prog, ok, out))

        threading.Thread(target=_do, daemon=True).start()

    def _after_uninstall(self, prog, ok, output):
        if ok:
            self._log("Avinstallationen klar.", "#4ec9b0")
        else:
            self._log(f"Problem vid avinstallation: {output}", "#f44747")

        if output.strip():
            self._log(output[:500])

        self._log("Söker efter kvarlämningar...", "#dcdcaa")
        threading.Thread(target=self._scan_leftovers, args=(prog,), daemon=True).start()

    def _scan_leftovers(self, prog):
        files = find_leftover_files(prog["name"])
        reg_keys = find_leftover_registry_keys(prog["name"])
        self.after(0, lambda: self._show_leftovers(prog, files, reg_keys))

    def _show_leftovers(self, prog, files, reg_keys):
        total = len(files) + len(reg_keys)
        if total == 0:
            self._log("Inga kvarlämningar hittades. Rent avinstallerat!", "#4ec9b0")
            self._load_programs()
            return

        self._log(f"Hittade {len(files)} filer/mappar och {len(reg_keys)} registerposter.", "#ce9178")

        # Visa panel för kvarlämningar
        self.leftovers_frame.pack(fill=tk.BOTH, padx=12, pady=(0, 8))
        for w in self.leftovers_frame.winfo_children():
            w.destroy()

        tk.Label(
            self.leftovers_frame,
            text=f"Följande kvarlämningar hittades för \"{prog['name']}\". Bocka i det du vill ta bort:",
            bg="#f0f0f0", font=("Segoe UI", 9), wraplength=900, justify=tk.LEFT
        ).pack(anchor="w", padx=6, pady=4)

        canvas = tk.Canvas(self.leftovers_frame, bg="#f0f0f0", highlightthickness=0)
        sb = ttk.Scrollbar(self.leftovers_frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg="#f0f0f0")
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=event.width)

        inner.bind("<Configure>", _resize)
        canvas.bind("<Configure>", _resize)

        checks = []

        if files:
            tk.Label(inner, text="Filer och mappar:", bg="#f0f0f0",
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        for f in files:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(inner, text=f, variable=var).pack(anchor="w", padx=18)
            checks.append(("file", f, var))

        if reg_keys:
            tk.Label(inner, text="Registerposter:", bg="#f0f0f0",
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=6, pady=(8, 2))
        for k in reg_keys:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(inner, text=k, variable=var).pack(anchor="w", padx=18)
            checks.append(("reg", k, var))

        btn_row = tk.Frame(self.leftovers_frame, bg="#f0f0f0")
        btn_row.pack(fill=tk.X, padx=6, pady=6)

        ttk.Button(
            btn_row, text="Ta bort markerade",
            command=lambda: self._delete_leftovers(checks)
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_row, text="Hoppa över",
            command=lambda: (self.leftovers_frame.pack_forget(), self._load_programs())
        ).pack(side=tk.LEFT)

    def _delete_leftovers(self, checks):
        ok = err = 0
        for kind, path, var in checks:
            if not var.get():
                continue
            if kind == "file":
                success = delete_path(path)
            else:
                success = delete_registry_key(path)

            if success:
                self._log(f"  Raderat: {path}", "#4ec9b0")
                ok += 1
            else:
                self._log(f"  Misslyckades: {path}", "#f44747")
                err += 1

        self._log(f"\nKlart: {ok} borttagna, {err} misslyckades.", "#4ec9b0" if err == 0 else "#ce9178")
        self.leftovers_frame.pack_forget()
        self._load_programs()


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def main():
    if not WINDOWS:
        print("Det här programmet är avsett för Windows.")
        print("På Linux/Mac används andra verktyg (apt, brew, etc.).")
        sys.exit(1)

    app = UninstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
