# ==========================================================
# 🖥️ Tool: Logcat logfile GUI Color Viewer
# 👤 Author: Eden Kim
# 📅 Date: 2026-08-11
#   - 고해상도 화면 흐림 해결: DPI 인식 선언 + Tk scaling/창크기 연동
#   - HTML 변환 호출 시 뜨던 cmd 창 제거
# 📅 Date: 2026-01-07
#   - run.log 전용 토큰 하이라이트 추가, 폰트 변경
# ==========================================================
# • 포맷: logcat -v epoch / threadtime(std) / 기타 텍스트
# • 기능: 검색, 레벨/STEP/ANR/CRASH/GC 필터, tail -f, 레벨/태그/메시지 컬러, 메시지 강조
# • 특징: Tkinter GUI, 대용량 파일 대응, elide 필터링 지원
# • 주의: Windows 10 이상, 콘솔 폰트는 고정폭 권장
# ==========================================================
import sys, os, re, argparse, io, tkinter as tk
from tkinter import ttk, filedialog, messagebox  # ⬅ messagebox 추가
import tkinter.font as tkfont
from datetime import datetime
import zlib  # 태그 색상 해시용
import subprocess  # ⬅ HTML 변환 스크립트 호출용

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qa_gui_util import (enable_dpi_awareness, apply_tk_scaling, scale_geometry,
                         silence_console_windows, relaunch_without_console, console_python)

# ⚠ Tk 창(파일 선택 다이얼로그의 숨은 root 포함)이 만들어지기 전에 확정되어야 한다
relaunch_without_console()   # exe 런처가 py.exe로 실행해 딸려온 콘솔 창 제거(먼저 처리)
UI_SCALE = enable_dpi_awareness()
silence_console_windows()

# ── Color Palette ────────────────────────────────────────
C = {
    "gray":"#9aa0a6","red":"#ff4d4f","red2":"#ff7875","yellow":"#ffc53d","amber":"#d49b00",
    "green":"#52c41a","lime":"#86e57f","blue":"#40a9ff","indigo":"#3b82f6","teal":"#20c997",
    "cyan":"#13c2c2","violet":"#8a2be2","magenta":"#c53db7","orange":"#ffa940",
    "white":"#f0f0f0","black":"#000000"
}
LVL_BG = {"V":"gray","D":"blue","I":"green","W":"yellow","E":"red","F":"magenta","A":"magenta"}
LVL_FG = {"V":"white","D":"white","I":"black","W":"black","E":"white","F":"white","A":"white"}

# ── 태그별 고정 색상 (해시 기반, 모든 뷰어에서 공통 사용) ──
TAG_COLOR_POOL = [
    "blue", "green", "teal", "cyan", "magenta",
    "orange", "indigo", "lime", "yellow", "red2",
]

def tag_color_name(tag: str) -> str:
    """
    태그 문자열만으로 항상 동일한 색상을 결정하는 해시 기반 매핑.
    - 실행 환경, 로그 순서와 무관하게 같은 태그면 항상 같은 색.
    - TAG_COLOR_POOL + 이 함수만 동일하게 쓰면
      resource_monitor_gui, logfile_viewer_gui, logfile_to_html 어디서든 색이 일치한다.
    """
    if not tag:
        return "gray"

    t = str(tag).strip()
    h = zlib.adler32(t.encode("utf-8")) & 0xffffffff  # 안정적인 해시
    idx = h % len(TAG_COLOR_POOL)
    return TAG_COLOR_POOL[idx]

# ── Regex ────────────────────────────────────────────────
PAT_STEP  = re.compile(r"\[STEP\]")
PAT_ANR   = re.compile(r"\bANR\b|\bANR in\b")
PAT_CRASH = re.compile(r"FATAL EXCEPTION|CRASH")
PAT_GC    = re.compile(r"\bGC_|\bconcurrent copying GC\b|Concurrent mark sweep", re.I)

RE_EPOCH = re.compile(r"^\s*(?P<epoch>\d+(?:\.\d+)?)\s+\d+\s+\d+\s+(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$")
RE_STD   = re.compile(r"^\s*(?P<md>\d{2}-\d{2})\s+(?P<hms>\d{2}:\d{2}:\d{2})\.\d+\s+\d+\s+\d+\s+(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$")

