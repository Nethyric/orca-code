#!/usr/bin/env python3
"""Build docs/ui-showcase.html from the captured ANSI transcripts.

Zero-dependency ANSI SGR → HTML converter + hand-styled showcase page.
Run:  python3 tools/build_showcase.py  (after capturing the .ans files)
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def palette256():
    p = {}
    base = ["000000", "800000", "008000", "808000", "000080", "800080",
            "008080", "c0c0c0", "808080", "ff0000", "00ff00", "ffff00",
            "0000ff", "ff00ff", "00ffff", "ffffff"]
    for i, c in enumerate(base):
        p[i] = c
    steps = [0, 95, 135, 175, 215, 255]
    i = 16
    for r in steps:
        for g in steps:
            for b in steps:
                p[i] = f"{r:02x}{g:02x}{b:02x}"
                i += 1
    for k in range(24):
        v = 8 + k * 10
        p[232 + k] = f"{v:02x}{v:02x}{v:02x}"
    return p


PAL = palette256()


def ansi_to_html(text: str) -> str:
    out, style, buf = [], {}, ""

    def flush():
        nonlocal buf
        if not buf:
            return
        css = []
        if style.get("b"):
            css.append("font-weight:700")
        if style.get("i"):
            css.append("font-style:italic")
        if style.get("d"):
            css.append("opacity:.62")
        if style.get("s"):
            css.append("text-decoration:line-through")
        if style.get("color"):
            css.append(f"color:#{style['color']}")
        if css:
            out.append(f'<span style="{";".join(css)}">{html.escape(buf)}</span>')
        else:
            out.append(html.escape(buf))
        buf = ""

    for tok in re.split(r"(\x1b\[[0-9;]*m)", text):
        if not tok:
            continue
        if tok.startswith("\x1b["):
            flush()
            parts = tok[2:-1].split(";")
            for j, code in enumerate(parts):
                if code == "0":
                    style.clear()
                elif code == "1":
                    style["b"] = 1
                elif code == "2":
                    style["d"] = 1
                elif code == "3":
                    style["i"] = 1
                elif code == "9":
                    style["s"] = 1
                elif code == "38" and j + 1 < len(parts):
                    if parts[j + 1] == "5" and j + 2 < len(parts):
                        style["color"] = PAL.get(int(parts[j + 2]), "ffffff")
                    elif parts[j + 1] == "2" and j + 4 < len(parts):
                        style["color"] = "".join(
                            f"{int(x):02x}" for x in parts[j + 2:j + 5])
                elif code in ("30", "31", "32", "33", "34", "35", "36", "37"):
                    style["color"] = PAL.get(int(code) - 30, "ffffff")
                elif code in ("90", "91", "92", "93", "94", "95", "96", "97"):
                    style["color"] = PAL.get(int(code) - 90 + 8, "ffffff")
        else:
            buf += tok
    flush()
    return "".join(out)


def terminal(title: str, body_html: str, height: str = "auto") -> str:
    return f"""
<div style="background:#171310;border:1px solid #2c241e;border-radius:14px;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.55),0 2px 8px rgba(0,0,0,.4);">
  <div style="display:flex;align-items:center;gap:8px;padding:11px 16px;background:#211b16;border-bottom:1px solid #2c241e;">
    <span style="width:12px;height:12px;border-radius:50%;background:#ff5f57;display:inline-block;"></span>
    <span style="width:12px;height:12px;border-radius:50%;background:#febc2e;display:inline-block;"></span>
    <span style="width:12px;height:12px;border-radius:50%;background:#28c840;display:inline-block;"></span>
    <span style="margin-left:10px;font:500 12px/1 ui-monospace,Menlo,monospace;color:#8b7d6d;">{html.escape(title)}</span>
    <span style="margin-left:auto;font:500 11px/1 ui-monospace,Menlo,monospace;color:#5d5348;border:1px solid #3a302a;border-radius:99px;padding:4px 10px;">ORCA_COLOR=force · theme dark</span>
  </div>
  <div style="overflow-x:auto;padding:20px 22px;background:#171310;">
    <pre style="margin:0;font:13px/1.6 ui-monospace,'SF Mono',Menlo,Consolas,'Cascadia Mono',monospace;color:#e9dfd2;white-space:pre;min-width:max-content;">{body_html}</pre>
  </div>
