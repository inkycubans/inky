"""
InkyVPN – WireGuard-klient för Windows.

Kräver:
  • WireGuard för Windows  → https://www.wireguard.com/install/
  • Körning som administratör (för att hantera tunneltjänsten)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import subprocess
import threading
import os
import sys
import shutil
import urllib.request

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

APP_NAME   = "InkyVPN"
APP_DATA   = os.path.join(os.environ.get("APPDATA", "."), APP_NAME)
CONF_DIR   = os.path.join(APP_DATA, "tunnels")
os.makedirs(CONF_DIR, exist_ok=True)

WG_SEARCH_PATHS = [
    r"C:\Program Files\WireGuard\wireguard.exe",
    r"C:\Program Files (x86)\WireGuard\wireguard.exe",
]

WG_EXE = next((p for p in WG_SEARCH_PATHS if os.path.isfile(p)), None)
WG_DIR  = os.path.dirname(WG_EXE) if WG_EXE else None
WG_CMD  = os.path.join(WG_DIR, "wg.exe") if WG_DIR else None

DISCONNECTED  = "disconnected"
CONNECTING    = "connecting"
CONNECTED     = "connected"
DISCONNECTING = "disconnecting"

POLL_MS = 3000   # ms mellan statuskontroller

# ---------------------------------------------------------------------------
# Windowsspecifik kontroll
# ---------------------------------------------------------------------------

try:
    import ctypes
    IS_WINDOWS = sys.platform == "win32"
except ImportError:
    IS_WINDOWS = False


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# WireGuard-funktioner
# ---------------------------------------------------------------------------

def wg_installed():
    return WG_EXE is not None and os.path.isfile(WG_EXE)


def tunnel_name(conf_path):
    """Returnerar tunnelnamnet (filnamn utan .conf)."""
    return os.path.splitext(os.path.basename(conf_path))[0]


def parse_conf(conf_path):
    """Läser grundläggande metadata ur en WireGuard .conf-fil."""
    meta = {"name": tunnel_name(conf_path), "address": "", "endpoint": "", "dns": ""}
    try:
        with open(conf_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.lower().startswith("address"):
                    meta["address"] = line.split("=", 1)[1].strip()
                elif line.lower().startswith("endpoint"):
                    meta["endpoint"] = line.split("=", 1)[1].strip()
                elif line.lower().startswith("dns"):
                    meta["dns"] = line.split("=", 1)[1].strip()
    except Exception:
        pass
    return meta


def is_tunnel_active(tname):
    """Kontrollerar om WireGuard-tunneln körs (Windows-tjänst)."""
    try:
        r = subprocess.run(
            ["sc", "query", f"WireGuardTunnel${tname}"],
            capture_output=True, text=True, timeout=5
        )
        return "RUNNING" in r.stdout
    except Exception:
        return False


def connect_tunnel(conf_path):
    """Startar WireGuard-tunneln. Returnerar (ok: bool, felmeddelande: str)."""
    if not wg_installed():
        return False, "WireGuard är inte installerat."
    try:
        r = subprocess.run(
            [WG_EXE, "/installtunnelservice", conf_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "Okänt fel.").strip()
    except subprocess.TimeoutExpired:
        return False, "Tidsgräns överskred vid anslutning."
    except Exception as e:
        return False, str(e)


def disconnect_tunnel(tname):
    """Stoppar WireGuard-tunneln. Returnerar (ok: bool, felmeddelande: str)."""
    if not wg_installed():
        return False, "WireGuard är inte installerat."
    try:
        r = subprocess.run(
            [WG_EXE, "/uninstalltunnelservice", tname],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "Okänt fel.").strip()
    except subprocess.TimeoutExpired:
        return False, "Tidsgräns överskred vid frånkoppling."
    except Exception as e:
        return False, str(e)


def wg_stats(tname):
    """Hämtar RX/TX-statistik från `wg show`. Returnerar dict eller None."""
    if not WG_CMD or not os.path.isfile(WG_CMD):
        return None
    try:
        r = subprocess.run(
            [WG_CMD, "show", tname, "transfer"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                return {"rx": int(parts[1]), "tx": int(parts[2])}
    except Exception:
        pass
    return None


def fmt_bytes(n):
    """Formaterar antal bytes till läsbart format."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def get_public_ip():
    """Returnerar maskinens publika IP-adress, eller None vid fel."""
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com",
                "https://icanhazip.com"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "InkyVPN/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return None