RE_STD   = re.compile(
    r"^\s*(?P<md>\d{2}-\d{2})\s+"
    r"(?P<hms>\d{2}:\d{2}:\d{2})\.(?P<ms>\d+)\s+"
    r"\d+\s+\d+\s+"
    r"(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$"
)
# [ADD] run.log 전용: 메시지 내 [TAG] 및 결과 토큰 하이라이트
RE_BRACKET_TAG   = re.compile(r"\[[^\]\r\n]{1,80}\]")   # [ ... ] 토큰
RE_BRACKET_CLOCK = re.compile(r"\[\d{2}:\d{2}:\d{2}\]") # [15:18:24] 같은 시간 토큰(제외)

RE_RUNLOG_WORD = re.compile(
    r"\bPASS\b|\bFAIL\b|\bWARN\b|"
    r"(?<![가-힣A-Za-z0-9])성공(?![가-힣A-Za-z0-9])|"
    r"(?<![가-힣A-Za-z0-9])실패(?![가-힣A-Za-z0-9])"
)

# 단색 심볼(색 적용 가능성이 높은 것만)
RE_RUNLOG_ICON = re.compile(r"☑|✔|✓|✖|×|⚠️|⚠|❌|⛔|✅")

def _fmt_epoch(v:str):
    try: return datetime.fromtimestamp(float(v)).strftime("%H:%M:%S")
    except: return "??:??:??"

def parse_threadtime_line(line: str):
    """
    threadtime 포맷 한 줄을 파싱해서
    ts, lvl, tag, msg 를 반환한다.
    ts 형식: 'MM-DD HH:MM:SS.mmm'
    """
    m = RE_THREADTIME.match(line)
    if not m:
        return None

    md  = m.group("md")
    hms = m.group("hms")
    ts  = f"{md} {hms}"

    lvl = m.group("lvl")
    tag = m.group("tag").strip()
    msg = m.group("msg")

    return ts, lvl, tag, msg

# ── logfile_to_html 스크립트 자동 탐색 ─────────────────────────
def _find_logfile_to_html(base_dir: str) -> str | None:
    """
    base_dir에서 logfile_to_html(.py / _YYMMDD-hhmm.py)를 찾아서
    가장 최신 파일 하나를 돌려준다.
    """
    # 1) 고정 이름 우선
    cand = os.path.join(base_dir, "logfile_to_html.py")
    if os.path.exists(cand):
        return cand

    # 2) 타임스탬프 버전 중 최신
    try:
        files = [
            fn for fn in os.listdir(base_dir)
            if re.match(r"logfile_to_html_\d{6}-\d{4}\.py$", fn)
        ]
    except Exception:
        return None

    if not files:
        return None

    files.sort(reverse=True)