</div>"""


def card(title: str, body: str, accent: str = "#5fd7ff") -> str:
    return f"""
  <div style="background:#1a1512;border:1px solid #2c241e;border-radius:14px;padding:18px 20px;">
    <div style="font:700 12px/1 ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:{accent};margin-bottom:12px;">{title}</div>
    {body}
  </div>"""


def build() -> str:
    session = Path("/tmp/pretty-demo/session.ans").read_text(encoding="utf-8")
    print_mode = Path("/tmp/pretty-demo/print_mode.err").read_text(encoding="utf-8")
    t1 = terminal("orca — interactive session — dahl/MiniMaxAI/MiniMax-M2.7",
                  ansi_to_html(session))
    t2 = terminal('orca -p "why does test_zero fail?" — stderr lane',
                  ansi_to_html(print_mode))

    mono = "font:12.5px/1.7 ui-monospace,'SF Mono',Menlo,Consolas,monospace"

    themes_card = card("5 themes · deep ocean is the signature", f"""
    <div style="{mono};color:#e9dfd2;">
      <div><span style="color:#5fd7ff;">⏺ dark</span>   <span style="color:#94a3ad;">⎿ Deep Ocean — glacier ice, the default</span></div>
      <div><span style="color:#0e7490;">⏺ light</span>  <span style="color:#6e767d;">⎿ Arctic Day, for paper-white terminals</span></div>
      <div><span style="color:#d97757;">⏺ coral</span>  <span style="color:#6e767d;">⎿ warm, low-glare accents</span></div>
      <div><span style="color:#e5c07b;">⏺ ansi</span>   <span style="color:#6e767d;">⎿ zero hardcoded color — your 16 colors</span></div>
      <div><span style="color:#8b8177;">⏺ mono</span>   <span style="color:#6e767d;">⎿ glyphs without color</span></div>
    </div>""")

    syntax_card = card("Syntax highlighting — stdlib regex, ~120 lines", f"""
    <div style="{mono};color:#e9dfd2;">
      <div><span style="color:#94a3ad;"> 12 │</span> <span style="color:#c678dd;">def</span> <span style="color:#56b6c2;">divide</span>(a, b):</div>
      <div><span style="color:#94a3ad;"> 13 │</span>     <span style="color:#c678dd;">if</span> b == <span style="color:#5fd7ff;">0</span>:</div>
      <div><span style="color:#94a3ad;"> 14 │</span>         <span style="color:#c678dd;">raise</span> ValueError(<span style="color:#98c379;">"division by zero"</span>)</div>
      <div><span style="color:#94a3ad;"> 15 │</span>     <span style="color:#c678dd;">return</span> a / b  <span style="color:#8b8177;font-style:italic;"># guard added</span></div>
      <div style="margin-top:8px;color:#6e767d;">python · js/ts · json · shell · yaml</div>
    </div>""")

    meter_card = card("The water level — Orca's signature meter", f"""
    <div style="{mono};color:#e9dfd2;">
      <div>context ▏<span style="color:#98c379;">≈≈≈≈≈≈≈≈≈≈≈</span><span style="color:#e5c07b;">≈≈≈≈≈≈</span><span style="color:#94a3ad;">·····</span>▏ <span style="color:#98c379;"> 51%</span> · 65k/128k · <span style="color:#94a3ad;">63k left</span></div>
      <div>context ▏<span style="color:#98c379;">≈≈≈≈≈≈≈≈≈≈≈</span><span style="color:#e5c07b;">≈≈≈≈</span><span style="color:#e06c75;">≈≈≈≈</span><span style="color:#94a3ad;">·</span>▏ <span style="color:#e06c75;"> 84%</span> · 108k/128k · <span style="color:#94a3ad;">20k left</span><span style="color:#e5c07b;"> · ↻ /compact soon</span></div>
      <div style="margin-top:8px;"><span style="color:#5fd7ff;">🐋</span> <span style="color:#94a3ad;">4,080 in · 500 out · 2,048 cached (86% hit) · $0.0142</span></div>
    </div>""")

    spinner_card = card("A spinner with personality", f"""
    <div style="{mono};color:#e9dfd2;">
      <div><span style="color:#5fd7ff;">✻</span> Pondering… <span style="color:#94a3ad;">(0.4s)</span></div>
      <div><span style="color:#ffffff;">✳</span> Echolocating… <span style="color:#94a3ad;">(2.4s)</span></div>
      <div><span style="color:#89e8ce;">✶</span> Reading the currents… <span style="color:#94a3ad;">(4.8s)</span></div>
      <div><span style="color:#56b6c2;">✽</span> Hunting… <span style="color:#94a3ad;">(9.6s)</span></div>
    </div>""")

    todo_card = card("Compact todos, strike-through on done", f"""
    <div style="{mono};color:#e9dfd2;">
      <div><span style="font-weight:700;">⏺ Update Todos</span></div>
      <div>  <span style="color:#94a3ad;">⎿</span> <span style="color:#98c379;">☒</span> <span style="color:#8b8177;text-decoration:line-through;">Read calc.py and find the bug</span></div>
      <div>  <span style="color:#94a3ad;">⎿</span> <span style="color:#5fd7ff;font-weight:700;">◐</span> <span style="font-weight:700;">Add a zero-division guard</span></div>
      <div>  <span style="color:#94a3ad;">⎿</span> <span style="color:#8b8177;">☐</span> Run the tests</div>
    </div>""")

    dialog_card = card("Diff-review permission dialogs", f"""
    <div style="{mono};color:#e9dfd2;">
      <div><span style="color:#5fd7ff;">╭──────────────</span><span style="color:#5fd7ff;font-weight:700;"> edit_file </span><span style="color:#5fd7ff;">─╮</span></div>
      <div>│ <span style="color:#94a3ad;">path   </span><span style="color:#56b6c2;">calc.py</span>             │</div>
      <div>│ <span style="color:#94a3ad;">old    </span><span style="color:#56b6c2;">'return a / b'</span>       │</div>
      <div><span style="color:#5fd7ff;">├── change ────┤</span></div>
      <div>│  <span style="color:#98c379;">+    if b == 0:</span>       │</div>
      <div>│  <span style="color:#98c379;">+        raise ValueError(...)</span>│</div>
      <div><span style="color:#5fd7ff;">╰──────────────╯</span></div>
      <div style="margin-top:8px;">  <span style="font-weight:700;">1</span>. Yes   <span style="font-weight:700;">2</span>. Always this session   <span style="font-weight:700;">3</span>. Always + save   <span style="font-weight:700;">4</span>. No</div>
    </div>""")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orca Code — UI showcase</title></head>
<body style="margin:0;background:#0d0a08;padding:44px 20px 60px;">
<div style="max-width:1060px;margin:0 auto;">

  <div style="text-align:center;margin-bottom:34px;">
    <div style="font:700 15px/1 ui-monospace,Menlo,monospace;letter-spacing:.3em;text-transform:uppercase;color:#5fd7ff;margin-bottom:14px;">🐋 orca code v0.0.1</div>
    <div style="font:800 clamp(26px,5vw,40px)/1.15 system-ui,-apple-system,'Segoe UI',sans-serif;color:#f2e9dc;max-width:720px;margin:0 auto 12px;">Deep Ocean. A look that belongs to Orca alone.</div>
    <div style="font:15px/1.6 system-ui,sans-serif;color:#a08e7c;max-width:620px;margin:0 auto;">Glacier-ice on dark water — the orca's own palette. Wave meters, syntax-highlighted everything, diff-review dialogs, five themes (one finally respects your terminal's own palette) — all pure ANSI, zero dependencies, Python stdlib only.</div>
  </div>

  {t1}

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:14px;">
    {themes_card}
    {syntax_card}
    {meter_card}
    {spinner_card}
    {todo_card}
    {dialog_card}
  </div>

  <div style="font:700 12px/1 ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:#5fd7ff;margin:36px 0 14px;">non-interactive · orca -p</div>
  {t2}

  <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:30px;justify-content:center;">
    <span style="font:600 12px/1 ui-monospace,monospace;color:#98c379;border:1px solid #2f3d2f;border-radius:99px;padding:8px 14px;">zero dependencies</span>
    <span style="font:600 12px/1 ui-monospace,monospace;color:#56b6c2;border:1px solid #2b3a3d;border-radius:99px;padding:8px 14px;">148 tests green</span>
    <span style="font:600 12px/1 ui-monospace,monospace;color:#d97757;border:1px solid #4a3328;border-radius:99px;padding:8px 14px;">31 providers incl. Gemini, Grok, Kimi</span>
    <span style="font:600 12px/1 ui-monospace,monospace;color:#c678dd;border:1px solid #3d2f45;border-radius:99px;padding:8px 14px;">prompt caching + hit-rate</span>
    <span style="font:600 12px/1 ui-monospace,monospace;color:#e5c07b;border:1px solid #453a2b;border-radius:99px;padding:8px 14px;">hard $ cost cap</span>
  </div>
</div>
</body></html>"""


if __name__ == "__main__":
    out = ROOT / "docs" / "ui-showcase.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
