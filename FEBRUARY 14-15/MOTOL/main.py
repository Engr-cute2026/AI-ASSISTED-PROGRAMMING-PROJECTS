"""
Bridge STAAD Builder — Python Tkinter GUI
Generates and runs bridge truss models directly in STAAD.Pro via OpenSTAADPy.

Requirements:
    - STAAD.Pro (with an empty model open)
    - openstaadpy installed (pip install openstaadpy)
    - Python 3.8+
    - tkinter (built-in with Python)
    - matplotlib (pip install matplotlib)

Usage:
    python bridge_staad_gui.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import math
import threading

# matplotlib for live SVG-style canvas preview
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── Colour palette ────────────────────────────────────────────────────────────
BG        = "#0a0f1a"
PANEL_BG  = "#0d1526"
CARD_BG   = "#111c30"
BORDER    = "#1e3a5f"
ACCENT    = "#f59e0b"
ACCENT2   = "#60a5fa"
TEXT      = "#c9d8f0"
MUTED     = "#475569"
SUCCESS   = "#22c55e"
DANGER    = "#ef4444"
PURPLE    = "#a78bfa"

# ── Section tables ────────────────────────────────────────────────────────────
CHORD_SECTIONS    = ["W21X50","W18X35","W16X31","W14X26","W24X55","W18X46"]
DIAGONAL_SECTIONS = ["L40404","L50505","L60606","L30303","L35353","L45454"]
UNIT_OPTIONS      = {
    "Feet / Kip"   : (1, 0),
    "Meter / kN"   : (5, 4),
    "Inches / Kip" : (0, 0),
}
BRIDGE_TYPES = ["Pratt Truss", "Warren Truss", "Howe Truss", "Bowstring Arch"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Geometry helpers
# ═══════════════════════════════════════════════════════════════════════════════

def compute_geometry(span, height, panels, btype):
    """Return (nodes dict, members dict, bottomNodes, topNodes, ...)"""
    panel_w   = span / panels
    nodes     = {}          # nid -> (x, y, z)
    nid       = 1
    bottom    = []
    top       = []

    btype_key = btype.lower().split()[0]   # "pratt" | "warren" | "howe" | "bowstring"

    # ── bottom chord nodes ────────────────────────────────────────────────────
    for i in range(panels + 1):
        x = round(i * panel_w, 4)
        nodes[nid] = (x, 0.0, 0.0)
        bottom.append(nid); nid += 1

    # ── top chord nodes ───────────────────────────────────────────────────────
    if btype_key == "warren":
        for i in range(panels):
            x = round((i + 0.5) * panel_w, 4)
            nodes[nid] = (x, float(height), 0.0)
            top.append(nid); nid += 1
    elif btype_key == "bowstring":
        for i in range(panels + 1):
            x   = round(i * panel_w, 4)
            y   = round(height * math.sin((i / panels) * math.pi), 4)
            nodes[nid] = (x, y, 0.0)
            top.append(nid); nid += 1
    else:  # pratt / howe
        for i in range(panels + 1):
            x = round(i * panel_w, 4)
            nodes[nid] = (x, float(height), 0.0)
            top.append(nid); nid += 1

    # ── members ───────────────────────────────────────────────────────────────
    members   = {}
    mid_      = 1
    bot_ch    = []
    top_ch    = []
    verts     = []
    diags     = []

    # bottom chords
    for i in range(panels):
        members[mid_] = (bottom[i], bottom[i+1]); bot_ch.append(mid_); mid_ += 1

    if btype_key == "warren":
        # top chords between apex nodes
        for i in range(panels - 1):
            members[mid_] = (top[i], top[i+1]); top_ch.append(mid_); mid_ += 1
        # diagonals (W-pattern)
        for i in range(panels):
            members[mid_] = (bottom[i],   top[i]);   diags.append(mid_); mid_ += 1
            members[mid_] = (top[i], bottom[i+1]);   diags.append(mid_); mid_ += 1

    elif btype_key in ("pratt", "howe"):
        # top chords
        for i in range(panels):
            members[mid_] = (top[i], top[i+1]); top_ch.append(mid_); mid_ += 1
        # verticals
        for i in range(panels + 1):
            members[mid_] = (bottom[i], top[i]); verts.append(mid_); mid_ += 1
        # diagonals
        half = panels // 2
        for i in range(panels):
            if btype_key == "pratt":
                if i < half:
                    members[mid_] = (top[i],    bottom[i+1])
                else:
                    members[mid_] = (bottom[i], top[i+1])
            else:   # howe
                if i < half:
                    members[mid_] = (bottom[i], top[i+1])
                else:
                    members[mid_] = (top[i],    bottom[i+1])
            diags.append(mid_); mid_ += 1

    elif btype_key == "bowstring":
        # top arch chords
        for i in range(panels):
            members[mid_] = (top[i], top[i+1]); top_ch.append(mid_); mid_ += 1
        # verticals (hangers)
        for i in range(panels + 1):
            members[mid_] = (bottom[i], top[i]); verts.append(mid_); mid_ += 1
        # diagonals
        for i in range(panels):
            members[mid_] = (bottom[i], top[i+1]); diags.append(mid_); mid_ += 1

    return nodes, members, bottom, top, bot_ch, top_ch, verts, diags


# ═══════════════════════════════════════════════════════════════════════════════
#  STAAD.Pro execution
# ═══════════════════════════════════════════════════════════════════════════════

def run_in_staad(cfg, log_callback):
    """Connect to STAAD.Pro and build the bridge model."""
    try:
        from openstaadpy import os_analytical
    except ImportError:
        log_callback("ERROR: openstaadpy not found.\n"
                     "Install with:  pip install openstaadpy", error=True)
        return False

    span    = cfg["span"]
    height  = cfg["height"]
    panels  = cfg["panels"]
    btype   = cfg["bridge_type"]
    unit    = cfg["unit"]
    csec    = cfg["chord_sec"]
    dsec    = cfg["diag_sec"]
    supp_l  = cfg["support_left"]
    supp_r  = cfg["support_right"]
    sw      = cfg["self_weight"]
    dl      = cfg["dead_load"]
    ll      = cfg["live_load"]
    wl      = cfg["wind_load"]

    lu, fu  = UNIT_OPTIONS[unit]

    nodes, members, bottom, top_n, bot_ch, top_ch, verts, diags = \
        compute_geometry(span, height, panels, btype)

    total_n = len(nodes)
    total_m = len(members)

    try:
        log_callback("Connecting to STAAD.Pro …")
        staad = os_analytical.connect()
        geo   = staad.Geometry
        prop  = staad.Property
        sup   = staad.Support
        load  = staad.Load

        log_callback(f"Setting units: {unit} (length={lu}, force={fu})")
        staad.SetInputUnits(lu, fu)
        staad.SaveModel(True)

        # Nodes
        log_callback(f"Creating {total_n} nodes …")
        for nid, (x, y, z) in nodes.items():
            geo.CreateNode(nid, x, y, z)

        # Members
        log_callback(f"Creating {total_m} members …")
        for mid, (n1, n2) in members.items():
            geo.CreateBeam(mid, n1, n2)

        # Properties
        log_callback("Assigning sections …")
        cc       = 1  # AISC
        chord_p  = prop.CreateBeamPropertyFromTable(cc, csec, 0, 0.0, 0.0)
        diag_p   = prop.CreateAnglePropertyFromTable(cc, dsec, 0, 0.0)

        prop.AssignBeamProperty(bot_ch, chord_p)
        if top_ch:
            prop.AssignBeamProperty(top_ch, chord_p)
        if verts:
            prop.AssignBeamProperty(verts, diag_p)
        if diags:
            prop.AssignBeamProperty(diags, diag_p)

        prop.AssignMaterialToMember("STEEL", list(range(1, total_m + 1)))

        # Releases on diagonals/verticals
        if diags:
            log_callback("Applying member releases …")
            sr = prop.CreateMemberPartialReleaseSpec(0, [0,1,1], [0.0,0.99,0.99])
            er = prop.CreateMemberPartialReleaseSpec(1, [0,1,1], [0.0,0.99,0.99])
            prop.AssignMemberSpecToBeam(diags, sr)
            prop.AssignMemberSpecToBeam(diags, er)

        # Supports
        log_callback("Assigning supports …")
        left_node  = bottom[0]
        right_node = bottom[-1]

        if supp_l == "Fixed":
            sid = sup.CreateSupportFixed()
        else:
            sid = sup.CreateSupportPinned()
        sup.AssignSupportToNode([left_node], sid)

        if supp_r == "Pinned":
            sid2 = sup.CreateSupportPinned()
        else:
            sid2 = sup.CreateSupportFixed()
        sup.AssignSupportToNode([right_node], sid2)

        # Load Case 1 – Dead + Live
        log_callback("Creating load cases …")
        c1 = load.CreateNewPrimaryLoadEx2("DEAD AND LIVE LOAD", 0, 1)
        load.SetLoadActive(c1)
        if sw:
            load.AddSelfWeightInXYZ(2, -1.0)
        interior = bottom[1:-1]
        if ll > 0 and interior:
            for n in interior:
                load.AddNodalLoad([n], 0.0, -ll, 0.0, 0.0, 0.0, 0.0)
        if dl > 0:
            load.AddMemberUniformForce(bot_ch, 2, -dl, 0.0, 0.0, 0.0)

        # Load Case 2 – Wind
        c2 = load.CreateNewPrimaryLoadEx2("WIND FROM LEFT", 3, 2)
        load.SetLoadActive(c2)
        if wl > 0:
            wind_members = verts if verts else bot_ch
            load.AddMemberUniformForce(wind_members, 4, wl, 0.0, 0.0, 0.0)

        # Combination 3 – 75 %
        load.CreateNewLoadCombination("75 PERCENT DL LL WL", 3)
        load.AddLoadAndFactorToCombination(3, 1, 0.75)
        load.AddLoadAndFactorToCombination(3, 2, 0.75)

        # Save & analyse
        log_callback("Saving model …")
        staad.SaveModel(True)
        log_callback("Running analysis …")
        staad.Command.PerformAnalysis(0)

        log_callback(
            f"\n✔  DONE  —  {btype}  |  Span {span} ft  |  "
            f"Height {height} ft  |  {panels} panels\n"
            f"   Nodes: {total_n}   Members: {total_m}",
            success=True
        )
        return True

    except Exception as exc:
        log_callback(f"\n✘  Error: {exc}", error=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Preview canvas (matplotlib or fallback tkinter canvas)
# ═══════════════════════════════════════════════════════════════════════════════

def draw_preview_mpl(ax, span, height, panels, btype):
    ax.clear()
    ax.set_facecolor("#060f1a")

    nodes, members, bottom, top_n, bot_ch, top_ch, verts, diags = \
        compute_geometry(span, height, panels, btype)

    color_map = {}
    for m in bot_ch + top_ch:
        color_map[m] = ("#f59e0b", 2.2)
    for m in diags:
        color_map[m] = ("#60a5fa", 1.5)
    for m in verts:
        color_map[m] = ("#94a3b8", 1.4)

    for mid, (n1, n2) in members.items():
        x1, y1, _ = nodes[n1]
        x2, y2, _ = nodes[n2]
        col, lw    = color_map.get(mid, ("#60a5fa", 1.5))
        ax.plot([x1, x2], [y1, y2], color=col, linewidth=lw, solid_capstyle="round")

    for nid, (x, y, _) in nodes.items():
        ax.plot(x, y, "o", markersize=4, color="#1e293b",
                markeredgecolor="#60a5fa", markeredgewidth=1.2)

    # Support symbols
    lx, ly, _ = nodes[bottom[0]]
    rx, ry, _ = nodes[bottom[-1]]
    ax.plot(lx, ly, "^", markersize=10, color=ACCENT,  zorder=5)
    ax.plot(rx, ry, "s", markersize=8,  color=ACCENT2, zorder=5)

    # Ground line
    ax.axhline(-0.4, color=MUTED, linewidth=1.5)

    ax.set_xlim(-span * 0.05, span * 1.05)
    ax.set_ylim(-height * 0.25, height * 1.3)
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")

    # Legend
    handles = [
        mpatches.Patch(color="#f59e0b", label="Chord"),
        mpatches.Patch(color="#60a5fa", label="Diagonal"),
        mpatches.Patch(color="#94a3b8", label="Vertical"),
    ]
    ax.legend(handles=handles, loc="upper right",
              facecolor="#0a0f1a", edgecolor=BORDER,
              labelcolor=TEXT, fontsize=7, framealpha=0.9)

    ax.set_title(f"{btype}  |  Span {span} ft  ·  H {height} ft  ·  {panels} panels",
                 color=ACCENT, fontsize=9, pad=6)


# ═══════════════════════════════════════════════════════════════════════════════
#  Styled widget helpers
# ═══════════════════════════════════════════════════════════════════════════════

def styled_label(parent, text, size=9, color=MUTED, **kw):
    return tk.Label(parent, text=text, font=("Consolas", size),
                    fg=color, bg=kw.pop("bg", PANEL_BG), **kw)

def styled_entry(parent, textvariable, width=10):
    e = tk.Entry(parent, textvariable=textvariable, width=width,
                 font=("Consolas", 10), fg=TEXT, bg=CARD_BG,
                 insertbackground=ACCENT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT)
    return e

def styled_combo(parent, values, textvariable, width=16):
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Dark.TCombobox",
                    fieldbackground=CARD_BG, background=CARD_BG,
                    foreground=TEXT, arrowcolor=ACCENT,
                    bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, selectbackground=BORDER,
                    selectforeground=ACCENT)
    cb = ttk.Combobox(parent, values=values, textvariable=textvariable,
                      width=width, state="readonly", style="Dark.TCombobox",
                      font=("Consolas", 10))
    return cb

def styled_scale(parent, variable, from_, to, resolution=1, command=None):
    s = tk.Scale(parent, variable=variable, from_=from_, to=to,
                 resolution=resolution, orient="horizontal",
                 command=command,
                 bg=PANEL_BG, fg=TEXT, troughcolor=CARD_BG,
                 activebackground=ACCENT, highlightthickness=0,
                 sliderrelief="flat", bd=0, font=("Consolas", 8))
    return s

def section_title(parent, text):
    f = tk.Frame(parent, bg=PANEL_BG)
    tk.Label(f, text=text, font=("Consolas", 8, "bold"),
             fg=ACCENT2, bg=PANEL_BG).pack(side="left")
    tk.Frame(f, height=1, bg=BORDER).pack(side="left", fill="x", expand=True, padx=(6,0))
    return f


# ═══════════════════════════════════════════════════════════════════════════════
#  Main GUI class
# ═══════════════════════════════════════════════════════════════════════════════

class BridgeSTAADApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Bridge STAAD Builder  —  OpenSTAADPy")
        self.configure(bg=BG)
        self.geometry("1180x760")
        self.minsize(900, 620)
        self.resizable(True, True)

        self._init_vars()
        self._build_ui()
        self._refresh_preview()

    # ── variable declarations ─────────────────────────────────────────────────

    def _init_vars(self):
        self.v_btype    = tk.StringVar(value="Pratt Truss")
        self.v_span     = tk.DoubleVar(value=120.0)
        self.v_height   = tk.DoubleVar(value=20.0)
        self.v_panels   = tk.IntVar(value=8)
        self.v_unit     = tk.StringVar(value="Feet / Kip")
        self.v_supp_l   = tk.StringVar(value="Fixed")
        self.v_supp_r   = tk.StringVar(value="Pinned")
        self.v_chord    = tk.StringVar(value="W21X50")
        self.v_diag     = tk.StringVar(value="L40404")
        self.v_dead     = tk.DoubleVar(value=1.2)
        self.v_live     = tk.DoubleVar(value=20.0)
        self.v_wind     = tk.DoubleVar(value=0.6)
        self.v_sw       = tk.BooleanVar(value=True)

        # bind auto-refresh
        for v in (self.v_btype, self.v_span, self.v_height,
                  self.v_panels, self.v_unit):
            v.trace_add("write", lambda *_: self._refresh_preview())

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── header bar ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg="#060f1a", height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        ico = tk.Label(hdr, text="⛓", font=("Segoe UI Emoji", 18),
                       fg=ACCENT, bg="#060f1a")
        ico.pack(side="left", padx=(18,8), pady=8)

        tk.Label(hdr, text="BRIDGE STAAD BUILDER",
                 font=("Consolas", 13, "bold"),
                 fg=ACCENT, bg="#060f1a").pack(side="left")
        tk.Label(hdr, text="  OPENSTAADPY DIRECT RUNNER",
                 font=("Consolas", 8), fg=MUTED, bg="#060f1a").pack(side="left")

        dot = tk.Label(hdr, text="● READY", font=("Consolas", 9),
                       fg=SUCCESS, bg="#060f1a")
        dot.pack(side="right", padx=18)
        self._status_dot = dot

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # left sidebar
        sidebar = tk.Frame(body, bg=PANEL_BG, width=300)
        sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

        # right main area
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_sidebar(sidebar)
        self._build_right(right)

    # ── sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=PANEL_BG)
        sb.pack(fill="both", expand=True, padx=14, pady=14)

        # ─ Bridge Type ────────────────────────────────────────────────────────
        section_title(sb, "BRIDGE TYPE").pack(fill="x", pady=(0,8))
        grid = tk.Frame(sb, bg=PANEL_BG)
        grid.pack(fill="x", pady=(0,14))
        icons = {"Pratt Truss":"◇","Warren Truss":"△",
                 "Howe Truss":"▽","Bowstring Arch":"⌒"}
        self._type_btns = {}
        for i, bt in enumerate(BRIDGE_TYPES):
            r, c = divmod(i, 2)
            btn  = tk.Button(grid, text=f"{icons[bt]}\n{bt}",
                             font=("Consolas", 8), wraplength=100,
                             width=11, height=3,
                             relief="flat", cursor="hand2",
                             command=lambda b=bt: self._select_type(b))
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            self._type_btns[bt] = btn
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)
        self._select_type("Pratt Truss")

        # ─ Geometry ───────────────────────────────────────────────────────────
        section_title(sb, "GEOMETRY").pack(fill="x", pady=(4,8))

        self._add_slider(sb, "Span (ft)", self.v_span,     40,  400, 10)
        self._add_slider(sb, "Height (ft)", self.v_height,  5,   60,  1)
        self._add_slider(sb, "Panels",    self.v_panels,    4,   16,  2)

        # ─ Units & Supports ──────────────────────────────────────────────────
        section_title(sb, "UNITS & SUPPORTS").pack(fill="x", pady=(10,8))

        row_u = tk.Frame(sb, bg=PANEL_BG); row_u.pack(fill="x", pady=2)
        styled_label(row_u, "Units").pack(side="left")
        styled_combo(row_u, list(UNIT_OPTIONS), self.v_unit, 14).pack(side="right")

        row_sl = tk.Frame(sb, bg=PANEL_BG); row_sl.pack(fill="x", pady=2)
        styled_label(row_sl, "Left support").pack(side="left")
        styled_combo(row_sl, ["Fixed","Pinned"], self.v_supp_l, 8).pack(side="right")

        row_sr = tk.Frame(sb, bg=PANEL_BG); row_sr.pack(fill="x", pady=2)
        styled_label(row_sr, "Right support").pack(side="left")
        styled_combo(row_sr, ["Pinned","Roller"], self.v_supp_r, 8).pack(side="right")

        # ─ Sections ───────────────────────────────────────────────────────────
        section_title(sb, "SECTIONS (AISC)").pack(fill="x", pady=(10,8))

        row_c = tk.Frame(sb, bg=PANEL_BG); row_c.pack(fill="x", pady=2)
        styled_label(row_c, "Chord").pack(side="left")
        styled_combo(row_c, CHORD_SECTIONS, self.v_chord, 10).pack(side="right")

        row_d = tk.Frame(sb, bg=PANEL_BG); row_d.pack(fill="x", pady=2)
        styled_label(row_d, "Diag/Vert").pack(side="left")
        styled_combo(row_d, DIAGONAL_SECTIONS, self.v_diag, 10).pack(side="right")

        # ─ Loads ──────────────────────────────────────────────────────────────
        section_title(sb, "LOADS").pack(fill="x", pady=(10,8))

        self._add_entry(sb, "Dead load (k/ft)",       self.v_dead)
        self._add_entry(sb, "Live load/node (kips)",  self.v_live)
        self._add_entry(sb, "Wind load (k/ft)",       self.v_wind)

        sw_row = tk.Frame(sb, bg=PANEL_BG); sw_row.pack(fill="x", pady=4)
        styled_label(sw_row, "Self weight").pack(side="left")
        tk.Checkbutton(sw_row, variable=self.v_sw, bg=PANEL_BG,
                       fg=TEXT, selectcolor=CARD_BG,
                       activebackground=PANEL_BG,
                       highlightthickness=0).pack(side="right")

        # ─ Run button ─────────────────────────────────────────────────────────
        tk.Frame(sb, bg=BORDER, height=1).pack(fill="x", pady=12)
        self._run_btn = tk.Button(
            sb, text="▶  RUN IN STAAD.PRO",
            font=("Consolas", 10, "bold"), fg="#050a10",
            bg=ACCENT, activebackground="#d97706",
            activeforeground="#050a10", relief="flat",
            cursor="hand2", pady=10,
            command=self._on_run)
        self._run_btn.pack(fill="x")

    def _add_slider(self, parent, label, var, from_, to, res):
        f = tk.Frame(parent, bg=PANEL_BG); f.pack(fill="x", pady=1)
        styled_label(f, label, color=MUTED).pack(anchor="w")
        row = tk.Frame(f, bg=PANEL_BG); row.pack(fill="x")
        s   = styled_scale(row, var, from_, to, res,
                           command=lambda *_: self._refresh_preview())
        s.pack(side="left", fill="x", expand=True)
        styled_label(row, "", color=ACCENT, width=5).pack(side="right")
        val_lbl = row.winfo_children()[-1]
        def _upd(*_):
            try:
                v = var.get()
                val_lbl.config(text=f"{v:.0f}" if isinstance(v, float) else str(v))
            except Exception:
                pass
        var.trace_add("write", _upd); _upd()

    def _add_entry(self, parent, label, var):
        f = tk.Frame(parent, bg=PANEL_BG); f.pack(fill="x", pady=2)
        styled_label(f, label).pack(side="left")
        styled_entry(f, var, 7).pack(side="right")

    # ── type button selection ─────────────────────────────────────────────────

    def _select_type(self, btype):
        self.v_btype.set(btype)
        for bt, btn in self._type_btns.items():
            if bt == btype:
                btn.config(bg=CARD_BG, fg=ACCENT,
                           highlightthickness=1,
                           highlightbackground=ACCENT)
            else:
                btn.config(bg=PANEL_BG, fg=MUTED,
                           highlightthickness=1,
                           highlightbackground=BORDER)

    # ── right panel ───────────────────────────────────────────────────────────

    def _build_right(self, parent):
        # preview area
        prev_frame = tk.Frame(parent, bg="#060f1a", height=320)
        prev_frame.pack(fill="x"); prev_frame.pack_propagate(False)

        if HAS_MPL:
            self._fig, self._ax = plt.subplots(
                figsize=(9, 3.2), facecolor="#060f1a")
            self._fig.subplots_adjust(left=0.01, right=0.99,
                                      top=0.88, bottom=0.04)
            self._canvas = FigureCanvasTkAgg(self._fig, master=prev_frame)
            self._canvas.get_tk_widget().pack(fill="both", expand=True)
        else:
            styled_label(prev_frame,
                         "Install matplotlib for live preview\n(pip install matplotlib)",
                         color=MUTED, size=10).pack(expand=True)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # stat bar
        stat_bar = tk.Frame(parent, bg=PANEL_BG, height=38)
        stat_bar.pack(fill="x"); stat_bar.pack_propagate(False)
        self._stats = []
        for col, (lbl, col_color) in enumerate([
                ("SPAN",""), ("HEIGHT",""), ("PANELS",""),
                ("TYPE",""), ("CHORD","")]):
            f = tk.Frame(stat_bar, bg=PANEL_BG)
            f.pack(side="left", fill="y", padx=1)
            tk.Frame(stat_bar, bg=BORDER, width=1).pack(side="left", fill="y")
            tk.Label(f, text=lbl, font=("Consolas",7),
                     fg=MUTED, bg=PANEL_BG).pack(anchor="w", padx=10, pady=(4,0))
            val = tk.Label(f, text="—", font=("Consolas",10,"bold"),
                           fg=ACCENT, bg=PANEL_BG)
            val.pack(anchor="w", padx=10)
            self._stats.append(val)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # log console
        log_hdr = tk.Frame(parent, bg="#060f1a", height=28)
        log_hdr.pack(fill="x"); log_hdr.pack_propagate(False)
        tk.Label(log_hdr, text="  OUTPUT LOG", font=("Consolas",8,"bold"),
                 fg=ACCENT2, bg="#060f1a").pack(side="left", pady=4)
        tk.Button(log_hdr, text="CLEAR", font=("Consolas",7),
                  fg=MUTED, bg="#060f1a", relief="flat",
                  cursor="hand2",
                  command=self._clear_log).pack(side="right", padx=8)

        self._log = scrolledtext.ScrolledText(
            parent, height=8, font=("Consolas",9),
            bg="#040b15", fg=TEXT, insertbackground=ACCENT,
            relief="flat", wrap="word",
            selectbackground=BORDER)
        self._log.pack(fill="both", expand=True, padx=2, pady=2)
        self._log.tag_config("error",   foreground=DANGER)
        self._log.tag_config("success", foreground=SUCCESS)
        self._log.tag_config("info",    foreground=ACCENT2)

        self._log_write("Bridge STAAD Builder ready.\n"
                        "Configure your bridge and click  ▶ RUN IN STAAD.PRO\n",
                        tag="info")

    # ── preview refresh ───────────────────────────────────────────────────────

    def _refresh_preview(self):
        # update stat bar
        vals = [
            f"{self.v_span.get():.0f} ft",
            f"{self.v_height.get():.0f} ft",
            str(self.v_panels.get()),
            self.v_btype.get().split()[0].upper(),
            self.v_chord.get(),
        ]
        colors = [ACCENT, ACCENT2, PURPLE, SUCCESS, ACCENT]
        for lbl, val, col in zip(self._stats, vals, colors):
            lbl.config(text=val, fg=col)

        if not HAS_MPL:
            return
        try:
            draw_preview_mpl(self._ax,
                             self.v_span.get(),
                             self.v_height.get(),
                             self.v_panels.get(),
                             self.v_btype.get())
            self._canvas.draw()
        except Exception:
            pass

    # ── log helpers ───────────────────────────────────────────────────────────

    def _log_write(self, msg, tag=None):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n", tag or "")
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    # ── run handler ───────────────────────────────────────────────────────────

    def _on_run(self):
        self._run_btn.config(state="disabled", text="⏳  Running …")
        self._status_dot.config(text="● RUNNING", fg=ACCENT)
        self._clear_log()
        self._log_write("Starting bridge model build …\n", tag="info")

        cfg = {
            "bridge_type" : self.v_btype.get(),
            "span"        : self.v_span.get(),
            "height"      : self.v_height.get(),
            "panels"      : self.v_panels.get(),
            "unit"        : self.v_unit.get(),
            "support_left": self.v_supp_l.get(),
            "support_right": self.v_supp_r.get(),
            "chord_sec"   : self.v_chord.get(),
            "diag_sec"    : self.v_diag.get(),
            "dead_load"   : self.v_dead.get(),
            "live_load"   : self.v_live.get(),
            "wind_load"   : self.v_wind.get(),
            "self_weight" : self.v_sw.get(),
        }

        def _worker():
            def log(msg, error=False, success=False):
                tag = "error" if error else ("success" if success else None)
                self.after(0, self._log_write, msg, tag)

            ok = run_in_staad(cfg, log)
            def _done():
                if ok:
                    self._status_dot.config(text="● DONE", fg=SUCCESS)
                else:
                    self._status_dot.config(text="● ERROR", fg=DANGER)
                self._run_btn.config(state="normal", text="▶  RUN IN STAAD.PRO")
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = BridgeSTAADApp()
    app.mainloop()