# ── Main Viewer ──────────────────────────────────────────
class LogViewer(tk.Tk):
    def __init__(self, path, follow=False, batch=800, filter_mode="rerender"):
        super().__init__()
        self.path = os.path.abspath(path)  # ⬅ 원본 로그 파일 경로 보관
        self.is_runlog = (os.path.basename(self.path).lower() == "run.log")
        self.title(f"Log Viewer - {os.path.basename(path)}")
        apply_tk_scaling(self, UI_SCALE)
        self.geometry(scale_geometry("1180x760", UI_SCALE))

        # UI 상단
        bar = ttk.Frame(self); bar.pack(side=tk.TOP, fill=tk.X)

        # 🔹 오른쪽 끝에 HTML 저장 버튼
        ttk.Button(bar, text="HTML 저장", command=self.export_html).pack(
            side=tk.RIGHT, padx=4
        )

        ttk.Label(bar, text="검색:").pack(side=tk.LEFT, padx=4)
        self.q = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.q, width=34)
        entry.pack(side=tk.LEFT)
        entry.bind("<Return>",    lambda e: self.on_search())  # ✅ Enter
        entry.bind("<KP_Enter>",  lambda e: self.on_search())  # ✅ Numpad Enter
        ttk.Button(bar, text="찾기", command=self.on_search).pack(side=tk.LEFT, padx=4)

        # 필터 체크박스
        self.filter_vars = {}
        for k in ["V","D","I","W","E","F","A","STEP","ANR","CRASH","GC"]:
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(bar, text=k, variable=v, command=self.on_filter_toggle).pack(side=tk.LEFT, padx=2)
            self.filter_vars[k] = v

        # 텍스트 위젯
        self.text = tk.Text(self, bg="black", fg="white", wrap="word", undo=False)
                # "Malgun Gothic",
                # "D2Coding",
                # "D2Coding Ligature",
                # "NanumGothicCoding",
                # "Noto Sans Mono CJK KR",
                # "Cascadia Mono",   # 한글 포함은 약할 수 있음(폴백 발생 가능)
                # "Consolas"
        self.text.configure(font=("Malgun Gothic", 10), spacing1=2)
        sy = ttk.Scrollbar(self, command=self.text.yview); self.text["yscrollcommand"]=sy.set
        sy.pack(side=tk.RIGHT, fill=tk.Y); self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 상태값
        self.follow = follow
        self.fp = io.open(self.path, "r", encoding="utf-8", errors="ignore", buffering=1<<20)
        self.batch = max(50, batch)
        self.items = []   # 파싱 결과 버퍼 ([(hhmmss,lvl,tag,msg,cat), ...])
        self.filter_mode = filter_mode  # "rerender" | "elide"
        self.supports_elide = True  # elide 지원 여부 (프로빙 후 결정)
        self.search_pos = None

        self._init_tags()

        # elide 모드 요청 시에만 프로빙
        if self.filter_mode == "elide":
            self.supports_elide = self._probe_elide()
            if not self.supports_elide:
                self.filter_mode = "rerender"  # 안전 폴백

        # 초기 표시
        self.after(30, self.read_loop)

    # ── 태그 초기화 ─────────────────────────────
    def _init_tags(self):
        self.text.tag_configure("ts", foreground=C["gray"])
        for lv in "VDIWEFA":
            self.text.tag_configure(f"badge_{lv}", foreground=C[LVL_FG[lv]], background=C[LVL_BG[lv]])
        self.text.tag_configure("tag_default", foreground=C["gray"])

        # 태그별 색상은 라인 렌더링 시 tag_color_name()으로 동적 생성
        self.text.tag_configure("msg_step",  foreground=C["cyan"])
        self.text.tag_configure("msg_anr",   foreground=C["magenta"])
        self.text.tag_configure("msg_crash", foreground=C["red2"])
        self.text.tag_configure("msg_gc",    foreground=C["gray"])
        self.text.tag_configure("hl", background="yellow", foreground="black")
        # elide용 카테고리 태그 (elide 모드에서만 사용)
        for cat in ["V","D","I","W","E","F","A","STEP","ANR","CRASH","GC"]:
            self.text.tag_configure(f"cat_{cat}", elide=False)

    # run.log 전용 토큰 스타일 설정
    def _style_runlog_token(self, key: str, fg_hex: str):
        """run.log용 토큰 스타일(글자색만)."""
        style = f"runlog_{key}"
        if style not in self.text.tag_names():
            self.text.tag_configure(style, foreground=fg_hex)
            self.text.tag_raise(style)
        return style

    def _insert_runlog_highlight(self, msg: str, base_style: str | None = None):
        """
        run.log 전용:
        - msg를 토큰 단위로 쪼개 insert(후처리 tag_add 안 씀)
        - [TAG]는 '[]'는 기본, 내부 글자만 색상
        - FIXED_TAG 고정색, 그 외 태그는 해시색
        - FIXED_WORD 단어도 고정색
        """
        if not msg:
            return

        FIXED_TAG = {  # 결과 성격 태그 고정색
            "ERR": "red",
            "ERROR": "red",
            "WARN": "orange",
            "WARNING": "orange",
            "SCROLL": "orange",
            "RISK": "orange",
            "TYPE": "orange",
            "ACCT": "orange",
            "RUN": "indigo",
            "SUB": "cyan",
            "OK": "green",
            "CLICK": "green",
            "RECOVERY": "green",
            "런처": "yellow",
            "Basic Test / 노출": "blue",
            "Basic Test / 기능": "blue",
            "BLOCK": "violet",
            "EXC-ACT": "violet",
            "EXC": "violet",
            "CHECK_CORE": "magenta",
            "CLICK_CORE": "magenta",
        }
        FIXED_TAG_UP = {k.upper(): v for k, v in FIXED_TAG.items()}

        FIXED_WORD = {  # 결과 단어 고정색
            "PASS": "green",
            "FAIL": "red",
            "WARN": "orange",
            "성공": "green",
            "실패": "red",
        }

        # 심볼도 가능한 범위에서 색상 부여
        FIXED_ICON = {
            "☑": "green", "✔": "green", "✓": "green", "✅": "green",
            "✖": "red", "×": "red", "❌": "red", "⛔": "red",
            "⚠": "orange", "⚠️": "orange",
        }

        # 한 번의 스캔으로 [TAG] / 단어 / 심볼을 모두 처리
        # (가장 먼저 나오는 토큰을 순서대로 소비)
        idx = 0
        while idx < len(msg):
            # 다음 매치 후보 3개를 각각 찾고, 가장 앞선 것을 선택
            m_tag  = RE_BRACKET_TAG.search(msg, idx)
            m_word = RE_RUNLOG_WORD.search(msg, idx)
            m_ico  = RE_RUNLOG_ICON.search(msg, idx)

            candidates = [m for m in (m_tag, m_word, m_ico) if m]
            if not candidates:
                # 남은 꼬리
                tail = msg[idx:]
                if base_style:
                    self.text.insert(tk.END, tail, base_style)
                else:
                    self.text.insert(tk.END, tail)
                break

            m = min(candidates, key=lambda x: x.start())

            # 토큰 앞 일반 텍스트
            if m.start() > idx:
                chunk = msg[idx:m.start()]
                if base_style:
                    self.text.insert(tk.END, chunk, base_style)
                else:
                    self.text.insert(tk.END, chunk)

            token = m.group(0)

            # 1) [TAG] 처리: []는 기본, 내부 글자만 색
            if m is m_tag:
                if RE_BRACKET_CLOCK.fullmatch(token):
                    # 시간 토큰은 그냥 출력
                    if base_style:
                        self.text.insert(tk.END, token, base_style)
                    else:
                        self.text.insert(tk.END, token)
                    idx = m.end()
                    continue

                inner = token[1:-1]  # 대괄호 제외
                inner_strip = inner.strip()
                if not inner_strip:
                    # 빈 태그면 그냥 출력
                    if base_style:
                        self.text.insert(tk.END, token, base_style)
                    else:
                        self.text.insert(tk.END, token)
                    idx = m.end()
                    continue

                up = inner_strip.upper()

                # 고정 태그 색 우선
                if up in FIXED_TAG_UP:
                    cname = FIXED_TAG_UP[up]
                else:
                    # 기타 태그: 해시 기반(회색 없음)
                    cname = tag_color_name(inner_strip)

                fg = C.get(cname, C["white"])
                style = self._style_runlog_token(f"tag_{zlib.adler32(inner_strip.encode('utf-8')) & 0xffffffff}", fg)

                # '['
                if base_style:
                    self.text.insert(tk.END, "[", base_style)
                else:
                    self.text.insert(tk.END, "[")

                # 내부 글자(색상)
                if base_style:
                    self.text.insert(tk.END, inner, (base_style, style))
                else:
                    self.text.insert(tk.END, inner, style)

                # ']'
                if base_style:
                    self.text.insert(tk.END, "]", base_style)
                else:
                    self.text.insert(tk.END, "]")

                idx = m.end()
                continue

            # 2) 결과 단어 처리
            if m is m_word:
                key = token
                # token이 WARN/PASS/FAIL 이외로 들어올 일은 없지만 안전 처리
                cname = FIXED_WORD.get(key, "white")
                fg = C.get(cname, C["white"])
                style = self._style_runlog_token(f"word_{key}", fg)

                if base_style:
                    self.text.insert(tk.END, token, (base_style, style))
                else:
                    self.text.insert(tk.END, token, style)

                idx = m.end()
                continue

            # 3) 심볼 처리(가능한 범위에서만)
            if m is m_ico:
                cname = FIXED_ICON.get(token)
                if cname:
                    fg = C.get(cname, C["white"])
                    style = self._style_runlog_token(f"ico_{ord(token[0])}", fg)
                    if base_style:
                        self.text.insert(tk.END, token, (base_style, style))
                    else:
                        self.text.insert(tk.END, token, style)
                else:
                    if base_style:
                        self.text.insert(tk.END, token, base_style)
                    else:
                        self.text.insert(tk.END, token)

                idx = m.end()
                continue


    # ── HTML 저장 (logfile_to_html 연동) ─────────────────────
    def export_html(self):
        # 1) 원본 로그 경로 체크
        in_path = getattr(self, "path", None)
        if not in_path or not os.path.exists(in_path):
            messagebox.showerror("HTML 저장", "원본 로그 파일 경로를 찾지 못했습니다.")
            return

        # 2) 변환 스크립트 찾기
        script_dir = os.path.dirname(os.path.abspath(__file__))
        conv = _find_logfile_to_html(script_dir)
        if not conv or not os.path.exists(conv):
            messagebox.showerror(
                "HTML 저장",
                "logfile_to_html(.py) 스크립트를 찾지 못했습니다.\n"
                "같은 폴더에 logfile_to_html.py 또는 logfile_to_html_YYMMDD-hhmm.py 가 있는지 확인해 주세요."
            )
            return

        # 3) 저장 경로 선택 (기본: 원본파일명 + .html)
        default_out = in_path + ".html"
        out_path = filedialog.asksaveasfilename(
            title="HTML로 저장",
            initialfile=os.path.basename(default_out),
            defaultextension=".html",
            filetypes=[("HTML 파일", "*.html"), ("All files", "*.*")]
        )
        if not out_path:
            return  # 사용자가 취소

        # 4) logfile_to_html 그대로 호출 (브라우저 오픈까지 맡김)
        pyexe = console_python()   # pythonw로 띄우면 손자 프로세스가 콘솔 창을 만든다
        try:
            subprocess.run(
                [pyexe, "-u", conv, in_path, "-o", out_path],
                check=True,
                cwd=script_dir
            )
            # logfile_to_html 쪽에서 이미 브라우저 오픈을 시도하므로 여기서는 안내만
            messagebox.showinfo("HTML 저장", f"HTML 저장 완료:\n{out_path}")
        except subprocess.CalledProcessError as e:
            messagebox.showerror(
                "HTML 저장",
                f"HTML 변환 중 오류가 발생했습니다.\n\n{e}"
            )
        except Exception as e:
            messagebox.showerror(
                "HTML 저장",
                f"실행 오류가 발생했습니다.\n\n{e}"
            )

    # ── elide 지원 여부 판정 ───────────────────
    def _probe_elide(self)->bool:
        start = self.text.index(tk.END)
        self.text.insert(tk.END, "ELIDE_PROBE\n")
        end = self.text.index(tk.END)
        self.text.tag_add("probe", start, end)
        self.text.tag_configure("probe", elide=True)
        self.update_idletasks()
        hidden = (self.text.bbox(start) is None)
        self.text.delete(start, end)
        return bool(hidden)

    # ── 카테고리 판정 ───────────────────────────
    def _categorize(self, lvl, msg):
        if   PAT_CRASH.search(msg): return "CRASH"
        elif PAT_ANR.search(msg):   return "ANR"
        elif PAT_GC.search(msg):    return "GC"
        elif PAT_STEP.search(msg):  return "STEP"
        return lvl if lvl in "VDIWEFA" else "I"

    # ── 필터 판정 ──────────────────────────────
    def _pass_filter(self, cat):
        # cat 은 "V,D,I,W,E,F,A,STEP,ANR,CRASH,GC" 중 하나
        v = self.filter_vars.get(cat)
        return True if (v is None) else v.get()

    # ── 한 줄 그리기(현 필터 반영 여부 선택) ───────────
    def _draw_line(self, ts, lvl, tag, msg, cat, apply_filter=True):
        if apply_filter and not self._pass_filter(cat):
            return  # 표시 생략 (rerender 모드/삽입 시)

        start = self.text.index(tk.END)

        # 시간 (threadtime: MM-DD HH:MM:SS.mmm, epoch: HH:MM:SS)
        if ts:
            self.text.insert(tk.END, f"{ts} ", "ts")
        else:
            self.text.insert(tk.END, " " * 24, "ts")  # 대략 자리 맞추기

        # 레벨 뱃지
        self.text.insert(tk.END, f" {lvl} ", (f"badge_{lvl}",))
        self.text.insert(tk.END, " ")

        # 태그: 해시 기반 고정 색상
        if tag:
            tag_style = f"tag_{tag}"
            if tag_style not in self.text.tag_names():
                cname = tag_color_name(tag)          # "blue", "magenta" 등
                fg = C.get(cname, C["white"])
                self.text.tag_configure(tag_style, foreground=fg)
        else:
            tag_style = "tag_default"

        if tag:
            self.text.insert(tk.END, f"{tag:>14}:", tag_style)
            self.text.insert(tk.END, " ")

        # 메시지 색 (STEP/ANR/CRASH/GC 강조는 기존대로 유지)
        base_style = None
        if   cat=="STEP":  base_style = "msg_step"
        elif cat=="ANR":   base_style = "msg_anr"
        elif cat=="CRASH": base_style = "msg_crash"
        elif cat=="GC":    base_style = "msg_gc"

        if self.is_runlog:
            self._insert_runlog_highlight(msg, base_style=base_style)
        else:
            if base_style:
                self.text.insert(tk.END, msg, base_style)
            else:
                self.text.insert(tk.END, msg)

        self.text.insert(tk.END, "\n")

        end = self.text.index(tk.END)
        if self.filter_mode == "elide":
            self.text.tag_add(f"cat_{cat}", start, end)


    # ── 배치 재렌더 ─────────────────────────────
    def _rerender_all(self):
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        # items: (ts, lvl, tag, msg, cat)
        for ts,lvl,tag,msg,cat in self.items:
            self._draw_line(ts, lvl, tag, msg, cat, apply_filter=True)
        self.text.see(tk.END)

    # ── elide 적용 ─────────────────────────────
    def _apply_elide(self):
        # elide 모드에서만 호출
        for key, var in self.filter_vars.items():
            self.text.tag_configure(f"cat_{key}", elide=not var.get())

    # ── 파싱 & 보관 & (필터 고려) 그리기 ─────────────
    def _parse_and_maybe_draw(self, raw):
        s = raw.rstrip("\r\n")
        m = RE_EPOCH.match(s)
        if m:
            # epoch 포맷: 날짜 정보는 없으므로 기존처럼 HH:MM:SS만 사용
            ts  = _fmt_epoch(m.group("epoch"))
            lv  = m.group("lvl")
            tg  = m.group("tag").strip()
            msg = m.group("msg")
        else:
            m2 = RE_STD.match(s)
            if m2:
                # threadtime 포맷: MM-DD HH:MM:SS.mmm 로 표시
                md  = m2.group("md")
                hms = m2.group("hms")
                ms  = m2.group("ms")
                ts  = f"{md} {hms}.{ms}"
                lv  = m2.group("lvl")
                tg  = m2.group("tag").strip()
                msg = m2.group("msg")
            else:
                # 기타 텍스트
                ts, lv, tg, msg = "", "I", "", s

        cat = self._categorize(lv, msg)
        self.items.append((ts, lv, tg, msg, cat))

        if self.filter_mode == "rerender":
            self._draw_line(ts, lv, tg, msg, cat, apply_filter=True)
        else:
            self._draw_line(ts, lv, tg, msg, cat, apply_filter=False)


    # ── 읽기 루프 ──────────────────────────────
    def read_loop(self):
        cnt = 0
        while cnt < self.batch:
            line = self.fp.readline()
            if not line:
                if self.follow:
                    self.after(100, self.read_loop)
                break
            self._parse_and_maybe_draw(line)
            cnt += 1

        if cnt:
            if self.filter_mode == "elide":
                self._apply_elide()   # 신규 라인에도 elide 재적용
            self.text.see(tk.END)
            self.after(1, self.read_loop)

    # ── 검색 ───────────────────────────────────
    def on_search(self):
        kw = self.q.get().strip()
        if not kw: return
        start = self.search_pos or "1.0"
        pos = self.text.search(kw, start, stopindex=tk.END, nocase=1)
        if pos:
            end = f"{pos}+{len(kw)}c"
            self.text.tag_remove("hl","1.0",tk.END)
            self.text.tag_add("hl", pos, end)
            self.text.see(pos); self.search_pos=end
        else:
            self.search_pos=None
            self.text.tag_remove("hl","1.0",tk.END)

    # ── 필터 토글 ──────────────────────────────
    def on_filter_toggle(self):
        # ✅ 토글이 여러 번 눌려도 100ms 동안은 모아서 반영
        if hasattr(self, "_pending_filter_job") and self._pending_filter_job:
            self.after_cancel(self._pending_filter_job)

        def _do_filter():
            if self.filter_mode == "elide":
                self._apply_elide()
            else:
                self._rerender_all()
            self._pending_filter_job = None

        self._pending_filter_job = self.after(100, _do_filter)  # 100ms 지연

# ── Entrypoint ──────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="로그 파일 경로")
    ap.add_argument("-f","--follow", action="store_true", help="tail -f")
    ap.add_argument("--batch", type=int, default=800, help="한번에 처리할 라인 수(기본 800)")
    ap.add_argument("--filter-mode", choices=["rerender","elide"], default="rerender",
                    help="필터 적용 방식: rerender(기본, 호환성 최고) / elide(고속, Tk 빌드에 따라 미동작 가능)")
    args = ap.parse_args()

    path = args.file or filedialog.askopenfilename(
        title="로그 파일 선택",
        filetypes=[("Log files","*.txt *.log *.logcat"),("All","*.*")]
    )
    if not path or not os.path.exists(path):
        print("❌ 파일을 선택/지정해 주세요."); sys.exit(1)

    app = LogViewer(path, follow=args.follow, batch=args.batch, filter_mode=args.filter_mode)
    app.mainloop()

if __name__ == "__main__":
    main()