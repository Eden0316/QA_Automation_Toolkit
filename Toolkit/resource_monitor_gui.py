# =============================================================
# 🖥️ GUI Resource Monitor (Crash-aware, Tkinter + Matplotlib)
# 👤 Author: Eden Kim
# 📅 Date: 2026-02-06 - v1.0.6
#   - 앱 재실행 시 PID 갱신하여 Logcat 재실행
#
# • 목적: 기존 PowerShell resource_monitor 기능을 Python GUI로 이식
#   - 실시간 그래프(좌: CPU %, 우: PSS KB)
#   - save.flag/report.flag, logcat recent/slice 저장, event_tap 연동 유지
#   - generate_report.py 호출로 PDF/CSV/JSON 생성 그대로 지원
#
# • 입력/환경:
#   - Windows 11, Python 3.8+, adb 설치 및 PATH 필요
#   - RESULT_DIR 환경변수(없으면 ./result)
#   - event_tap.py / generate_report.py 는 같은 폴더에 존재(없으면 최신 타임스탬프 파일 탐색)
#
# • 산출물:
#   - resource_YYMMDD_HHMM.txt, logcat_recent_*.txt, logcat_slice_*.txt, events.csv 등 기존과 동일
#   - report.flag 처리 시 resource_report_YYMMDD_HHMM.(pdf/csv/json)
#
# =============================================================
# -*- coding: utf-8 -*-
import os, sys, io, re, time, queue, threading, subprocess, math, ctypes, pathlib, csv, json, traceback, datetime as dt
import zlib
from dataclasses import dataclass

# ---- GUI/Plot ----
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter, MinuteLocator, SecondLocator, AutoDateLocator
from matplotlib.offsetbox import AnchoredOffsetbox, TextArea, HPacker
from matplotlib import font_manager as fm
import matplotlib
matplotlib.use("TkAgg")

# =============================================================
# 설정 상수 (기본값) — 필요 시 UI에서 조정 가능
# =============================================================
LOGCAT_FORMAT = "threadtime"
ROLLING_BUFFERS = "main,system,events,crash"
LOG_WINDOW_LINES = 30000     # recent/logcat 컷 라인 수
SLICE_WINDOW_SEC = 120       # rolling 슬라이스 시간 (초)
SLICE_SCAN_MAX_BYTES = 16 * 1024 * 1024   # 최대 역탐색 바이트(16MB)
SLICE_STABILIZE_MS = 200     # 롤링 파일 안정화 대기(ms)
SLICE_MIN_TAIL_LINES = 2000  # 시간 매칭 실패 시 최소 보장 라인(0KB 방지)
SAMPLE_INTERVAL_SEC = 1.0    # 샘플링 주기
MAX_SAMPLES = 600            # 그래프에 유지할 최대 샘플 개수 (시간 단위(분): MAX_SAMPLES * SAMPLE_INTERVAL_SEC / 60)
MAX_ENTRIES = 600            # 리소스 버퍼에 유지할 최대 엔트리 개수 (시간 단위(분): MAX_ENTRIES * SAMPLE_INTERVAL_SEC / 60)
MAX_LINES = 3000             # 로그뷰어 최대 라인 수

# 동적 임계치(기본 상수 — ADB 실패 시 사용)
CPU_WARN_DEF = 250.0
CPU_CRIT_DEF = 350.0
MEM_WARN_KB_DEF = 900_000
MEM_CRIT_KB_DEF = 1_100_000

# 퍼센트(코어 기준) → 절대치 계산 시 사용
CPU_WARN_PCT = 0.60
CPU_CRIT_PCT = 0.80
MEM_WARN_PCT = 0.23
MEM_CRIT_PCT = 0.28

# 누수 의심 임계(KB/min)
LEAK_SUSPECT_KB_PER_MIN = 50_000

# === [폴더 기준 고정] ===
SCRIPT_DIR = os.getenv("QA_SCRIPT") or os.path.abspath(os.path.dirname(__file__))
OUT_ROOT   = os.path.join(SCRIPT_DIR, "result")
os.makedirs(OUT_ROOT, exist_ok=True)

# =============================================================
# Logcat Live View
# =============================================================
# ── Logcat Viewer palette & regex ──
C = {
    "gray":"#9aa0a6","red":"#ff4d4f","red2":"#ff7875","yellow":"#ffc53d","amber":"#d49b00",
    "green":"#52c41a","lime":"#86e57f","blue":"#40a9ff","indigo":"#3b82f6","teal":"#20c997",
    "cyan":"#13c2c2","violet":"#8a2be2","magenta":"#c53db7","orange":"#ffa940",
    "white":"#f0f0f0","black":"#000000"
}
LVL_BG = {"V":"gray","D":"blue","I":"green","W":"yellow","E":"red","F":"magenta","A":"magenta"}
LVL_FG = {"V":"white","D":"white","I":"black","W":"black","E":"white","F":"white","A":"white"}

# ── 태그별 고정 색상 (해시 기반, 모든 log viewer 공통 사용 예정) ──
# C 딕셔너리의 key 를 그대로 사용
TAG_COLOR_POOL = [
    "blue", "green", "teal", "cyan", "magenta",
    "orange", "indigo", "lime", "yellow", "red2",
]

def tag_color_name(tag: str) -> str:
    """
    태그 문자열만으로 항상 동일한 색상을 결정하는 해시 기반 매핑.
    - 실행 환경, 로그 순서와 무관하게 같은 태그면 항상 같은 색.
    - TAG_COLOR_POOL 과 이 함수만 logfile_viewer_gui / logfile_to_html 에도 복붙하면
      모든 뷰어에서 태그 색상이 일관되게 유지됨.
    """
    if not tag:
        return "gray"

    # 공백 제거 + 안전한 인코딩
    t = str(tag).strip()

    # adler32: 프로세스/플랫폼에 독립적인 안정적인 해시
    h = zlib.adler32(t.encode("utf-8")) & 0xffffffff
    idx = h % len(TAG_COLOR_POOL)
    return TAG_COLOR_POOL[idx]

# --- 이하 기존과 동일 ---
PAT_STEP  = re.compile(r"\[STEP\]")
PAT_ANR   = re.compile(r"\bANR\b|\bANR in\b")
PAT_CRASH = re.compile(r"FATAL EXCEPTION|CRASH")
PAT_GC    = re.compile(r"\bGC_|\bconcurrent copying GC\b|Concurrent mark sweep", re.I)

# logcat -v threadtime 표준 포맷
RE_THREADTIME = re.compile(
    r"^\s*(?P<md>\d{2}-\d{2})\s+(?P<hms>\d{2}:\d{2}:\d{2}\.\d{3})\s+\d+\s+\d+\s+(?P<lvl>[VDIWEAF])\s+(?P<tag>[^:]+):\s*(?P<msg>.*)$"
)


