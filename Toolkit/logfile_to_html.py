# ==========================================================
# 🛠️ Tool: Logcat logfile to html Convertor
# 👤 Author: Eden Kim
# 📅 Date: 2025-11-24 - 해시 기반 태그별 고정 색상 패치, 시간 외 날짜도 출력 되도록 수정
# • 목적: 로그캣 로그파일(txt) → 컬러 스타일 HTML 변환기
# • 특징: 컬러 스타일 - 레벨 배지(배경색포함), 태그 컬러, 메시지 강조
# • 포맷: epoch/std/res_ts + generic
# • 입력: logcat -v epoch/std + meminfo(top)
# • 산출물: log.html
# • 주의: Windows 10 이상, 콘솔 폰트는 고정폭 권장
# ==========================================================
# -*- coding: utf-8 -*-
"""
logfile_to_html.py (rev3 - level badge with background, tag colored text)
"""
import sys, os, re, argparse, html, subprocess, webbrowser
from datetime import datetime
import zlib  # 태그 색상 해시용

TPL = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Logcat Logfile Convert</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --bg: #0e1116; --fg: #e6e6e6; --muted:#9aa0a6;
  --badge-V-bg:#616161; --badge-V-fg:#ffffff;
  --badge-D-bg:#1565c0; --badge-D-fg:#ffffff;
  --badge-I-bg:#2e7d32; --badge-I-fg:#000000;
  --badge-W-bg:#f9a825; --badge-W-fg:#000000;
  --badge-E-bg:#c62828; --badge-E-fg:#ffffff;
  --badge-F-bg:#6a1b9a; --badge-F-fg:#ffffff;
  --badge-A-bg:#6a1b9a; --badge-A-fg:#ffffff;
  --step:#26c6da; --anr:#ab47bc; --crash:#ff1744; --gc:#90a4ae;
  --tag:#80cbc4; --row-alt:#11151c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace}