def list_profiles():
    """Returnerar lista med .conf-filnamn i konfigurationsmappen."""
    try:
        return sorted(f for f in os.listdir(CONF_DIR) if f.endswith(".conf"))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class VPNApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("780x580")
        self.minsize(620, 460)
        self.configure(bg="#f0f0f0")

        self._status         = DISCONNECTED
        self._active_tunnel  = None   # tunnelnamn för aktiv anslutning
        self._active_conf    = None   # sökväg till aktiv .conf

        self._build_ui()
        self._refresh_profiles()
        self._check_prerequisites()
        self._schedule_poll()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        # Rubrik
        header = tk.Frame(self, bg="#2d6a9f", pady=8)
        header.pack(fill=tk.X)
        tk.Label(
            header, text=APP_NAME,
            font=("Segoe UI", 16, "bold"), fg="white", bg="#2d6a9f"
        ).pack(side=tk.LEFT, padx=16)
        tk.Label(
            header, text="WireGuard VPN-klient",
            font=("Segoe UI", 10), fg="#cce0f5", bg="#2d6a9f"
        ).pack(side=tk.LEFT, padx=4)

        self.status_text = tk.Label(
            header, text="Frånkopplad",
            font=("Segoe UI", 10), fg="#cce0f5", bg="#2d6a9f"
        )
        self.status_text.pack(side=tk.RIGHT, padx=8)
        self.status_dot = tk.Label(
            header, text="●",
            font=("Segoe UI", 18), fg="#f44747", bg="#2d6a9f"
        )
        self.status_dot.pack(side=tk.RIGHT, padx=(8, 0))

        # Innehållsarea
        content = tk.Frame(self, bg="#f0f0f0")
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # --- Vänster: profillista ---
        left = tk.Frame(content, bg="#f0f0f0")
        left.pack(side=tk.LEFT, fill=tk.BOTH)

        tk.Label(
            left, text="VPN-profiler",
            bg="#f0f0f0", font=("Segoe UI", 9, "bold"), fg="#333"
        ).pack(anchor="w")

        list_frame = tk.Frame(left, bg="#f0f0f0")
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.profile_lb = tk.Listbox(
            list_frame,
            font=("Segoe UI", 10),
            bg="white", fg="#222",
            selectbackground="#2d6a9f", selectforeground="white",
            relief=tk.FLAT, bd=1,
            highlightthickness=1, highlightcolor="#aaa",
            width=24, activestyle="none"
        )
        self.profile_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.profile_lb.bind("<<ListboxSelect>>", self._on_select)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.profile_lb.yview)
        self.profile_lb.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Knappar under listan
        lb_btns = tk.Frame(left, bg="#f0f0f0", pady=4)
        lb_btns.pack(fill=tk.X)
        ttk.Button(lb_btns, text="+ Importera .conf",
                   command=self._import_conf).pack(side=tk.LEFT, padx=(0, 4))
        self.delete_btn = ttk.Button(lb_btns, text="Ta bort",
                                     command=self._delete_profile, state=tk.DISABLED)
        self.delete_btn.pack(side=tk.LEFT)

        # --- Separator ---
        ttk.Separator(content, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # --- Höger: detaljer ---
        right = tk.Frame(content, bg="#f0f0f0")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            right, text="Anslutningsinformation",
            bg="#f0f0f0", font=("Segoe UI", 9, "bold"), fg="#333"
        ).pack(anchor="w")

        info = tk.Frame(right, bg="#f0f0f0", pady=4)
        info.pack(fill=tk.X)

        def row(label, r):
            tk.Label(info, text=label + ":", bg="#f0f0f0",
                     font=("Segoe UI", 9), fg="#555",
                     width=14, anchor="e"
                     ).grid(row=r, column=0, sticky="e", pady=2, padx=(0, 6))
            var = tk.StringVar(value="—")
            tk.Label(info, textvariable=var, bg="#f0f0f0",
                     font=("Segoe UI", 9), fg="#111", anchor="w"
                     ).grid(row=r, column=1, sticky="w")
            return var

        self.v_profil    = row("Profil",      0)
        self.v_server    = row("Server",      1)
        self.v_address   = row("VPN-adress",  2)
        self.v_dns       = row("DNS",         3)
        self.v_pubip     = row("Publik IP",   4)
        self.v_rx        = row("Mottagen",    5)
        self.v_tx        = row("Skickad",     6)

        # Anslutningsknapp + spinner
        conn_row = tk.Frame(right, bg="#f0f0f0", pady=10)
        conn_row.pack(anchor="w")
        self.connect_btn = ttk.Button(
            conn_row, text="Anslut",
            command=self._toggle, state=tk.DISABLED, width=18
        )
        self.connect_btn.pack(side=tk.LEFT)
        self.spinner = tk.Label(conn_row, text="", bg="#f0f0f0",
                                font=("Segoe UI", 9), fg="#888")
        self.spinner.pack(side=tk.LEFT, padx=8)

        # --- Logg ---
        tk.Label(self, text="Logg:", anchor="w",
                 bg="#f0f0f0", font=("Segoe UI", 9, "bold")).pack(fill=tk.X, padx=12)
        self.log_box = scrolledtext.ScrolledText(
            self, height=7, state=tk.DISABLED,
            font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.log_box.pack(fill=tk.X, padx=12, pady=(0, 8))

    # ------------------------------------------------------------------ Profiler

    def _refresh_profiles(self):
        self.profile_lb.delete(0, tk.END)
        for f in list_profiles():
            self.profile_lb.insert(tk.END, os.path.splitext(f)[0])
        self._clear_info()

    def _sel_name(self):
        sel = self.profile_lb.curselection()
        return self.profile_lb.get(sel[0]) if sel else None

    def _sel_path(self):
        name = self._sel_name()
        return os.path.join(CONF_DIR, name + ".conf") if name else None

    def _on_select(self, _=None):
        name = self._sel_name()
        self.delete_btn.configure(state=tk.NORMAL if name else tk.DISABLED)
        if name:
            meta = parse_conf(os.path.join(CONF_DIR, name + ".conf"))
            self._show_meta(meta)
        if self._status == DISCONNECTED:
            self.connect_btn.configure(
                state=tk.NORMAL if name else tk.DISABLED,
                text="Anslut"
            )

    def _show_meta(self, meta):
        self.v_profil.set(meta["name"])
        self.v_server.set(meta["endpoint"] or "—")
        self.v_address.set(meta["address"] or "—")
        self.v_dns.set(meta["dns"] or "—")

    def _clear_info(self):
        for v in (self.v_profil, self.v_server, self.v_address,
                  self.v_dns, self.v_pubip, self.v_rx, self.v_tx):
            v.set("—")

    def _import_conf(self):
        path = filedialog.askopenfilename(
            title="Välj WireGuard-konfigurationsfil",
            filetypes=[("WireGuard Config", "*.conf"), ("Alla filer", "*.*")]
        )
        if not path:
            return
        dest = os.path.join(CONF_DIR, os.path.basename(path))
        if os.path.exists(dest):
            if not messagebox.askyesno(
                "Profil finns redan",
                f"'{os.path.basename(path)}' finns redan. Vill du ersätta den?"
            ):
                return
        try:
            shutil.copy2(path, dest)
            self._log(f"Importerade: {os.path.basename(path)}", "#4ec9b0")
            self._refresh_profiles()
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte importera filen:\n{e}")

    def _delete_profile(self):
        name = self._sel_name()
        if not name:
            return
        if self._active_tunnel == name:
            messagebox.showwarning("Aktiv profil",
                                   "Koppla från tunneln innan du tar bort profilen.")
            return
        if not messagebox.askyesno("Ta bort profil",
                                   f"Ta bort profilen '{name}'?"):
            return
        try:
            os.remove(os.path.join(CONF_DIR, name + ".conf"))
            self._log(f"Tog bort: {name}", "#ce9178")
            self._refresh_profiles()
            self.connect_btn.configure(state=tk.DISABLED)
            self.delete_btn.configure(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Fel", f"Kunde inte ta bort profilen:\n{e}")

    # ------------------------------------------------------------------ Anslutning

    def _toggle(self):
        if self._status == CONNECTED:
            self._start_disconnect()
        elif self._status == DISCONNECTED:
            self._start_connect()

    def _start_connect(self):
        conf = self._sel_path()
        if not conf:
            return
        tname = tunnel_name(conf)
        self._set_status(CONNECTING)
        self._log(f"Ansluter till '{tname}'...", "#dcdcaa")

        def _do():
            ok, err = connect_tunnel(conf)
            self.after(0, lambda: self._after_connect(conf, tname, ok, err))

        threading.Thread(target=_do, daemon=True).start()

    def _after_connect(self, conf, tname, ok, err):
        if ok:
            self._active_tunnel = tname
            self._active_conf   = conf
            self._set_status(CONNECTED)
            self._log(f"Tunnel '{tname}' ansluten!", "#4ec9b0")
            self._fetch_ip()
        else:
            self._set_status(DISCONNECTED)
            self._log(f"Anslutning misslyckades: {err}", "#f44747")
            if any(w in err.lower() for w in ("access", "denied", "privilege")):
                messagebox.showerror(
                    "Adminrättigheter krävs",
                    "WireGuard kräver administratörsbehörighet.\n\n"
                    "Högerklicka på vpn_app.py och välj\n'Kör som administratör'."
                )

    def _start_disconnect(self):
        tname = self._active_tunnel
        if not tname:
            return
        self._set_status(DISCONNECTING)
        self._log(f"Kopplar från '{tname}'...", "#dcdcaa")

        def _do():
            ok, err = disconnect_tunnel(tname)
            self.after(0, lambda: self._after_disconnect(tname, ok, err))

        threading.Thread(target=_do, daemon=True).start()

    def _after_disconnect(self, tname, ok, err):
        if ok:
            self._log(f"'{tname}' frånkopplad.", "#ce9178")
        else:
            self._log(f"Frånkoppling misslyckades: {err}", "#f44747")
        self._active_tunnel = None
        self._active_conf   = None
        self.v_pubip.set("—")
        self.v_rx.set("—")
        self.v_tx.set("—")
        self._set_status(DISCONNECTED)

    # ------------------------------------------------------------------ Statuspollning

    def _schedule_poll(self):
        self.after(POLL_MS, self._poll)

    def _poll(self):
        if self._status == CONNECTED and self._active_tunnel:
            tname = self._active_tunnel
            threading.Thread(target=self._poll_worker, args=(tname,), daemon=True).start()
        self._schedule_poll()

    def _poll_worker(self, tname):
        active = is_tunnel_active(tname)
        stats  = wg_stats(tname) if active else None
        self.after(0, lambda: self._apply_poll(tname, active, stats))

    def _apply_poll(self, tname, active, stats):
        if not active and self._status == CONNECTED:
            self._log(f"Tunneln '{tname}' verkar ha tappats.", "#f44747")
            self._active_tunnel = None
            self._active_conf   = None
            self.v_pubip.set("—")
            self.v_rx.set("—")
            self.v_tx.set("—")
            self._set_status(DISCONNECTED)
        elif active and stats:
            self.v_rx.set(fmt_bytes(stats["rx"]))
            self.v_tx.set(fmt_bytes(stats["tx"]))

    def _fetch_ip(self):
        self.v_pubip.set("Hämtar...")

        def _do():
            ip = get_public_ip()
            self.after(0, lambda: self.v_pubip.set(ip or "Kunde inte hämta IP"))

        threading.Thread(target=_do, daemon=True).start()

    # ------------------------------------------------------------------ Statushantering

    def _set_status(self, status):
        self._status = status
        colors = {
            DISCONNECTED:  ("#f44747", "Frånkopplad"),
            CONNECTING:    ("#dcdcaa", "Ansluter..."),
            CONNECTED:     ("#4ec9b0", "Ansluten"),
            DISCONNECTING: ("#dcdcaa", "Kopplar från..."),
        }
        dot_color, label = colors.get(status, ("#888", "Okänt"))
        self.status_dot.configure(fg=dot_color)
        self.status_text.configure(text=label)

        if status == DISCONNECTED:
            sel = self._sel_name()
            self.connect_btn.configure(
                text="Anslut",
                state=tk.NORMAL if sel else tk.DISABLED
            )
            self.spinner.configure(text="")
        elif status == CONNECTED:
            self.connect_btn.configure(text="Koppla från", state=tk.NORMAL)
            self.spinner.configure(text="")
        else:
            self.connect_btn.configure(state=tk.DISABLED)
            self.spinner.configure(text="Väntar...")

    # ------------------------------------------------------------------ Logg

    def _log(self, msg, color=None):
        self.log_box.configure(state=tk.NORMAL)
        tag = f"t{len(self.log_box.tag_names())}"
        if color:
            self.log_box.tag_configure(tag, foreground=color)
            self.log_box.insert(tk.END, msg + "\n", tag)
        else:
            self.log_box.insert(tk.END, msg + "\n")
        self.log_box.configure(state=tk.DISABLED)
        self.log_box.see(tk.END)

    # ------------------------------------------------------------------ Förutsättningar

    def _check_prerequisites(self):
        if not IS_WINDOWS:
            self._log("Det här programmet är avsett för Windows.", "#f44747")
            return

        if not wg_installed():
            self._log(
                "WireGuard hittades inte. Hämta från: wireguard.com/install/",
                "#f44747"
            )
            messagebox.showwarning(
                "WireGuard saknas",
                "WireGuard för Windows hittades inte.\n\n"
                "Hämta det på:\nhttps://www.wireguard.com/install/\n\n"
                "Starta sedan om InkyVPN."
            )
            return

        self._log(f"WireGuard: {WG_EXE}", "#4ec9b0")

        if not is_admin():
            self._log(
                "Varning: Körs inte som administratör – anslutning kan misslyckas.",
                "#dcdcaa"
            )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def main():
    app = VPNApp()
    app.mainloop()


if __name__ == "__main__":
    main()