class LogcatLiveView(ttk.Frame):
    def __init__(self, master, get_serial_callable, get_pkg_callable=None):
        super().__init__(master)
        self.get_serial = get_serial_callable  # App에서 현재 시리얼 가져오는 콜백
        self.get_pkg    = get_pkg_callable     # App에서 현재 패키지 가져오는 콜백
        self.proc = None
        self.alive = False
        self.queue = queue.Queue()
        self.thread = None
        self.batch = []
        self.batch_size = 200
        self.filter_vars = {}
        self.follow = True
        self.supports_elide = None  # 최초 프로빙
        self.search_pos = None
        self.current_pkg = None
        self.current_pid = None

        # ─ UI 상단 바
        bar = ttk.Frame(self); bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="검색:").pack(side=tk.LEFT, padx=4)
        self.q = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.q, width=34); ent.pack(side=tk.LEFT)
        ent.bind("<Return>", lambda e: self.on_search())
        ttk.Button(bar, text="찾기", command=self.on_search).pack(side=tk.LEFT, padx=4)

        ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=6)

        for k in ["V","D","I","W","E","F","A"]:
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(bar, text=k, variable=v, command=self.apply_filter).pack(side=tk.LEFT, padx=2)
            self.filter_vars[k] = v

        self.var_elide = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="elide", variable=self.var_elide, command=self.apply_filter).pack(side=tk.LEFT, padx=8)

        ttk.Button(bar, text="정지", command=self.stop).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="시작", command=self.start).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="🧹 Clear", command=self.clear_logcat_buffers).pack(side=tk.RIGHT, padx=2)

        # ─ Text
        self.text = tk.Text(self, bg="black", fg="white", wrap="word", undo=False)
        self.text.configure(font=("Consolas", 10))

        # 🔹 스크롤바 저장
        self.sy = ttk.Scrollbar(self, command=self.text.yview)
        self.sx = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)

        # 🔹 Text가 스크롤될 때 우리 핸들러를 거치게
        self.text.configure(yscrollcommand=self._on_text_yview,
                            xscrollcommand=self.sx.set)

        self.sy.pack(side=tk.RIGHT, fill=tk.Y)
        self.sx.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)


        # 태그 초기화
        self._init_tags()
        self.after(100, self._probe_elide_once)

    # logcat buffer clear
    def clear_logcat_buffers(self):
        """
        모니터링 대상 디바이스 logcat buffer 전체 clear.
        - adb logcat -b all -c (가능하면 all 버퍼)
        - GUI 표시(text)도 함께 비움
        """
        serial = None
        try:
            serial = (self.get_serial() or "").strip()
        except Exception:
            serial = None

        # 1) 단말 logcat clear
        try:
            cmd = ["adb"]
            if serial:
                cmd += ["-s", serial]
            cmd += ["logcat", "-b", "all", "-c"]
            subprocess.run(cmd, check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        # 2) 화면도 clear
        try:
            self.text.delete("1.0", tk.END)
        except Exception:
            pass

    # ─── controls ─────────────────────────────
    def start(self):
        self.stop()  # 중복 방지

        serial = (self.get_serial() or "").strip()

        # 🔹 현재 패키지 / PID 계산
        pkg = (self.get_pkg() or "").strip() if hasattr(self, "get_pkg") and self.get_pkg else ""
        pid = None
        if pkg:
            try:
                # pid_of는 파일 아래쪽에 이미 정의되어 있음
                pid = pid_of(pkg, serial or None)
            except Exception:
                pid = None

        self.current_pkg = pkg or None
        self.current_pid = pid

        args = ["adb"]
        if serial:
            args += ["-s", serial]

        # 🔹 PID가 있으면 해당 앱 로그만, 없으면 전체 로그
        if pid:
            args += ["logcat", f"--pid={pid}", "-v", "threadtime", "-T", "50"]
        else:
            args += ["logcat", "-v", "threadtime", "-T", "50"]  # fallback

        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="ignore"
            )
            self.alive = True
            self.queue = queue.Queue()

            # 🔹 블로킹 I/O는 별도 스레드에서
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()

            # 🔹 Tk는 큐만 주기적으로 비움
            self._drain_queue()
        except Exception as e:
            messagebox.showerror("logcat 시작 실패", str(e))


    def stop(self):
        self.alive = False
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None

    # ─── inner ────────────────────────────────
    def _reader_loop(self):
        """logcat stdout을 계속 읽어서 큐에만 넣는 스레드 (GUI 건드리지 않음)"""
        try:
            while self.alive and self.proc and self.proc.poll() is None:
                line = self.proc.stdout.readline()
                if not line:
                    break
                self.queue.put(line.rstrip("\n"))
        except Exception:
            pass

    def _drain_queue(self):
        """큐에서 일정량만 꺼내서 파싱/그리기 (Tk 메인스레드)"""
        if not self.alive:
            return

        pulled = 0
        while pulled < self.batch_size:
            try:
                line = self.queue.get_nowait()
            except queue.Empty:
                break
            self._parse_append(line)
            pulled += 1

        if pulled:
            self._flush_batch()

        # 너무 자주 돌면 이것도 부담 → 100~200ms 정도로
        self.after(120, self._drain_queue)

    def _parse_append(self, line:str):
        m = RE_THREADTIME.match(line)
        if not m:
            return
        # 🔹 시간 문자열 생성
        ts  = f"{m.group('md')} {m.group('hms')}"
        lvl = m.group("lvl")
        tag = m.group("tag")
        msg = m.group("msg")
        cat = self._categorize(msg)
        # 🔹 배치에 시간까지 넣기
        self.batch.append((ts, lvl, tag, msg, cat))

    def _categorize(self, msg:str)->str:
        if PAT_STEP.search(msg):  return "STEP"
        if PAT_ANR.search(msg):   return "ANR"
        if PAT_CRASH.search(msg): return "CRASH"
        if PAT_GC.search(msg):    return "GC"
        return "OTHER"

    def _flush_batch(self):
        # 필터 상태 반영(레벨/카테고리)
        for (ts, lvl, tag, msg, cat) in self.batch:
            if not self.filter_vars.get(lvl, tk.BooleanVar(value=True)).get():
                continue
            self._append_line(ts, lvl, tag, msg, cat)
        self.batch.clear()
        if self.follow:
            self.text.see(tk.END)
        if self.var_elide.get():
            self._apply_elide()

    def _on_text_yview(self, first, last):
        """
        Text 내용이 스크롤될 때 호출됨.
        - 스크롤바 위치 업데이트
        - 맨 아래( last ~= 1.0 )면 follow=True, 아니면 False
        """
        try:
            # 스크롤바 위치 반영
            if hasattr(self, "sy") and self.sy:
                self.sy.set(first, last)
            f = float(first)
            l = float(last)
        except Exception:
            return

        # 사용자가 한 칸이라도 위로 올려놓으면 자동 따라가기 비활성화
        # (맨 아래일 때만 다시 활성화)
        self.follow = (l >= 0.999)


    # ─── render ───────────────────────────────
    def _init_tags(self):
        self.text.tag_configure("ts", foreground=C["gray"])
        for lv in "VDIWEFA":
            self.text.tag_configure(
                f"badge_{lv}",
                foreground=C[LVL_FG[lv]],
                background=C[LVL_BG[lv]],
            )
        # 기본 태그 스타일(혹시 실패했을 때 폴백용)
        self.text.tag_configure("tag_default", foreground=C["gray"])

        self.text.tag_configure("msg_step",  foreground=C["cyan"])
        self.text.tag_configure("msg_anr",   foreground=C["magenta"])
        self.text.tag_configure("msg_crash", foreground=C["red2"])
        self.text.tag_configure("msg_gc",    foreground=C["gray"])
        self.text.tag_configure("hl", background="yellow", foreground="black")
        for cat in ["V","D","I","W","E","F","A","STEP","ANR","CRASH","GC","OTHER"]:
            self.text.tag_configure(f"cat_{cat}", elide=False)

    def _probe_elide_once(self):
        if self.supports_elide is not None:
            return
        start = self.text.index(tk.END)
        self.text.insert(tk.END, "ELIDE_PROBE\n")
        end = self.text.index(tk.END)
        self.text.tag_add("probe", start, end)
        self.text.tag_configure("probe", elide=True)
        self.update_idletasks()
        self.supports_elide = (self.text.bbox(start) is None)
        self.text.delete(start, end)

    def _apply_elide(self):
        if not self.var_elide.get() or not self.supports_elide:
            # elide 해제
            for cat in ["V","D","I","W","E","F","A","STEP","ANR","CRASH","GC","OTHER"]:
                self.text.tag_configure(f"cat_{cat}", elide=False)
            return
        # 선택된 것 외 elide
        for lv in "VDIWEFA":
            self.text.tag_configure(f"cat_{lv}", elide=not self.filter_vars[lv].get())
        for cat in ["STEP","ANR","CRASH","GC","OTHER"]:
            self.text.tag_configure(f"cat_{cat}", elide=False)

    def _append_line(self, ts, lvl, tag, msg, cat):
        start = self.text.index(tk.END)

        # 시간
        self.text.insert(tk.END, f"{ts} ", ("ts",))

        # 레벨 배지
        self.text.insert(tk.END, f" {lvl} ", (f"badge_{lvl}",))
        self.text.insert(tk.END, " ")

        # --- pidcat 스타일: 태그별 고정 색상 ---
        tag_style = f"tag_{tag}"
        if tag_style not in self.text.tag_names():
            cname = tag_color_name(tag)          # ex) "blue", "magenta" ...
            fg = C.get(cname, C["white"])
            self.text.tag_configure(tag_style, foreground=fg)

        # 태그 출력
        self.text.insert(tk.END, f"{tag:>14}:", tag_style)
        self.text.insert(tk.END, " ")

        # 메시지 색상 (기존대로)
        if   cat == "STEP":
            self.text.insert(tk.END, msg, "msg_step")
        elif cat == "ANR":
            self.text.insert(tk.END, msg, "msg_anr")
        elif cat == "CRASH":
            self.text.insert(tk.END, msg, "msg_crash")
        elif cat == "GC":
            self.text.insert(tk.END, msg, "msg_gc")
        else:
            self.text.insert(tk.END, msg)

        self.text.insert(tk.END, "\n")
        end = self.text.index(tk.END)
        self.text.tag_add(f"cat_{cat}", start, end)

        # 최대 라인 수 유지 (기존 로직 그대로)
        try:
            line_count = int(self.text.index("end-1c").split(".")[0])
            if line_count > MAX_LINES:
                self.text.delete("1.0", f"{line_count - MAX_LINES + 1}.0")
        except Exception:
            pass

    # ─── search ───────────────────────────────
    def on_search(self):
        kw = self.q.get().strip()
        if not kw:
            return
        self.text.tag_remove("hl", "1.0", tk.END)
        pos = "1.0"
        while True:
            idx = self.text.search(kw, pos, stopindex=tk.END, nocase=True)
            if not idx: break
            end = f"{idx}+{len(kw)}c"
            self.text.tag_add("hl", idx, end)
            pos = end

    def apply_filter(self):
        if self.var_elide.get():
            self._apply_elide()


# =============================================================
# 공통 유틸
# =============================================================
# --- 결과 폴더/시리얼 결정 유틸 ---
def resolve_serial(pref=None, var_serial=None):
    """
    우선순위: 버튼에서 받은 인자(pref) > GUI콤보(var_serial) > ENV(ADB_SERIAL/ANDROID_SERIAL) > 1대만 연결 시 자동 > None
    """
    # 1) 명시 인자
    if pref and str(pref).strip():
        return str(pref).strip()
    # 2) GUI 콤보
    if var_serial and str(var_serial).strip():
        return str(var_serial).strip()
    # 3) ENV
    env = os.environ.get("ADB_SERIAL") or os.environ.get("ANDROID_SERIAL")
    if env and env.strip():
        return env.strip()
    # 4) 1대만 연결 시 자동
    try:
        out = subprocess.check_output(["adb", "devices"], text=True, encoding="utf-8", errors="ignore")
        devs = [l.split()[0] for l in out.splitlines() if l.endswith("\tdevice")]
        if len(devs) == 1:
            return devs[0]
    except Exception:
        pass
    return None

def ensure_serial_result_dir(base_dir, serial):
    """
    base_dir를 Tools\result 로, 항상 …\result\<serial> 형태로 보장.
    (base_dir가 이미 …\result\<x>로 끝나더라도 새 serial로 재조합하여
     B 실행 시 A 잔상이 섞이는 것을 원천 차단)
    """
    base_dir = os.path.abspath(base_dir)
    serial = (serial or "unknown").strip()

    # base_dir가 ...\result\<무언가> 로 끝나는 경우, result 상위로 롤업
    head, tail = os.path.split(base_dir)
    if tail and tail.lower() != "result":
        # tail이 시리얼처럼 붙은 상태면 한 단계 위를 result로 간주
        if os.path.basename(head).lower() == "result":
            base_dir = head  # …\result
    # 최종 out_dir = …\result\<serial>
    out_dir = os.path.join(base_dir, serial)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

# --- [ADD] 이벤트 마커 시각화 메타 ---
EVENT_STYLE = {
    "CRASH": {"color": "crimson", "linestyle": "-",  "emoji": "💥", "label": "CR"},
    "ANR":   {"color": "purple",  "linestyle": "-.", "emoji": "⛔", "label": "ANR"},
    "GC":    {"color": "gray",    "linestyle": ":",  "emoji": "⚙",  "label": "GC"},
    "STEP":  {"color": "teal",    "linestyle": ":",  "emoji": "🔖", "label": "STEP"},
}