.toolbar{position:sticky;top:0;background:#0b0e13ee;padding:8px 12px;backdrop-filter: blur(8px);display:flex;gap:16px;align-items:center;border-bottom:1px solid #1a1f29;z-index:10}
.toolbar label{font-size:12px;color:var(--muted)}
.container{padding:12px}
.line{
  white-space:pre-wrap;
  word-break:break-word;
  padding:2px 8px;
  border-radius:6px;
}
.line:nth-child(odd){background:var(--row-alt)}
.time{color:var(--muted);padding-right:8px}
.lvl{display:inline-block;min-width:16px;text-align:center;border-radius:4px;padding:0 6px;margin-right:8px;font-weight:700}
.lvl.V{background:var(--badge-V-bg);color:var(--badge-V-fg)}
.lvl.D{background:var(--badge-D-bg);color:var(--badge-D-fg)}
.lvl.I{background:var(--badge-I-bg);color:var(--badge-I-fg)}
.lvl.W{background:var(--badge-W-bg);color:var(--badge-W-fg)}
.lvl.E{background:var(--badge-E-bg);color:var(--badge-E-fg)}
.lvl.F,.lvl.A{background:var(--badge-F-bg);color:var(--badge-F-fg)}
.tag{color:var(--tag);margin-right:8px}
.msg.step{color:var(--step)}
.msg.anr{color:var(--anr)}
.msg.crash{color:var(--crash);font-weight:700}
.msg.gc{color:var(--gc)}
.hidden{display:none}
.count{font-size:12px;color:var(--muted)}
input[type=checkbox]{vertical-align:middle}
.search{padding:4px 8px;border-radius:6px;border:1px solid #2a3140;background:#0e141e;color:var(--fg)}
</style>
</head>
<body>
<div class="toolbar">
  <label><input type="checkbox" id="showI" checked> I</label>
  <label><input type="checkbox" id="showW" checked> W</label>
  <label><input type="checkbox" id="showE" checked> E/F</label>
  <label><input type="checkbox" id="showD"> D/V</label>
  <label><input type="checkbox" id="showSTEP" checked> STEP</label>
  <label><input type="checkbox" id="showANR" checked> ANR</label>
  <label><input type="checkbox" id="showCRASH" checked> CRASH</label>
  <label><input type="checkbox" id="showGC" checked> GC</label>
  <input class="search" id="q" placeholder="검색(정규식)" />
  <span class="count" id="count"></span>
</div>
<div class="container" id="log">
{LINES}
</div>
<script>
function applyFilters(){
  const show = {
    I: document.getElementById('showI').checked,
    W: document.getElementById('showW').checked,
    E: document.getElementById('showE').checked,
    D: document.getElementById('showD').checked,
    STEP: document.getElementById('showSTEP').checked,
    ANR: document.getElementById('showANR').checked,
    CRASH: document.getElementById('showCRASH').checked,
    GC: document.getElementById('showGC').checked,
  };
  const q = document.getElementById('q').value;
  let re = null;
  if(q){try{re = new RegExp(q,'i')}catch(e){re=null}}
  let visible = 0;
  document.querySelectorAll('.line').forEach(el=>{
    const lvl = el.getAttribute('data-lvl') || 'I';
    const cls = el.getAttribute('data-cls') || '';
    const text = el.textContent || '';
    let ok = true;
    if(lvl==='I' && !show.I) ok=false;
    if((lvl==='W') && !show.W) ok=false;
    if((lvl==='E' || lvl==='F' || lvl==='A') && !show.E) ok=false;
    if((lvl==='D' || lvl==='V') && !show.D) ok=false;
    if(cls.includes('step') && !show.STEP) ok=false;
    if(cls.includes('anr') && !show.ANR) ok=false;
    if(cls.includes('crash') && !show.CRASH) ok=false;
    if(cls.includes('gc') && !show.GC) ok=false;
    if(re && !re.test(text)) ok=false;
    el.classList.toggle('hidden', !ok);
    if(ok) visible++;
  });
  document.getElementById('count').textContent = visible + ' lines';
}
['showI','showW','showE','showD','showSTEP','showANR','showCRASH','showGC','q']
  .forEach(id=>document.getElementById(id).addEventListener('input', applyFilters));
applyFilters();
</script>
</body>
</html>
"""

re_epoch = re.compile(r"^\s*(?P<epoch>\d+(?:\.\d+)?)\s+\d+\s+\d+\s+(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$")
re_std   = re.compile(r"^\s*(?P<md>\d{2}-\d{2})\s+(?P<hms>\d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$")
re_res_ts= re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

def fmt_time_epoch(e):
    try: return datetime.fromtimestamp(float(e)).strftime("%H:%M:%S")
    except: return "??:??:??"

# ── 태그 색상 팔레트 (GUI와 동일) ──
C = {
    "gray":"#9aa0a6","red":"#ff4d4f","red2":"#ff7875","yellow":"#ffc53d","amber":"#d49b00",
    "green":"#52c41a","lime":"#86e57f","blue":"#40a9ff","indigo":"#3b82f6","teal":"#20c997",
    "cyan":"#13c2c2","violet":"#8a2be2","magenta":"#c53db7","orange":"#ffa940",
    "white":"#f0f0f0","black":"#000000"
}

# HTML/CSS 쪽 기본 태그색은 --tag 로 남겨두되,
# 여기서는 태그마다 다른 색을 주기 위해 별도 팔레트 사용
TAG_COLOR_POOL = [
    "blue", "green", "teal", "cyan", "magenta",
    "orange", "indigo", "lime", "yellow", "red2",
]

def tag_color_name(tag: str) -> str:
    """
    태그 문자열만으로 항상 동일한 색상을 결정하는 해시 기반 매핑.
    resource_monitor_gui / logfile_viewer_gui 와 동일한 로직.
    """
    if not tag:
        return "gray"

    t = str(tag).strip()
    h = zlib.adler32(t.encode("utf-8")) & 0xffffffff
    idx = h % len(TAG_COLOR_POOL)
    return TAG_COLOR_POOL[idx]

def classify(msg):
    cls=[]
    if "[STEP]" in msg: cls.append("step")
    if "FATAL EXCEPTION" in msg or "CRASH" in msg: cls.append("crash")
    if "ANR in " in msg or re.search(r"\bANR\b", msg): cls.append("anr")
    if " GC_" in msg or "concurrent copying GC" in msg or "Concurrent mark sweep" in msg: cls.append("gc")
    return " ".join(cls)

def to_html_line(raw):
    s = raw.rstrip("\r\n")
    if not s:
        return ""

    # 1) logcat -v epoch
    m = re_epoch.match(s)
    if m:
        t   = fmt_time_epoch(m.group("epoch"))  # HH:MM:SS (epoch는 날짜 정보 없음)
        lvl = m.group("lvl")
        tag = m.group("tag").strip()
        msg = m.group("msg")

        cls     = classify(msg)
        msg_esc = html.escape(msg)

        color_name = tag_color_name(tag)
        tag_color  = C.get(color_name, "#80cbc4")  # CSS 기본값을 fallback

        return (
            f'<div class="line" data-lvl="{lvl}" data-cls="{cls}">'
            f'<span class="time">{html.escape(t)}</span>'
            f'<span class="lvl {lvl}">{lvl}</span>'
            f'<span class="tag" style="color:{tag_color};">{html.escape(tag)}</span>'
            f'<span class="msg {cls}">{msg_esc}</span>'
            f'</div>'
        )

    # 2) logcat -v threadtime (std)
    m2 = re_std.match(s)
    if m2:
        md  = m2.group("md")   # MM-DD
        hms = m2.group("hms")  # HH:MM:SS.mmm
        t   = f"{md} {hms}"    # ⇒ MM-DD HH:MM:SS.mmm (리소스모니터GUI와 동일)

        lvl = m2.group("lvl")
        tag = m2.group("tag").strip()
        msg = m2.group("msg")

        cls     = classify(msg)
        msg_esc = html.escape(msg)

        color_name = tag_color_name(tag)
        tag_color  = C.get(color_name, "#80cbc4")

        return (
            f'<div class="line" data-lvl="{lvl}" data-cls="{cls}">'
            f'<span class="time">{html.escape(t)}</span>'
            f'<span class="lvl {lvl}">{lvl}</span>'
            f'<span class="tag" style="color:{tag_color};">{html.escape(tag)}</span>'
            f'<span class="msg {cls}">{msg_esc}</span>'
            f'</div>'
        )

    # 3) resource_monitor / meminfo 스타일 [YYYY-MM-DD HH:MM:SS] 라인
    m3 = re_res_ts.match(s)
    if m3:
        t    = m3.group("ts")[11:19]  # HH:MM:SS 만 (이 포맷은 원래 이렇게 쓰던 거 유지)
        body = s
        lvl  = "I"
        cls  = ""
        if "TOTAL" in body:
            cls = "total"
        if "WARN" in body:
            lvl = "W"
        if "CRIT" in body:
            lvl = "E"
        body_esc = html.escape(body)
        return (
            f'<div class="line" data-lvl="{lvl}" data-cls="{cls}">'
            f'<span class="time">{html.escape(t)}</span>'
            f'<span class="lvl {lvl}">{lvl}</span>'
            f'<span class="msg">{body_esc}</span>'
            f'</div>'
        )

    # 4) 그 외 일반 텍스트
    lvl   = "I"
    cls   = classify(s)
    s_esc = html.escape(s)
    return (
        f'<div class="line" data-lvl="{lvl}" data-cls="{cls}">'
        f'<span class="lvl {lvl}">{lvl}</span>'
        f'<span class="msg">{s_esc}</span>'
        f'</div>'
    )

def _pick_file_dialog():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw()
        return filedialog.askopenfilename(title="로그 파일 선택", filetypes=[("Text/Log","*.txt *.log *.out *.lst *.logcat"),("All","*.*")]) or None
    except Exception:
        return None

def main():
    ap=argparse.ArgumentParser(description="Convert Logcat logfile to HTML")
    ap.add_argument("file", nargs="?", help="입력 로그(미지정 시 파일 선택창)")
    ap.add_argument("-o","--out", help="출력 HTML 경로(미지정 시 입력경로+.html)")
    args=ap.parse_args()

    in_path = args.file or _pick_file_dialog()
    if not in_path or not os.path.exists(in_path):
        print("❌ 입력 파일이 없습니다."); sys.exit(1)

    out = args.out or (in_path + ".html")

    lines=[]
    with open(in_path,encoding="utf-8",errors="ignore") as f:
        for line in f:
            h=to_html_line(line)
            if h: lines.append(h)

    html_text = TPL.replace("{LINES}", "\n".join(lines))
    with open(out,"w",encoding="utf-8") as w: w.write(html_text)
    print("✅ HTML 생성:", out)

    # (파일 저장/print 직후) 자동 실행
    try:
        if os.name == "nt":
            os.startfile(out)  # Windows
        elif sys.platform == "darwin":
            subprocess.run(["open", out], check=False)
        else:
            subprocess.run(["xdg-open", out], check=False)
    except Exception:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:
            pass

if __name__=="__main__":
    main()