class EventsTailer:
    """events.csv를 지속 관찰하여 신규 이벤트를 돌려준다."""
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.csv_path = os.path.join(out_dir, "events.csv")
        self._pos = 0  # 파일 오프셋
        self._seen = set()  # (ts_str, type, detail) 중복 방지

    def poll_new(self):
        """
        신규 이벤트 [(dt, type, detail, level), ...] 반환
        - csv.DictReader 반복 중 f.tell() 사용 금지 -> chunk 읽기 방식으로 변경
        """
        out = []
        try:
            if not os.path.exists(self.csv_path):
                return out

            # 파일 열기 (csv 모듈 권장: newline="")
            with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
                # 첫 호출: 헤더 한 줄 스킵
                if self._pos == 0:
                    _ = f.readline()
                    self._pos = f.tell()

                # 현재 오프셋으로 이동
                f.seek(self._pos)

                # 남은 구간을 통째로 읽어 StringIO로 파싱
                chunk = f.read()
                if not chunk:
                    return out

                # 현재 파일 끝 위치로 오프셋 갱신 (반복 중 tell 금지 회피)
                self._pos = f.tell()

            # chunk를 메모리에서 CSV 파싱
            sio = io.StringIO(chunk)
            rdr = csv.DictReader(sio, fieldnames=["timestamp","type","detail","level"])
            for row in rdr:
                ts_str = (row.get("timestamp") or "").strip()
                typ    = (row.get("type") or "").strip()
                detail = (row.get("detail") or "").strip()
                level  = (row.get("level") or "").strip()

                if not ts_str or not typ:
                    continue

                key = (ts_str, typ, detail)
                if key in self._seen:
                    continue
                self._seen.add(key)

                try:
                    dt_obj = dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue

                out.append((dt_obj, typ, detail, level))

        except Exception as e:
            # 디버그 로그 연동되어 있으면 GUI 로그창에도 보이도록
            self._log(f"[events] tailer error: {e}")

        return out


@dataclass
class DeviceInfo:
    serial: str | None
    package: str | None
    initial_pid: str | None

# epoch: "<epoch> <pid> <tid> <L> <tag>: msg"
_re_epoch = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+\d+\s+\d+\s+[VDIWEAF]\s+[^:]+:\s")

# threadtime: "MM-DD HH:MM:SS.mmm  pid  tid  L  tag: msg"
_re_thread = re.compile(
    r"^\s*(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+\d+\s+\d+\s+[VDIWEAF]\s+[^:]+:\s"
)

def _parse_log_ts(line: str) -> float | None:
    """
    epoch 또는 threadtime 라인에서 '유닉스 타임스탬프(second)' 반환.
    매칭 실패 시 None.
    """
    m = _re_epoch.match(line)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None

    m = _re_thread.match(line)
    if m:
        try:
            now = dt.datetime.now()
            year = now.year
            ts = dt.datetime(
                year, int(m.group(1)), int(m.group(2)),
                int(m.group(3)), int(m.group(4)), int(m.group(5)),
                int(m.group(6)) * 1000
            )
            # 연말/연초 넘김 보정: 미래 7일 이상이면 작년으로
            if ts - now > dt.timedelta(days=7):
                ts = ts.replace(year=year - 1)
            return ts.timestamp()
        except Exception:
            return None

    return None

def ts_file_stamp() -> str:
    return dt.datetime.now().strftime("%y%m%d_%H%M")


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def result_dir() -> str:
    """
    우선순위:
      1) RESULT_DIR 환경변수 (common.adb_env / run_multi에서 보장)
      2) QA_SCRIPT/result/<serial?>  또는 script_dir/result/<serial?>
         - ANDROID_SERIAL or ADB_SERIAL 이 있으면 시리얼 하위 폴더로 분리
    """
    rd = os.environ.get("RESULT_DIR")
    if rd:
        ensure_dir(rd)
        return os.path.abspath(rd)

    base = os.environ.get("QA_SCRIPT") or os.path.abspath(os.path.dirname(__file__))
    serial = os.environ.get("ANDROID_SERIAL") or os.environ.get("ADB_SERIAL")
    d = os.path.join(base, "result", serial) if serial else os.path.join(base, "result")
    ensure_dir(d)
    return os.path.abspath(d)


def script_dir() -> str:
    return os.path.abspath(os.path.dirname(__file__))


def which(cmd: str) -> str | None:
    from shutil import which as _which
    return _which(cmd)


def adb_ready(timeout=30, serial=None):
    subprocess.run(["adb", "start-server"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # ← ... 금지
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = subprocess.check_output(["adb","devices"], encoding="utf-8", errors="ignore")
        if serial is None and len(re.findall(r"(?m)^\S+\s+device$", out)) > 1:
            return  # 다중 단말인데 시리얼 미지정이면 핑 생략(준비만 확인)
        if re.search(r"(?m)^\S+\s+device$", out) and not re.search(r"(offline|unauthorized)", out):
            pong = subprocess.check_output(["adb","-s", serial, "shell","echo","ping"],
                                           encoding="utf-8", errors="ignore") if serial else \
                   subprocess.check_output(["adb","shell","echo","ping"], encoding="utf-8", errors="ignore")
            if pong: return
        time.sleep(0.5)
    raise RuntimeError("ADB 준비 실패: 디바이스 응답 없음")


def current_foreground_pkg(serial: str | None = None) -> str | None:
    try:
        out = adb_out(["shell", "dumpsys", "activity", "activities"], serial=serial)
        m = re.search(r"ResumedActivity.*? (\w[\w\.]+)/", out)
        return m.group(1) if m else None
    except Exception:
        return None


def pid_of(pkg: str, serial: str | None = None) -> str | None:
    try:
        p = adb_out(["shell", "pidof", pkg], serial=serial).strip()
        if p: return p
    except Exception: 
        pass
    try:
        ps = adb_out(["shell", "ps"], serial=serial)
        for line in ps.splitlines():
            if pkg in line:
                toks = [t for t in line.split(" ") if t]
                if len(toks) >= 2: return toks[1]
    except Exception: 
        pass
    return None


def ktail(src_file: str, n_lines: int, dst_file: str):
    try:
        with open(src_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            pos = size
            while pos > 0 and data.count(b"\n") <= n_lines:
                step = min(block, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
        lines = data.splitlines()[-n_lines:]
        with open(dst_file, "wb") as o:
            o.write(b"\n".join(lines))
    except Exception as e:
        print(f"[ktail] err: {e}")

def list_devices() -> list[str]:
    """adb devices에서 online device만 추출"""
    out = subprocess.check_output(["adb", "devices"], encoding="utf-8", errors="ignore")
    devs = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("List of devices"): 
            continue
        cols = ln.split()
        if len(cols) >= 2 and cols[1] == "device":
            devs.append(cols[0])
    return devs

def _adb_prefix(serial: str | None) -> list[str]:
    return ["-s", serial] if serial else []

def adb_run(args: list[str], *, serial: str | None = None, **popen_kwargs):
    """subprocess.run용 ADB 래퍼"""
    if popen_kwargs.get("text"):
        popen_kwargs.setdefault("encoding", "utf-8")
        popen_kwargs.setdefault("errors", "replace")
    return subprocess.run(["adb", *_adb_prefix(serial), *args], **popen_kwargs)

def adb_out(args: list[str], *, serial: str | None = None) -> str:
    """stdout만 반환(stderr 무시) — Permission denied 등 억제"""
    proc = subprocess.run(
        ["adb", *_adb_prefix(serial), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",     # ← 이거 추가
        errors="replace",     # ← 이거 추가 (깨지는 문자 있어도 예외 안 나게)
    )
    return proc.stdout or ""

# =============================================================
# 동적 임계치 계산 (generate_report 로직과 호환)
# =============================================================

def get_device_cores(default=8) -> int:
    def _count(expr: str) -> int:
        if not expr: return 0
        total = 0
        for part in expr.strip().split(','):
            m = re.match(r"(\d+)-(\d+)", part.strip())
            if m:
                a,b = int(m.group(1)), int(m.group(2))
                if b >= a: total += (b-a+1)
            elif part.strip().isdigit():
                total += 1
        return total
    for path in ["/sys/devices/system/cpu/possible", "/sys/devices/system/cpu/present"]:
        try:
            n = _count(adb_out(["cat", path]))
            if n>0: return n
        except Exception: pass
    try:
        c = len(re.findall(r"(?m)^\s*processor\s*:\s*\d+\s*$", adb_out(["cat","/proc/cpuinfo"])) )
        if c>0: return c
    except Exception: pass
    return default


def get_memtotal_kb(default=3_900_000) -> int:
    try:
        m = re.search(r"MemTotal:\s+(\d+)\s*kB", adb_out(["cat","/proc/meminfo"]))
        return int(m.group(1)) if m else default
    except Exception:
        return default


def nearest_ram_class_kb(mem_kb: int):
    classes = {"2GB":1_950_000,"3GB":2_950_000,"4GB":3_900_000,"6GB":5_800_000,"8GB":7_800_000,"12GB":11_700_000}
    name, base = min(classes.items(), key=lambda kv: abs(mem_kb - kv[1]))
    return name, base


def compute_thresholds():
    try:
        cores = get_device_cores()
        mem_real = get_memtotal_kb()
        ram_name, ram_kb = nearest_ram_class_kb(mem_real)
        cpu_warn = int(CPU_WARN_PCT * 100 * cores)
        cpu_crit = int(CPU_CRIT_PCT * 100 * cores)
        mem_warn = int(MEM_WARN_PCT * ram_kb)
        mem_crit = int(MEM_CRIT_PCT * ram_kb)
        return (cpu_warn, cpu_crit, mem_warn, mem_crit, cores, mem_real, ram_name, ram_kb)
    except Exception:
        return (CPU_WARN_DEF, CPU_CRIT_DEF, MEM_WARN_KB_DEF, MEM_CRIT_KB_DEF, None, None, None, None)


# =============================================================
# 샘플링 (CPU, Memory) — PS 스크립트와 동일 의미의 값 산출
# =============================================================

def sample_cpu_mem(pkg: str, pid: str | None, serial: str | None):
    ts = dt.datetime.now()
    cpu = None
    pss_kb = None

    # CPU
    try:
        if pid:
            top = adb_out(["shell", "top", "-n", "1", "-p", pid], serial=serial)
        else:
            top = adb_out(["shell", "top", "-n", "1"], serial=serial)
        for line in top.splitlines():
            if "%CPU" in line:
                continue
            if re.match(r"^\s*\d+\s", line):
                parts = [p for p in line.split() if p]
                if len(parts) > 8:
                    try: cpu = float(parts[8])
                    except: cpu = None
                break
    except Exception:
        pass

    # Memory (smaps_rollup → statm → status)
    try:
        if pid:
            try:
                sr = adb_out(["shell","cat", f"/proc/{pid}/smaps_rollup"], serial=serial)
                m = re.search(r"(?im)^\s*Pss:\s+(\d+)\s+kB", sr)
                if m: pss_kb = int(m.group(1))
            except: pass
            if pss_kb is None:
                try:
                    statm = adb_out(["shell","cat", f"/proc/{pid}/statm"], serial=serial).strip()
                    m = re.match(r"(\d+)\s+(\d+)\s+(\d+)", statm)
                    if m:
                        resident_kb = int(m.group(2)) * 4
                        pss_kb = resident_kb
                except: pass
            if pss_kb is None:
                try:
                    status = adb_out(["shell","cat", f"/proc/{pid}/status"], serial=serial)
                    m = re.search(r"(?im)^\s*VmRSS:\s+(\d+)\s+kB", status)
                    if m: pss_kb = int(m.group(1))
                except: pass
    except Exception:
        pass

    return ts, cpu, pss_kb


# =============================================================
# 롤링 logcat 및 저장 루틴 (기존 PS 동작과 대응)
# =============================================================
class RollingLogcat:
    def __init__(self, out_dir: str, serial: str | None = None, logger=None):
        self.out_dir = out_dir
        self.serial = serial
        self.log_path = os.path.join(out_dir, f"rolling_{ts_file_stamp()}.log")
        self._proc = None
        self._logger = logger or (lambda msg: None)

    def start(self):
        if self._proc and self._proc.poll() is None:
            return
        f = open(self.log_path, "wb")
        self._proc = subprocess.Popen(
            ["adb", *_adb_prefix(self.serial), "logcat", "-v", LOGCAT_FORMAT, "-b", ROLLING_BUFFERS],
            stdout=f, stderr=subprocess.DEVNULL
        )
        self._logger(f"[rolling] start: {self.log_path}")

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try: self._proc.terminate()
            except: pass
        self._logger("[rolling] stop")

    def save_slice(self, window_sec: int = SLICE_WINDOW_SEC):
        """
        롤링 로그(현재 self.log_path)에서 '최근 window_sec초'만 잘라 저장.
        - epoch/threadtime 자동 인식
        - 역탐색으로 성능 확보
        - 매칭 0줄이면 마지막 SLICE_MIN_TAIL_LINES 줄로 폴백 (0KB 방지)
        """
        try:
            import os

            # 파일 안정화
            time.sleep(SLICE_STABILIZE_MS / 1000.0)

            if not os.path.exists(self.log_path) or os.path.getsize(self.log_path) == 0:
                # 빈 롤링이면 폴백(빈 파일 방지)
                dst = os.path.join(self.out_dir, f"logcat_slice_{ts_file_stamp()}.txt")
                with open(dst, "w", encoding="utf-8") as o:
                    o.write("[slice] rolling log is empty at this moment\n")
                print(f"[slice] {dst} (empty rolling)")
                return dst

            # 파일 끝에서부터 역탐색 버퍼 구성
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                max_bytes = min(size, SLICE_SCAN_MAX_BYTES)
                f.seek(size - max_bytes)
                raw = f.read(max_bytes)

            lines = raw.splitlines()  # b'\n' 기준, 개행 미완성 라인도 포함
            cutoff = dt.datetime.now().timestamp() - float(window_sec)

            picked: list[str] = []
            started = False  # 윈도우에 들어온 순간부터 타임스탬프가 없는 줄도 함께 수집

            for b in reversed(lines):
                try:
                    s = b.decode("utf-8", "ignore")
                except Exception:
                    continue

                ts = _parse_log_ts(s)
                if ts is not None:
                    if ts >= cutoff:
                        picked.append(s)
                        started = True
                    else:
                        # 이미 창 안을 수집 중이었다면 여기서 중단(시간 기준 완성)
                        if started:
                            break
                        # 아직 창에 못 들어왔으면 계속 역탐색
                else:
                    # 타임스탬프를 못 읽는 줄: 창에 들어온 뒤에는 포함
                    if started:
                        picked.append(s)

            picked.reverse()

            dst = os.path.join(self.out_dir, f"logcat_slice_{ts_file_stamp()}.txt")

            if picked:
                with open(dst, "w", encoding="utf-8") as o:
                    o.write("\n".join(picked))
                print(f"[slice] {dst} ({len(picked)} lines, ~{window_sec}s)")
                return dst

            # ⬇ 시간 매칭이 전혀 없으면 마지막 N줄 폴백 (0KB 방지)
            tail_n = min(SLICE_MIN_TAIL_LINES, len(lines))
            tail = [l.decode("utf-8", "ignore") for l in lines[-tail_n:]] if tail_n > 0 else []
            with open(dst, "w", encoding="utf-8") as o:
                if tail:
                    o.write("\n".join(tail))
                else:
                    o.write("[slice] no lines to write (both window and tail empty)\n")
            print(f"[slice] {dst} (fallback tail {len(tail)} lines)")
            return dst

        except Exception as e:
            print(f"[slice] err: {e}")
            return None


# 최근 로그 저장 함수군
def save_logcat_crash(out_dir: str):
    f = os.path.join(out_dir, f"logcat_crash_{ts_file_stamp()}.txt")
    try:
        with open(f, "wb") as o:
            subprocess.run(["adb","logcat","-b","crash","-d","-v",LOGCAT_FORMAT,"-t",str(LOG_WINDOW_LINES)], stdout=o, stderr=subprocess.DEVNULL)
        return f
    except Exception:
        return None


def save_logcat_recent_all(out_dir: str):
    f = os.path.join(out_dir, f"logcat_recent_{ts_file_stamp()}.txt")
    try:
        with open(f, "wb") as o:
            subprocess.run(["adb","logcat","-d","-v",LOGCAT_FORMAT,"-t",str(LOG_WINDOW_LINES)], stdout=o, stderr=subprocess.DEVNULL)
        return f
    except Exception:
        return None


def save_logcat_recent_pkg(out_dir: str, pkg: str):
    tmp = os.path.join(out_dir, f"_recent_raw_{ts_file_stamp()}.tmp")
    dst = os.path.join(out_dir, f"logcat_recent_pkg_{ts_file_stamp()}.txt")
    try:
        with open(tmp, "wb") as o:
            subprocess.run(["adb","logcat","-d","-v",LOGCAT_FORMAT,"-t",str(LOG_WINDOW_LINES)], stdout=o, stderr=subprocess.DEVNULL)
        # 텍스트 필터
        with open(tmp, "r", encoding="utf-8", errors="ignore") as i, open(dst, "w", encoding="utf-8") as o2:
            for line in i:
                if pkg in line:
                    o2.write(line)
        os.remove(tmp)
        return dst
    except Exception:
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception: pass
        return None


def save_logcat_recent_pid(out_dir: str, pid: str | None):
    if not pid: return None
    f = os.path.join(out_dir, f"logcat_recent_pid_{ts_file_stamp()}.txt")
    try:
        with open(f, "wb") as o:
            subprocess.run(["adb", f"logcat", f"--pid={pid}", "-d","-v",LOGCAT_FORMAT,"-t",str(LOG_WINDOW_LINES)], stdout=o, stderr=subprocess.DEVNULL)
        return f
    except Exception:
        return None


# =============================================================
# 이벤트 탭(event_tap) 연동
# =============================================================
class EventTapProc:
    def __init__(self, pkg: str, out_dir: str, serial: str | None = None, on_log=None):
        self.pkg = pkg
        self.out_dir = out_dir
        self.serial = serial
        self.proc = None
        self._on_log = on_log or (lambda s: None)
        self._threads = []

    def _find_event_tap(self) -> str | None:
        cdir = script_dir()
        cand = os.path.join(cdir, "event_tap.py")
        if os.path.exists(cand):
            return cand
        # 타임스탬프 변형본 탐색
        files = [f for f in os.listdir(cdir) if re.match(r"^event_tap_\d{6}-\d{4}\.py$", f)]
        files.sort(reverse=True)
        if files:
            return os.path.join(cdir, files[0])
        return None

    def start(self):
        path = self._find_event_tap()
        if not path:
            self._on_log("[event_tap] not found — skip")
            return
        # stale stop.flag 제거(시작 시 한 번)
        try:
            sflag = os.path.join(self.out_dir, "stop.flag")
            if os.path.exists(sflag): os.remove(sflag)
        except Exception: pass

        env = os.environ.copy()
        if self.serial:
            env["ADB_SERIAL"] = self.serial  # event_tap 내부 ADB 호출에 적용
            env["ANDROID_SERIAL"] = self.serial   # 👈 추가
        self.proc = subprocess.Popen(
            [sys.executable, path, "-p", self.pkg, "-o", self.out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",     # ✅ automation으로 켰을 때도 강제로 utf-8
            errors="replace",     # ✅ 이상한 바이트 있어도 터지지 말고 대체
            env=env,
        )
        self._on_log(f"[event_tap] start pid={self.proc.pid}")

        # stdout/stderr 리더 스레드
        def _reader(stream, tag):
                for line in iter(stream.readline, ""):
                    self._on_log(f"[event_tap:{tag}] {line.rstrip()}")
        t1 = threading.Thread(target=_reader, args=(self.proc.stdout, "out"), daemon=True)
        t2 = threading.Thread(target=_reader, args=(self.proc.stderr, "err"), daemon=True)
        t1.start(); t2.start()
        self._threads = [t1, t2]

    def stop(self):
        try:
            # 정상 종료 유도
            open(os.path.join(self.out_dir, "stop.flag"), "w").close()
        except Exception: pass
        if self.proc and self.proc.poll() is None:
            try: self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired: self.proc.terminate()
        self._on_log("[event_tap] stop")


# =============================================================
# 리소스 버퍼 파일 포맷(기존 generate_report 파서 호환)
# =============================================================
class ResourceBuffer:
    def __init__(self, out_dir: str, max_entries: int = 100):
        self.out_dir = out_dir
        self.q: list[str] = []
        self.max_entries = max_entries

    def _fmt_int(self, v, w=12):
        try:
            return f"{int(v):>{w}d}"
        except Exception:
            return f"{'N/A':>{w}s}"

    def _fmt_kb(self, v, w=12):
        try:
            return f"{int(v):>{w},d}"
        except Exception:
            return f"{'N/A':>{w}s}"

    def append(self, ts: dt.datetime, pkg: str, pid: str | None, cpu, pss_kb):
        lines = []
        lines.append(f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}]\r\n")
        lines.append(f"[Package] {pkg} (PID: {pid})\r\n")
        lines.append("[CPU]\r\n")
        # top 라인은 원문을 표기하기 어렵기 때문에 헤더만 유지
        lines.append("PID USER %CPU ARGS (omitted in GUI mode)\r\n")
        # 파서 호환: 9번째 토큰이 CPU(부동소수)여야 함
        pid_s = str(pid or "0")
        cpu_s = f"{float(cpu):.1f}" if cpu is not None else "0.0"
        # 예시: "123 u0_qa 0 0 0 0 0 S 15.0 com.example.app"
        lines.append(f"{pid_s} u0_qa 0 0 0 0 0 S {cpu_s} {pkg}\r\n\r\n")

        lines.append("[Memory]\r\n")
        lines.append("     PssTotal         VmRSS   Threads\r\n")
        pss = self._fmt_kb(pss_kb)
        rss = self._fmt_kb(pss_kb)  # 근사
        thr = f"{''.rjust(7)}"      # 정보 부재 → N/A
        lines.append(f"TOTAL {pss} kB  {rss} kB  {thr}\r\n")
        self.q.append("".join(lines))
        if len(self.q) > self.max_entries:
            self.q.pop(0)

    def save(self):
        f = os.path.join(self.out_dir, f"resource_{ts_file_stamp()}.txt")
        with open(f, "w", encoding="utf-8") as o:
            o.write("".join(self.q))
        return f


# =============================================================
# GUI 메인 애플리케이션
# =============================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.serial = None          # 선택 디바이스(아직 미정)
        self.pkg = None
        self.initial_pid = None
        self._busy_count = 0
        self.title("QA Resource Monitor (GUI)")
        self.geometry("1080x700")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._crash_flagged = False

        # --- Emoji font pick (Windows 우선) ---
        self.emoji_font = None
        for name in ["Segoe UI Emoji", "Noto Color Emoji", "Twitter Color Emoji", "Apple Color Emoji", "EmojiOne Color", "Segoe UI Symbol"]:
            try:
                path = fm.findfont(name, fallback_to_default=False)
                if path and os.path.exists(path):
                    self.emoji_font = fm.FontProperties(fname=path)
                    break
            except Exception:
                pass

        # ✅ 외부에서 RESULT_DIR이 주입되었는지 "앱 시작 시점"에만 판정(래치)
        # - 단독 실행에서는 False
        # - common/run_id 또는 --out-dir로 실행되면 True
        self._external_result_dir = bool((os.environ.get("RESULT_DIR") or "").strip())
        self._external_result_dir_path = os.path.abspath(os.environ["RESULT_DIR"]) if self._external_result_dir else None

        # 상태
        self.out_dir = result_dir()
        self.running = False
        self.roll = RollingLogcat(self.out_dir)
        self.evtap = None
        self.buf = ResourceBuffer(self.out_dir, max_entries=MAX_ENTRIES)
        
        # 임계치(로드)
        (self.CPU_WARN, self.CPU_CRIT, self.MEM_WARN_KB, self.MEM_CRIT_KB,
         self.CORES, self.MEMTOTAL_REAL, self.RAM_NAME, self.RAM_CLASS_KB) = compute_thresholds()
        
        # 이벤트 관찰자
        self.events = []          # [(dt, type, detail, level)]
        self.event_artists = []   # 현재 플롯에 올린 아티스트(지우기 용도)
        self.tailer = EventsTailer(self.out_dir)  # [ADD] 워처
        
        self.events_enabled = tk.BooleanVar(value=True)        # Show Events
        self.clear_events_on_start = tk.BooleanVar(value=True) # Clear events

        # UI 구성
        self.nb = ttk.Notebook(self)
        self.nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tab_res = ttk.Frame(self.nb)
        self.tab_log = ttk.Frame(self.nb)
        self.nb.add(self.tab_res, text="📊 리소스")
        self.nb.add(self.tab_log, text="🧾 로그캣")

        # 리소스 탭에 기존 구성 이식 (logview → toolbar → plot → status)
        self._build_logview(parent=self.tab_res)
        self._build_toolbar(parent=self.tab_res)
        self._build_plot(parent=self.tab_res)
        self._build_status(parent=self.tab_res)

        # 로그캣 탭 생성
        self.logcat_view = LogcatLiveView(
            self.tab_log,
            get_serial_callable=self._selected_serial,
            get_pkg_callable=lambda: (self.var_pkg.get() or self.pkg or "").strip()
        )
        self.logcat_view.pack(fill=tk.BOTH, expand=True)

        # 데이터 시리즈
        self.time_series: list[dt.datetime] = []
        self.cpu_series: list[float] = []
        self.mem_series: list[int] = []

        # 타이머
        self.after_id = None

        # 초기 안내
        self.log_status("ADB 초기화 중…")
        try:
            # adb_ready()
            # self.log_status("ADB ready")
            # self.pkg = current_foreground_pkg() or ""
            # 콤보박스에 채워진 첫 번째 시리얼(또는 사용자가 선택한 시리얼) 사용
            sel = self._selected_serial()
            adb_ready(serial=sel)
            self.log_status(f"ADB ready ({sel or 'default'})")
            self.pkg = current_foreground_pkg(sel) or ""
            if not self.pkg:
                self.log_status("포그라운드 패키지 미감지 — 수동 입력하세요")
        except Exception as e:
            messagebox.showerror("ADB 오류", str(e))

        # ---- stale flags cleanup ----
        for fn in ("save.flag", "report.flag", "stop.flag"):
            try:
                p = os.path.join(self.out_dir, fn)
                if os.path.exists(p): os.remove(p)
            except Exception:
                pass
        
        # ---- flag watch: save.flag / report.flag 자동 감지 ----
        self._flag_last = {"save": 0.0, "report": 0.0}
        self._flag_timer_id = self.after(1000, self._check_flags)

    # App 클래스 메서드로 추가 (기존 self._adb_log 옆)
    def _adb_log_prio(self, tag: str, msg: str, prio: str = "i"):
        """
        adb shell log -p <priority> -t <TAG> "<MSG>"
        priority: v/d/i/w/e/f/s 중 하나. CRASH는 'e' 권장.
        """
        try:
            args = ["adb"]
            if self.serial:
                args += ["-s", self.serial]
            # -p <prio> 로 우선순위 강제
            subprocess.run(args + ["shell", "log", "-p", prio, "-t", tag, f"{msg}"], check=False)
            self.log_status(f"[SIM] {tag}/{prio.upper()}: {msg}")
        except Exception as e:
            self.log_status(f"[SIM] 실패: {e}")

    # ----- Simulator helpers -----
    def _adb_log(self, tag: str, msg: str, level: str = "I"):
        """adb logcat에 한 줄 주입."""
        try:
            args = ["adb"]
            if self.serial:
                args += ["-s", self.serial]
            # logcat 입력은 log 태그만 지원 → -p/level은 메시지로 처리
            # 표준: adb shell log -t <TAG> "<MSG>"
            subprocess.run(args + ["shell", "log", "-t", tag, f"{msg}"], check=False)
            self.log_status(f"[SIM] {tag}: {msg}")
        except Exception as e:
            self.log_status(f"[SIM] 실패: {e}")

    def on_step(self):
        """입력칸의 텍스트로 STEP을 남기고, 비어 있으면 '테스트 단계'를 사용"""
        txt = (self.var_step.get() or "").strip()
        if not txt:
            txt = "테스트 단계"

        # GUI 라벨 업데이트: 기존 sim_step 라벨이 있으면 우선 갱신
        try:
            if hasattr(self, "sim_step"):  # 프로젝트의 기존 라벨 위젯 이름이 sim_step 라고 가정
                try:
                    # ttk.Label 또는 tk.Label 모두 대응
                    self.sim_step.configure(text=txt)
                except Exception:
                    pass
        except Exception:
            pass

        # ADB 로그에 STEP 한 줄 남기기 (QA 태그)
        try:
            adb_run(["shell", "log", "-t", "QA", f"[STEP] {txt}"], serial=self.serial, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            # ADB 실패해도 GUI는 계속 동작하도록
            self.log_status(f"[STEP] ADB 로그 실패: {e}")

        # 하단 로그창에도 남김
        self.log_status(f"[STEP] {txt}")

        # 입력창 비우고 포커스
        try:
            self.var_step.set("")
            self.ent_step.focus_set()
        except Exception:
            pass

    def sim_step(self, label: str):
        # event_tap는 tag==QA & "[STEP] ..."만 인정하도록 설계됨
        self._adb_log("QA", f"[STEP] {label}")

    def sim_anr(self):
        pkg = (self.var_pkg.get() or self.pkg or "").strip()
        if not pkg:
            messagebox.showinfo("Simulator", "Package를 먼저 입력하세요.")
            return
        # event_tap의 ANR 패턴: "ANR in <pkg>"
        self._adb_log("QA", f"ANR in {pkg}")

    def sim_crash(self):
        pkg = (self.var_pkg.get() or self.pkg or "").strip()
        if not pkg:
            messagebox.showinfo("Simulator", "Package를 먼저 입력하세요.")
            return
        # 1) 직전 프로세스 라인(Info) → 2) FATAL EXCEPTION 라인(Error)
        self._adb_log_prio("AndroidRuntime", f"Process: {pkg}", prio="i")
        time.sleep(0.05)  # 너무 붙으면 파서가 순서를 못 잡는 환경이 있어 소폭 딜레이
        self._adb_log_prio("AndroidRuntime", "FATAL EXCEPTION: main", prio="e")

    def sim_gc(self):
        pkg = (self.var_pkg.get() or self.pkg or "").strip()
        if not pkg:
            messagebox.showinfo("Simulator", "Package를 먼저 입력하세요.")
            return
        # event_tap의 GC 패턴 중 하나 + 패키지명 포함
        self._adb_log("QA", f"concurrent copying GC for {pkg}")

    # ----- UI -----
    def _build_toolbar(self, parent=None):
        parent = parent or self
        bar = ttk.Frame(parent)
        bar.pack(side=tk.TOP, fill=tk.X)

        # ── Row 1: Device & Package ──────────────────────────────
        row1 = ttk.Frame(bar)
        row1.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 2))

        ttk.Label(row1, text="Device:").pack(side=tk.LEFT)
        self.var_serial = tk.StringVar()
        self.cmb_serial = ttk.Combobox(row1, textvariable=self.var_serial, width=20, state="readonly")
        self.cmb_serial.pack(side=tk.LEFT, padx=(2, 6))

        def _refresh_devs():
            devs = list_devices()                  # 실제 시리얼 리스트
            self.serials = devs

            labels = []
            self.map_label_to_serial = {}          # 👈 라벨→시리얼
            self.map_serial_to_label = {}          # 👈 시리얼→라벨
            for s in devs:
                try:
                    out = subprocess.check_output(
                        ["adb","-s", s, "shell", "getprop", "ro.product.model"],
                        encoding="utf-8", errors="ignore", timeout=5
                    )
                    model = (out or "").strip()
                except Exception:
                    model = ""
                label = f"{model}({s})" if model else s
                labels.append(label)
                self.map_label_to_serial[label] = s
                self.map_serial_to_label[s] = label

            self.labels = labels
            self.cmb_serial["values"] = labels
            # 기존 선택이 없으면 첫 항목 라벨로 세팅
            if labels and not self.var_serial.get():
                self.var_serial.set(labels[0])

        
        ttk.Button(row1, text="Refresh", command=_refresh_devs).pack(side=tk.LEFT)

        ttk.Label(row1, text="Package:").pack(side=tk.LEFT, padx=(12, 4))
        self.var_pkg = tk.StringVar()
        self.ent_pkg = ttk.Entry(row1, textvariable=self.var_pkg, width=32)
        self.ent_pkg.pack(side=tk.LEFT)

        def _btn_detect():
            serial = self._selected_serial()
            p = current_foreground_pkg(serial)
            if p:
                self.var_pkg.set(p)
                self.log_status(f"포그라운드 패키지: {p}")
            else:
                self.log_status("포그라운드 패키지 미감지")
        self.btn_detect = ttk.Button(row1, text="포그라운드 감지", command=_btn_detect)
        self.btn_detect.pack(side=tk.LEFT, padx=6)

        _refresh_devs()

        # ── Row 2: Actions ───────────────────────────────────────
        row2 = ttk.Frame(bar)
        row2.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 6))

        self.btn_toggle = ttk.Button(row2, width=9, text=("■ Stop" if self.running else "▶ Start"),
                                    command=self._on_toggle_start_stop)
        self.btn_toggle.pack(side=tk.LEFT, padx=1)
        self.btn_save   = ttk.Button(row2, width=9, text="💾 Save", command=self.on_save); self.btn_save.pack(side=tk.LEFT, padx=1)
        self.btn_report = ttk.Button(row2, width=9, text="📜 Report", command=self.on_report); self.btn_report.pack(side=tk.LEFT, padx=1)

        # [ADD] 이벤트 옵션
        ttk.Checkbutton(row2, text="Clear Ev", variable=self.clear_events_on_start).pack(side=tk.LEFT, padx=(10,0))
        ttk.Checkbutton(row2, text="Show Ev", variable=self.events_enabled).pack(side=tk.LEFT, padx=(5,0))

        # [ADD] Simulator 버튼군
        sim = ttk.Frame(row2)
        sim.pack(side=tk.LEFT, padx=(5,0))
        # ⬇⬇⬇ [추가] STEP 입력/버튼/미리보기
        self.var_step = tk.StringVar(value="")
        self.ent_step = ttk.Entry(sim, textvariable=self.var_step, width=15)
        self.ent_step.pack(side=tk.LEFT)
        self.btn_step = ttk.Button(sim, text="STEP", width=6, command=self.on_step)
        self.btn_step.pack(side=tk.LEFT, padx=(2, 1))
        # ttk.Button(sim, text="STEP", width=6, command=lambda: self.sim_step("테스트 단계")).pack(side=tk.LEFT, padx=1)
        ttk.Button(sim, text="ANR", width=6, command=self.sim_anr).pack(side=tk.LEFT, padx=1)
        ttk.Button(sim, text="CRASH", width=6, command=self.sim_crash).pack(side=tk.LEFT, padx=1)
        ttk.Button(sim, text="GC", width=6, command=self.sim_gc).pack(side=tk.LEFT, padx=1)

        self.var_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Auto-Scroll", variable=self.var_autoscroll).pack(side=tk.RIGHT)

    def _build_plot(self, parent=None):
        parent = parent or self
        frm = ttk.Frame(parent)
        frm.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.fig = Figure(figsize=(8,4), dpi=80)
        self.ax1 = self.fig.add_subplot(111)
        self.ax2 = self.ax1.twinx()
        self.ax1.grid(True, alpha=0.25)
        self.ax1.set_ylabel("CPU (%)")
        self.ax2.set_ylabel("PSS (KB)")

        # 기존 라인
        self.line_cpu, = self.ax1.plot([], [], label="CPU (%)", color="tab:blue", linewidth=2, zorder=3)
        self.line_mem, = self.ax2.plot([], [], label="Memory PSS (KB)", color="tab:orange", linewidth=2, zorder=3)

        # 가이드라인: 더 뒤에(아래) 그리고 연하게
        self.cpu_warn_line = self.ax1.axhline(self.CPU_WARN, color="tab:blue",
            linestyle=":",  linewidth=1, label="CPU WARN", zorder=1, alpha=0.35)
        self.cpu_crit_line = self.ax1.axhline(self.CPU_CRIT, color="tab:blue",
            linestyle="--", linewidth=1, label="CPU CRIT", zorder=1, alpha=0.35)
        self.mem_warn_line = self.ax2.axhline(self.MEM_WARN_KB, color="tab:orange",
            linestyle=":",  linewidth=1, label="MEM WARN", zorder=1, alpha=0.35)
        self.mem_crit_line = self.ax2.axhline(self.MEM_CRIT_KB, color="tab:orange",
            linestyle="--", linewidth=1, label="MEM CRIT", zorder=1, alpha=0.35)

        # 범례(두 축 라인 모두 병합)
        h1, l1 = self.ax1.get_legend_handles_labels()
        h2, l2 = self.ax2.get_legend_handles_labels()
        self.ax1.legend(h1 + h2, l1 + l2, loc="upper left", framealpha=0.9)

        # 날짜 포맷
        self.ax1.xaxis.set_major_locator(AutoDateLocator(minticks=5, maxticks=10))
        self.ax1.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))

        # 보기 좋게 회전
        self.fig.autofmt_xdate(rotation=20)

        # ── 우측 상단 고정 HUD (CPU | PSS, 각자 색상)
        self.hud_cpu_text = TextArea(
            "CPU --%", textprops=dict(color="tab:blue", fontsize=10)
        )
        self.hud_sep_text = TextArea(
            "  |  ", textprops=dict(color="0.3", fontsize=10)
        )
        self.hud_mem_text = TextArea(
            "PSS -- KB", textprops=dict(color="tab:orange", fontsize=10)
        )

        self.hud_line = HPacker(children=[self.hud_cpu_text, self.hud_sep_text, self.hud_mem_text],
                                align="center", pad=0, sep=0)

        self.hud_anchor = AnchoredOffsetbox(loc="upper right",  # ← 우측 상단 고정
                                            child=self.hud_line,
                                            pad=0.2, borderpad=0.25, frameon=True,
                                            bbox_to_anchor=(1.0, 1.0),
                                            bbox_transform=self.ax1.transAxes)

        # 배경(흰색 반투명, 라운드)
        self.hud_anchor.patch.set_alpha(0.85)
        self.hud_anchor.patch.set_facecolor("white")
        self.hud_anchor.patch.set_edgecolor("none")

        self.ax1.add_artist(self.hud_anchor)

        # 🔧 그래프 바깥쪽 여백 축소
        self.fig.subplots_adjust(
            left=0.09,   # 기본 0.125 → 그래프 왼쪽 여백 축소 (0.05 ~ 0.08)
            right=0.91,  # 기본 0.9   → 그래프 오른쪽 여백 축소 (0.95 ~ 0.98)
            bottom=0.15, # x축 라벨 영역 (필요시 조정) (0.10 ~ 0.12)
            top=0.9     # 상단 제목 등 여유 (0.93 ~ 0.95)
        )

        # 캔버스
        self.canvas = FigureCanvasTkAgg(self.fig, master=frm)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_status(self, parent=None):
        parent = parent or self
        frm = ttk.Frame(parent)
        frm.pack(side=tk.BOTTOM, fill=tk.X)

        self.var_status = tk.StringVar(value="Ready")
        s = ttk.Label(frm, textvariable=self.var_status, anchor="w")
        s.pack(side=tk.LEFT, fill=tk.X)

    def _build_logview(self, parent=None):
        parent = parent or self
        frm = ttk.Frame(parent)
        frm.pack(side=tk.BOTTOM, fill=tk.X)

        self.logview = scrolledtext.ScrolledText(frm, height=8, state="disabled")
        self.logview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def log(self, msg: str):
        # 안전 가드: logview 미생성 시 콘솔로만 출력
        if not hasattr(self, "logview") or self.logview is None:
            print(f"{dt.datetime.now():%H:%M:%S} {msg}")
            return
        try:
            self.logview.configure(state="normal")
            self.logview.insert(tk.END, f"{dt.datetime.now():%H:%M:%S} {msg}\n")
            if self.var_autoscroll.get():
                self.logview.see(tk.END)
        finally:
            self.logview.configure(state="disabled")

    def log_status(self, msg: str):
        self.var_status.set(msg)
        # 상태 메시지도 로그창에 남김
        self.log(msg)
    
    def _selected_serial(self):
        """
        라벨/원시 시리얼/ENV 모두 안정적으로 처리:
        - 콤보가 라벨(model(serial))을 들고 있어도 map으로 역매핑
        - var_serial이 '원시 시리얼'일 경우 그대로 사용
        - 둘 다 모호하면 ENV → 첫 디바이스 순서
        """
        # 1) 콤보 인덱스가 정해져 있으면 그 인덱스로
        try:
            idx = self.cmb_serial.current()
        except Exception:
            idx = -1

        if hasattr(self, "serials") and self.serials:
            # 콤보 인덱스 유효
            if idx is not None and 0 <= idx < len(self.serials):
                return self.serials[idx]

            # 2) var_serial 값 해석
            val = (self.var_serial.get() or "").strip()
            if val:
                # 라벨→시리얼 역매핑
                if hasattr(self, "map_label_to_serial") and val in self.map_label_to_serial:
                    return self.map_label_to_serial[val]
                # 원시 시리얼일 가능성
                if val in self.serials:
                    return val
                # 라벨 문자열에서 괄호 안 시리얼 추출 시도
                m = re.search(r"\(([^)]+)\)\s*$", val)
                if m and m.group(1) in self.serials:
                    return m.group(1)

            # 3) ENV 폴백
            env_ser = os.environ.get("ADB_SERIAL") or os.environ.get("ANDROID_SERIAL")
            if env_ser and env_ser in self.serials:
                return env_ser

            # 4) 최종 폴백: 첫 장치
            return self.serials[0]

        # serials가 아직 비어 있을 때의 극초기 폴백
        devs = list_devices()
        if devs:
            return devs[0]
        return None

    # ----- 컨트롤 -----
    def _update_toggle_label(self):
        """running 상태에 따라 토글 버튼 라벨 업데이트"""
        if hasattr(self, "btn_toggle") and self.btn_toggle is not None:
            self.btn_toggle.configure(text=("■ Stop" if self.running else "▶ Start"))

    def _on_toggle_start_stop(self):
        """토글 버튼 핸들러"""
        if self.running:
            self.stop()
        else:
            self.start()
        self._update_toggle_label()

    def start(self):
        if self.running: return
        self.serial = self._selected_serial()   # 👈 인덱스→시리얼
        self.pkg = (self.var_pkg.get() or "").strip() or (current_foreground_pkg(self.serial) or "")
        if not self.pkg:
            messagebox.showwarning("패키지 필요", "Package 값을 입력하거나 포그라운드를 감지하세요.")
            return

        # ✅ 시리얼 결정
        sel_serial = self.serial                 # 이미 확정한 값 사용
        self.log_status(f"[debug] selected={sel_serial}, combo={self.var_serial.get()}")

        # ✅ 결과 폴더 우선순위(안전 버전)
        #  - 외부 주입 RESULT_DIR(=run_id 등)인 경우에만 고정 사용
        #  - 단독 실행에서는 환경변수 RESULT_DIR이 이전 실행에서 남아 있어도 무시하고,
        #    항상 …\result\<serial>로 재계산한다.
        if getattr(self, "_external_result_dir", False) and self._external_result_dir_path:
            self.out_dir = self._external_result_dir_path
            os.makedirs(self.out_dir, exist_ok=True)
        else:
            self.out_dir = ensure_serial_result_dir(OUT_ROOT, sel_serial)

        # ✅ 하위 파일 경로 예시(기존 코드의 경로들을 모두 self.out_dir 기반으로 바꿔주세요)
        self.csv_path   = os.path.join(self.out_dir, "resource.csv")
        self.pid_path   = os.path.join(self.out_dir, "resource_monitor.pid")
        self.stat_path  = os.path.join(self.out_dir, "summary.txt")
        # … 기타 로그/스크린샷/첨부 파일들도 동일하게 교체

        # ✅ 하위 도구(event_tap 등) 일관성 위해 Start마다 주입
        os.environ["RESULT_DIR"] = self.out_dir           # 이후 실행될 도구들이 동일 폴더를 쓰도록
        if sel_serial:
            os.environ["ADB_SERIAL"] = sel_serial         # 실수 방지
            os.environ["ANDROID_SERIAL"] = sel_serial

        # ✅ [여기부터 추가] out_dir를 사용하는 컴포넌트들을 새 경로로 재바인딩
        # 1) ResourceBuffer가 기존 result 경로를 바라보던 문제 교정
        if hasattr(self, "buf") and self.buf is not None:
            self.buf.out_dir = self.out_dir
        else:
            self.buf = ResourceBuffer(self.out_dir, max_entries=MAX_ENTRIES)

        # 2) EventsTailer도 새 경로의 events.csv를 보도록 재생성
        self.tailer = EventsTailer(self.out_dir)
        self.tailer._pos = 0
        self.tailer._seen.clear()
        # ✅ [여기까지 추가]

        # ✅ UI에도 반영(상태바/제목 등)
        self.log_status(f"RESULT_DIR: {self.out_dir} (serial={sel_serial or 'unknown'})")

        # ── 초기화 ──────────────────────────────────
        # 기존 상태 리셋
        self.initial_pid = pid_of(self.pkg, self.serial)
        self.running = True
        self._crash_flagged = False
        self.log_status(f"Start: {self.pkg} (PID: {self.initial_pid or 'N/A'}, SERIAL: {self.serial or 'default'})")

        # ── 이벤트/CSV 초기화 ─────────────────────────────
        try:
            # 내부 상태 리셋
            self.events = []
            self._clear_event_artists()
            # 테일러 포인터/중복 집합 리셋
            if hasattr(self, "tailer"):
                self.tailer._pos = 0
                self.tailer._seen.clear()
            # 파일 초기화(옵션)
            ev = os.path.join(self.out_dir, "events.csv")
            if self.clear_events_on_start.get() and os.path.exists(ev):
                os.remove(ev)
                # 새 헤더 작성(선호 시)
                with open(ev, "w", encoding="utf-8-sig") as f:
                    f.write("timestamp,type,detail,level\n")
                self.log_status("[events] reset events.csv")
        except Exception as e:
            self.log_status(f"[events] reset fail: {e}")

        # 롤링 시작 (serial/로그 콜백 전달)
        self.roll = RollingLogcat(self.out_dir, serial=self.serial, logger=self.log)
        self.roll.start()

        # event_tap 시작 (stdout/stderr를 GUI 로그로)
        self.evtap = EventTapProc(self.pkg, self.out_dir, serial=self.serial, on_log=self.log)
        self.evtap.start()

        self._tick()
        self._update_toggle_label()

        # 로그캣 뷰어 시작
        try:
            # ... 기존 시작 로직
            if hasattr(self, "logcat_view"):
                self.logcat_view.start()
        except Exception as e:
            self.log_status(f"로그캣 뷰어 시작 실패: {e}")

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        try:
            # stop.flag → event_tap 정상종료
            sflag = os.path.join(self.out_dir, "stop.flag")
            open(sflag, "w").close()
        except Exception:
            pass
        if self.evtap:
            self.evtap.stop()
        self.roll.stop()
        self.log_status("Stopped")
        self._update_toggle_label()

        # ▶ 다음 실행에 A 잔상이 남지 않도록 핵심 상태 초기화
        self.initial_pid = None
        self.serial = None
        # (선택) self.out_dir = result_dir()  # 재시작 시 start()가 다시 올바른 경로로 재설정

        # 로그캣 뷰어 정지
        if hasattr(self, "logcat_view"):
            self.logcat_view.stop()

        # ✅ 단독 실행 모드에서는 RESULT_DIR을 정리해 다음 Start 오염을 줄인다.
        # (외부 주입 모드(run_id)에서는 건드리지 않음)
        if not getattr(self, "_external_result_dir", False):
            try:
                os.environ.pop("RESULT_DIR", None)
            except Exception:
                pass

    def on_close(self):
        try:
            self.stop()
            try:
                if getattr(self, "_flag_timer_id", None):
                    self.after_cancel(self._flag_timer_id)
            except Exception:
                pass
        finally:
            self.destroy()

    def _set_busy(self, on: bool, note: str = ""):
        """중첩 작업 대응 Busy 토글(0→잠금, 0보다 크면 계속 잠금 유지)"""
        try:
            # 카운터
            if on:
                self._busy_count += 1
            else:
                self._busy_count = max(0, self._busy_count - 1)

            lock = (self._busy_count > 0)

            # 커서/상태
            self.configure(cursor="watch" if lock else "")
            if note:
                try: self.var_status.set(note)
                except Exception: pass
                try: self.log(note)
                except Exception: pass

            # 모든 주요 버튼을 잠금
            for name in ("btn_toggle", "btn_save", "btn_report", "btn_detect"):
                btn = getattr(self, name, None)
                if btn is not None:
                    btn.configure(state=("disabled" if lock else "normal"))

            self.update_idletasks()
        except Exception:
            pass


    # ----- 주기 샘플링 -----
    def _tick(self):
        if not self.running:
            return
        try:
            ts, cpu, pss = sample_cpu_mem(self.pkg, self.initial_pid, self.serial)
            if cpu is not None and pss is not None:
                self.time_series.append(ts)
                self.cpu_series.append(cpu)
                self.mem_series.append(pss)
                # 버퍼 기록(파일 포맷 호환)
                self.buf.append(ts, self.pkg, self.initial_pid, cpu, pss)
                # 시리즈 제한
                if len(self.time_series) > MAX_SAMPLES:
                    self.time_series = self.time_series[-MAX_SAMPLES:]
                    self.cpu_series = self.cpu_series[-MAX_SAMPLES:]
                    self.mem_series = self.mem_series[-MAX_SAMPLES:]
                # 업데이트
                self._refresh_plot()
            else:
                # 여기서 현재 생존 PID를 확인
                alive_pid = pid_of(self.pkg, self.serial)

                if self.initial_pid:
                    if alive_pid is None:
                        # 크래시/종료 감지 → save.flag 1회 예약(가드 유지)
                        if not self._crash_flagged:
                            self.log_status("앱 종료/크래시 감지 — 자동 저장 예약")
                            try:
                                open(os.path.join(self.out_dir, "save.flag"), "w").close()
                            except Exception:
                                pass
                            self._crash_flagged = True
                    else:
                        # 🔹 앱이 다시 떠서 새 PID가 생겼으면 즉시 교체하고 계속 모니터링
                        if alive_pid != self.initial_pid:
                            self.initial_pid = alive_pid
                            self.log_status(f"앱 재실행 감지 — 모니터링 재개 (PID: {alive_pid})")

                            # ✅ [ADD] logcat 뷰어도 새 PID로 재시작
                            try:
                                if hasattr(self, "logcat_view") and self.logcat_view is not None:
                                    # LogcatLiveView.start() 내부에 stop()이 있어 중복 방지됨
                                    self.logcat_view.start()
                                    self.log_status(f"로그캣 뷰어 재시작(PID 갱신): {alive_pid}")
                            except Exception as e:
                                self.log_status(f"로그캣 뷰어 재시작 실패: {e}")

                            # 재무장: 다음 크래시에 다시 한 번만 save.flag 예약
                            self._crash_flagged = False

                else:
                    # 시작 당시 PID가 없었는데 지금 생겼다면(앱이 늦게 떴을 때)
                    if alive_pid:
                        self.initial_pid = alive_pid
                        self.log_status(f"앱 실행 감지 — 모니터링 시작 (PID: {alive_pid})")
                        self._crash_flagged = False
                        
        except Exception as e:
            self.log_status(f"샘플링 오류: {e}")
        finally:
            self.after_id = self.after(int(SAMPLE_INTERVAL_SEC * 1000), self._tick)

    def _find_latest_resource(self):
        try:
            files = [f for f in os.listdir(self.out_dir)
                     if re.match(r"^resource_\d{6}_\d{4}\.txt$", f)]
            files.sort(reverse=True)
            if files:
                return os.path.join(self.out_dir, files[0])
        except Exception:
            pass
        return None

    def _run_generate_report(self, target_log_path: str):
        # generate_report.py(또는 타임스탬프 버전) 탐색
        gen = os.path.join(script_dir(), "generate_report.py")
        if not os.path.exists(gen):
            cands = [f for f in os.listdir(script_dir())
                     if re.match(r"^generate_report_\d{6}-\d{4}\.py$", f)]
            cands.sort(reverse=True)
            if cands:
                gen = os.path.join(script_dir(), cands[0])
        if not os.path.exists(gen):
            messagebox.showerror("리포트", "generate_report 스크립트를 찾을 수 없습니다.")
            return

        prefix = os.path.join(self.out_dir, f"resource_report_{ts_file_stamp()}.pdf")
        # 백엔드 충돌 방지
        try:
            os.environ.pop("TCL_LIBRARY", None)
            os.environ.pop("TK_LIBRARY", None)
            os.environ["MPLBACKEND"] = "Agg"
        except Exception:
            pass

        try:
            subprocess.run([sys.executable, gen, "-i", target_log_path, "-o", prefix], check=False)
            self.log_status("리포트 생성 요청 완료")
        except Exception as e:
            messagebox.showerror("리포트", str(e))

    def _check_flags(self):
        try:
            # save.flag 감지 → 산출물 저장
            sflag = os.path.join(self.out_dir, "save.flag")
            if os.path.exists(sflag):
                mt = os.path.getmtime(sflag)
                if mt > self._flag_last.get("save", 0):
                    self._flag_last["save"] = mt
                    # ⬇ 플래그가 트리거한 저장이므로 set_flag=False
                    def _worker():
                        try:
                            self._do_save(reason="save.flag", set_flag=False)
                        finally:
                            self.after(0, lambda: self._set_busy(False))
                    self._set_busy(True, "로그 저장 중…")
                    threading.Thread(target=_worker, daemon=True).start()

            # report.flag 감지 → generate_report 실행
            rflag = os.path.join(self.out_dir, "report.flag")
            if os.path.exists(rflag):
                mt = os.path.getmtime(rflag)
                if mt > self._flag_last.get("report", 0):
                    self._flag_last["report"] = mt
                    target = self._find_latest_resource()
                    if target:
                        self._run_generate_report(target)
                    else:
                        self.log_status("리포트 대상 리소스 로그가 없습니다. 먼저 Save를 수행하세요.")
                    # report.flag 정리
                    try:
                        if os.path.exists(rflag): os.remove(rflag)
                    except Exception:
                        pass
        finally:
            # 1초 주기 폴링
            self._flag_timer_id = self.after(1000, self._check_flags)
            # [ADD] 이벤트 폴링도 1초 주기 동기화
            self._poll_and_draw_events()
    
    # ----- 이벤트 탭(추가 기능) -----
    # ── 2) _poll_and_draw_events(): 날짜 비교를 숫자로
    def _poll_and_draw_events(self):
        if not self.events_enabled.get():
            self._clear_event_artists()
            return

        new_items = self.tailer.poll_new()
        if new_items:
            self.events.extend(new_items)
            # 👇 디버그: 들어오는지 즉시 확인 가능(하단 로그창)
            self.log_status(f"[events] +{len(new_items)} new (total {len(self.events)})")

        try:
            x0, x1 = self.ax1.get_xlim()
        except Exception:
            return

        self._clear_event_artists()

        for (t, typ, detail, level) in self.events:
            ex = matplotlib.dates.date2num(t)
            if not (x0 <= ex <= x1):
                continue
            meta = EVENT_STYLE.get(typ, {"color": "gray", "linestyle": ":", "emoji": "•"})
            # ▶ 더 잘 보이도록: 굵기↑, 투명도↓, zorder↑
            v = self.ax1.axvline(ex, color=meta["color"], linestyle=meta["linestyle"],
                                linewidth=1.8, alpha=0.85, zorder=6)
            
            # 이모지/라벨 선택 (폰트 없을 때만 라벨 폴백)
            glyph = meta["emoji"] if self.emoji_font is not None else meta.get("label", typ)

            y_top = self.ax1.get_ylim()[1]
            txt = self.ax1.text(
                ex, y_top, glyph,
                ha="center", va="bottom",
                fontsize=(13 if self.emoji_font is not None else 10),
                zorder=7, clip_on=False,
                color=meta["color"],
                fontproperties=(self.emoji_font if self.emoji_font is not None else None)
            )
            self.event_artists.extend([v, txt])

        self.canvas.draw_idle()


    # 이벤트 마커 제거
    def _clear_event_artists(self):
        for a in self.event_artists:
            try:
                a.remove()
            except Exception:
                pass
        self.event_artists.clear()

    #----- 플롯 갱신 -----
    def _refresh_plot(self):
        xs = [matplotlib.dates.date2num(t) for t in self.time_series]
        self.line_cpu.set_data(xs, self.cpu_series)
        self.line_mem.set_data(xs, self.mem_series)

        if xs:
            self.ax1.set_xlim(xs[0], xs[-1])

        if self.cpu_series:
            y1_lo = min(min(self.cpu_series), self.CPU_WARN, self.CPU_CRIT)
            y1_hi = max(max(self.cpu_series), self.CPU_WARN, self.CPU_CRIT)
            m1 = max(5.0, (y1_hi - y1_lo) * 0.10)
            self.ax1.set_ylim(y1_lo - m1, y1_hi + m1)
            self.hud_cpu_text.set_text(f"CPU {self.cpu_series[-1]:.1f}%")

        if self.mem_series:
            y2_lo = min(min(self.mem_series), self.MEM_WARN_KB, self.MEM_CRIT_KB)
            y2_hi = max(max(self.mem_series), self.MEM_WARN_KB, self.MEM_CRIT_KB)
            m2 = max(20480.0, (y2_hi - y2_lo) * 0.10)
            self.ax2.set_ylim(y2_lo - m2, y2_hi + m2)
            self.hud_mem_text.set_text(f"PSS {self.mem_series[-1]:,} KB")

        # 🔁 축/데이터 갱신 직후 마커를 다시 그려서 보장
        self._poll_and_draw_events()

        self.canvas.draw_idle()



    # ----- 저장/리포트 -----
    def _do_save(self, reason: str = "manual", set_flag: bool = True):
        # save.flag 파일 기록(정보성 — 기존 플로우 호환)
        try:
            if set_flag:
                sflag = os.path.join(self.out_dir, "save.flag")
                with open(sflag, "w", encoding="utf-8") as f:
                    f.write(str(time.time()))
        except Exception:
            pass

        # 1) 리소스 버퍼
        res = self.buf.save()
        # 2) crash 버퍼, 3) recent 전체 + 패키지 필터, 4) 시작PID 필터, 5) 롤링 슬라이스
        f1 = save_logcat_crash(self.out_dir)
        f2 = save_logcat_recent_all(self.out_dir)
        if f2:
            _ = save_logcat_recent_pkg(self.out_dir, self.pkg)
        f3 = save_logcat_recent_pid(self.out_dir, self.initial_pid)
        f4 = self.roll.save_slice()
        self.log_status(f"저장 완료: {os.path.basename(res)}")

        # save.flag 정리
        try:
            sflag = os.path.join(self.out_dir, "save.flag")
            if os.path.exists(sflag): os.remove(sflag)
        except Exception:
            pass

        return res

    def on_save(self):
        if not self.pkg:
            messagebox.showinfo("안내", "Start 후 사용하세요.")
            return

        def _worker():
            try:
                # 플래그를 다시 쓰지 않아도 되므로 set_flag=False (원하면 True로)
                self._do_save(reason="manual", set_flag=False)
            except Exception as e:
                self.after(0, lambda: self.log_status(f"저장 오류: {e}"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        self._set_busy(True, "로그 저장 중…")
        threading.Thread(target=_worker, daemon=True).start()

    def on_report(self):
        if not self.pkg:
            messagebox.showinfo("안내", "Start 후 사용하세요.")
            return
        # report.flag만 생성 → 실제 실행은 _check_flags()가 담당
        try:
            rflag = os.path.join(self.out_dir, "report.flag")
            open(rflag, "w").close()
            self.log_status("리포트 플래그 생성 완료(곧 실행)")
        except Exception as e:
            messagebox.showerror("리포트", str(e))


# =============================================================
# main
# =============================================================
if __name__ == "__main__":
    
    # 디버그: 실행 환경 출력
    # print("GUI_PY", sys.executable)
    # print("GUI_CWD", os.getcwd())
    # print("GUI_RESULT_DIR", os.environ.get("RESULT_DIR",""))
    # print("GUI_SERIAL", os.environ.get("ANDROID_SERIAL","") or os.environ.get("ADB_SERIAL",""))

    # 0) 변수 세팅
    argv = sys.argv[1:]

    # ---- [ADD] --out-dir 파싱 (주체가 결과 폴더를 지정하는 경우)
    out_dir_arg = None
    for i, a in enumerate(argv):
        if a == "--out-dir" and i + 1 < len(argv):
            out_dir_arg = argv[i + 1]
            break

    if out_dir_arg:
        od = os.path.abspath(out_dir_arg)
        os.makedirs(od, exist_ok=True)
        os.environ["RESULT_DIR"] = od  # ✅ resource_monitor 전체 기준 폴더

    pkg = None
    ser = None

    # 1) 첫 번째 인자를 pkg로 본다
    if len(argv) >= 1 and argv[0] and not argv[0].startswith("--"):
        pkg = argv[0]

    # 2) 두 번째 인자를 serial로 본다
    if len(argv) >= 2 and argv[1] and not argv[1].startswith("--"):
        ser = argv[1]

    # 3) env에서 serial 보충
    if not ser:
        ser = os.getenv("ADB_SERIAL") or os.getenv("ANDROID_SERIAL")

    # 4) os.environ에 ANDROID_SERIAL을 먼저 주입 → 하위 adb가 기본으로 이 시리얼 사용
    if ser:
        os.environ["ANDROID_SERIAL"] = ser  # 중요!

    # 5) UI(app) 생성
    app = App()

    # 6) 여기서 pkg를 GUI에 주입해두면 start()가 그걸 먼저 쓴다
    if pkg:
        try:
            app.var_pkg.set(pkg)
        except Exception:
            pass

    # 7) 콤보박스 초기 선택도 ser로 고정
    if ser:
        # 라벨/시리얼 매핑이 준비된 이후에 '인덱스'까지 정확히 반영
        def _apply_ser():
            try:
                # _refresh_devs()가 먼저 실행되어 map_*이 준비되어 있어야 함
                if hasattr(app, "map_serial_to_label") and ser in app.map_serial_to_label:
                    label = app.map_serial_to_label[ser]
                    app.var_serial.set(label)
                    app.cmb_serial.set(label)
                else:
                    # map이 아직 없으면 raw 값이라도 넣어 두기
                    app.var_serial.set(ser)
            except Exception:
                pass
        app.after(200, _apply_ser)
    # auto-start 처리
    auto = ("--auto" in argv) or (os.getenv("RM_AUTO_START") == "1")

    def _late_init():
        # var_serial 값이 raw 시리얼이면 라벨로 전환해 인덱스 확정
        val = (app.var_serial.get() or "").strip()
        if hasattr(app, "map_serial_to_label") and val in getattr(app, "map_serial_to_label", {}):
            lab = app.map_serial_to_label[val]
            app.var_serial.set(lab)
            app.cmb_serial.set(lab)
        elif val and hasattr(app, "map_label_to_serial") and val in app.map_label_to_serial:
            # 이미 라벨이면 OK
            app.cmb_serial.set(val)

        if auto:
            app.start()
    app.after(300, _late_init)
    app.mainloop()
