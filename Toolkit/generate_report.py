# ==========================================================
# 🧪 Tool: QA Resource Report Generator
# 👤 Author: Eden Kim
# 📅 Date: 2026-02-09 - v1.0.6
#   - 리포트 생성 후 자동 오픈되지 않도록 수정
# ==========================================================
# • 목적: 리소스 로그(txt) → PDF/CSV/JSON 보고서 + 이벤트 마커/요약
# • 동적 임계: ADB 조회(코어/램 클래스) 기반 CPU 60%·80%, MEM 23%·28% 스케일링(실패 시 기본값)
# • 그래프: CPU(좌)/PSS(우) + WARN/CRIT/P95 라인·음영, 시간눈금 자동, 한글/이모지 폰트 대비
# • KPI: max/avg/P95, 경고/임계 연속구간, 메모리 누수 기울기(KB/분) → PASS/FAIL
# • 이벤트: events.csv(리포트 범위 ±10분) → 1p 마커(💥⛔⚙🔖), 3p 텍스트 요약, *_events.csv 별도 저장
# • 산출물: resource_report_YYMMDD_HHMM.(pdf/csv/json) + resource_report_*_events.csv
# • 주의: 입력 포맷(top 9번째=%CPU / "TOTAL <PSSKB>") 불일치 시 파싱 실패
# ==========================================================
# -*- coding: utf-8 -*-
import os, re, math, json, csv, argparse, subprocess, platform
os.environ.setdefault("MPLBACKEND", "Agg")  # ① 환경변수 경로보다 우선 적용
import csv, datetime as dt, os
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
import matplotlib
matplotlib.use("Agg", force=True)           # ② 코드 레벨 강제
from matplotlib import pyplot as plt        # ③ 이후 pyplot import
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.dates import DateFormatter, MinuteLocator, SecondLocator
from matplotlib import font_manager as fm

# 🔠 한글 깨짐 방지 (기존 원칙 유지)
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

# =========================
# [기본 임계치(고정값)] — 장치 미연결/조회 실패 시 사용
#   * 4GB급 단말을 가정한 보수적 기본선
# =========================
CPU_WARN = 250.0          # % (WARN: 지속 고부하 경고선)
CPU_CRIT = 350.0          # % (CRIT: 임계선)
MEM_WARN_KB = 900_000     # KB
MEM_CRIT_KB = 1_100_000   # KB

# 메모리 누수 의심 기준(분당 증가량, KB/min)
LEAK_SUSPECT_KB_PER_MIN = 50_000

# 🔧 동적 임계치 사용 플래그(원하면 False로 끌 수 있음)
DYNAMIC_THRESHOLDS = True
CPU_WARN_PCT = 0.60   # CPU 코어 기준 경고 비율
CPU_CRIT_PCT = 0.80   # CPU 코어 기준 임계 비율
MEM_WARN_PCT = 0.23   # 램 클래스 기준 경고 비율
MEM_CRIT_PCT = 0.28   # 램 클래스 기준 임계 비율

# 동적 임계치 메타(보고서 표기용)
CORE_COUNT = None          # 예: 8
RAM_TOTAL_KB_REAL = None   # /proc/meminfo 실측값
RAM_CLASS_NAME = None      # 예: "4GB"
RAM_CLASS_KB = None        # 예: 3_900_000

# =========================
# 유틸리티
# =========================
# === 메타 추출: 패키지/ PID/ 시리얼 ==========================================
def _extract_meta_from_log(file_path: str):
    """
    우선순위:
      1) 리소스 로그 내부의 "[Package] <pkg> (PID: <pid>)" 라인
      2) 환경변수 ANDROID_SERIAL / ADB_SERIAL
      3) 파일 경로의 result/<serial>/ 폴더명 추론
    """
    pkg = None
    pid = None

    # 1) 로그 내부 파싱 (resource_monitor_gui 가 기록)
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            for raw in f:
                m = re.search(r'^\[Package\]\s+([A-Za-z0-9_.]+)\s+\(PID:\s*([0-9]+|None)\)', raw.strip())
                if m:
                    pkg = m.group(1)
                    pid = None if m.group(2) == "None" else int(m.group(2))
                    break
    except Exception:
        pass

    # 2) 시리얼: ENV 우선
    serial = os.getenv("ANDROID_SERIAL") or os.getenv("ADB_SERIAL")

    # 3) 경로 추론: .../result/<serial>/resource_YYMMDD_HHMM.txt
    if not serial:
        try:
            d = os.path.abspath(os.path.dirname(file_path))
            cand = os.path.basename(d)
            if re.match(r"^[A-Za-z0-9._:-]+$", cand):
                serial = cand
        except Exception:
            pass

    return pkg, pid, serial

# 이벤트 리드
def _truncate(s: str, n: int = 100) -> str:
    return s if len(s) <= n else (s[: n - 1] + "…")

# === 이모지 폰트 활성화(Windows/ macOS/ Linux 대응) ===
def _setup_emoji_font():
    # 각 OS별 대표 이모지 폰트 후보
    candidates = [
        (r"C:\Windows\Fonts\seguiemj.ttf", "Segoe UI Emoji"),
        (r"C:\Windows\Fonts\seguisym.ttf", "Segoe UI Symbol"),
        ("/System/Library/Fonts/Apple Color Emoji.ttc", "Apple Color Emoji"),
        ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "Noto Color Emoji"),
        ("/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf", "Noto Emoji"),
    ]

    found_names = []
    for path, name in candidates:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)  # 폰트 등록
                found_names.append(name)
            except Exception:
                pass

    # 한글 우선 → 이모지 폰트 폴백 → 기본 산세리프
    families = ["Malgun Gothic"] + found_names + ["DejaVu Sans"]
    matplotlib.rcParams["font.family"] = families
    matplotlib.rcParams["font.sans-serif"] = families

    # PDF/PS에 TrueType 임베드(이모지 글리프 빠짐 방지)
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"]  = 42
    matplotlib.rcParams["text.usetex"] = False

_setup_emoji_font()

def render_summary(ax, lines, fontsize=12, spacing=1.12, top=0.02, bottom=0.06):
    """
    줄 간격(spacing): 1.0=기본, 1.2=20% 더 넓게, 0.9=10% 좁게.
    전체 여백(top/bottom) 내에서 항상 맞춰 들어가도록 단위를 계산한다.
    """
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    n = max(len(lines), 1)
    usable = max(1.0 - top - bottom, 0.1)

    g = max(spacing, 0.5)                   # 너무 작아지지 않게 하한
    total_units = n + (n - 1) * (g - 1.0)   # n줄 + (줄 사이)추가 여백
    unit = usable / total_units             # 한 줄의 '기본 높이' 단위

    y = 1.0 - top
    for i, line in enumerate(lines):
        y -= unit                           # 현재 줄의 baseline
        ax.text(0.02, y, line, fontsize=fontsize, va="top", ha="left")
        if i < n - 1:
            y -= unit * (g - 1.0)           # 다음 줄과의 추가 여백

def _strip_bom(s: str) -> str:
    """일부 로그 첫 줄에 붙는 BOM(유니코드 서명) 보정"""
    return s.lstrip("\ufeff")


def _set_time_ticks(ax, timestamps):
    """
    시계열 범위에 따라 시간 눈금을 촘촘하게 설정.
      - 10분 이하: 30초 간격 (시:분:초)
      - 30분 이하: 1분 간격 (시:분)
      - 2시간 이하: 5분 간격 (시:분)
      - 그 이상: 10분 간격 (시:분)
    """
    if not timestamps:
        return
    span_sec = (timestamps[-1] - timestamps[0]).total_seconds()
    if span_sec <= 10 * 60:
        locator = SecondLocator(interval=30)
        fmt = DateFormatter("%H:%M:%S")
    elif span_sec <= 30 * 60:
        locator = MinuteLocator(interval=1)
        fmt = DateFormatter("%H:%M")
    elif span_sec <= 2 * 60 * 60:
        locator = MinuteLocator(interval=5)
        fmt = DateFormatter("%H:%M")
    else:
        locator = MinuteLocator(interval=10)
        fmt = DateFormatter("%H:%M")

    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(fmt)
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(20)
        lbl.set_ha("right")


def _percentile(sorted_values, p: float) -> float:
    """외부 의존성 없이 p-퍼센타일(P95 등) 계산 (선형 보간) — 입력은 정렬 리스트 가정"""
    n = len(sorted_values)
    if n == 0:
        return float('nan')
    if n == 1:
        return float(sorted_values[0])
    rank = (p / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def _contiguous_spans_over(series, times, threshold):
    """threshold 초과 구간을 (start_idx, end_idx, duration_sec) 리스트로 반환"""
    spans = []
    start = None
    for i, v in enumerate(series):
        if v > threshold and start is None:
            start = i
        if (v <= threshold or i == len(series) - 1) and start is not None:
            end = i if v > threshold and i == len(series) - 1 else i - 1
            dt = (times[end] - times[start]).total_seconds()
            spans.append((start, end, dt))
            start = None
    return spans


def _linear_slope_kb_per_min(times, mem_kb):
    """메모리 PSS의 1차 회귀 기울기(KB/분) — 최소자승(수식)로 계산"""
    n = len(times)
    if n < 2:
        return 0.0
    t0 = times[0]
    xs = [(t - t0).total_seconds() / 60.0 for t in times]   # 분 단위
    ys = [float(m) for m in mem_kb]
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return 0.0
    slope = (n * sxy - sx * sy) / denom
    return float(slope)


# =========================
# 동적 임계치(코어/총RAM 기반)
#  - adb로 장치 스펙 조회 → WARN/CRIT 자동 스케일링
#  - 실패 시 기본 상수 유지
# =========================
SER = os.getenv("ANDROID_SERIAL") or os.getenv("ADB_SERIAL")
def _adb_out(args):
    base = ["adb"]
    if SER: base += ["-s", SER]
    """['cat','/proc/meminfo'] 처럼 list 인자를 받아 UTF-8 문자열 반환"""
    return subprocess.check_output(base + ["shell"] + args, encoding="utf-8", errors="ignore")


def _get_device_cores(default=8):
    """
    안드로이드 단말에서 코어 수를 안전하게 추출(Windows 호스트 호환).
    우선순위:
      1) /sys/devices/system/cpu/possible (예: "0-7" → 8개)
      2) /sys/devices/system/cpu/present  (예: "0-3,4-7")
      3) /proc/cpuinfo의 'processor :' 라인 개수
    실패 시 default 반환
    """
    def _count_ranges(expr: str) -> int:
        # "0-3,4-7" 또는 "0-7" 같은 표현을 정수 개수로 변환
        expr = expr.strip()
        if not expr:
            return 0
        total = 0
        for part in expr.split(","):
            part = part.strip()
            m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", part)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if b >= a:
                    total += (b - a + 1)
            else:
                if part.isdigit():
                    total += 1
        return total

    try:
        out = _adb_out(["cat", "/sys/devices/system/cpu/possible"])
        n = _count_ranges(out)
        if n > 0:
            return n
    except Exception:
        pass

    try:
        out = _adb_out(["cat", "/sys/devices/system/cpu/present"])
        n = _count_ranges(out)
        if n > 0:
            return n
    except Exception:
        pass

    try:
        txt = _adb_out(["cat", "/proc/cpuinfo"])
        n = len(re.findall(r"(?m)^\s*processor\s*:\s*\d+\s*$", txt))
        if n > 0:
            return n
    except Exception:
        pass

    return default


def _get_memtotal_kb(default=3_900_000):
    """총 메모리(KB) 탐지. 실패 시 default(≈4GB급)"""
    try:
        out = _adb_out(["cat", "/proc/meminfo"])
        m = re.search(r"MemTotal:\s+(\d+)\s*kB", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return default

def _nearest_ram_class_kb(memtotal_kb: int):
    """
    MemTotal(KB)을 가장 가까운 'RAM 클래스' 표준값으로 스냅.
    표준값은 현장 체감치(커널/예약 메모리 차감 후 대략치)로 잡았습니다.
    """
    classes = {
        "2GB":  1_950_000,
        "3GB":  2_950_000,
        "4GB":  3_900_000,  # ← 4GB급은 보통 3.8~3.95M 사이로 관측
        "6GB":  5_800_000,
        "8GB":  7_800_000,
        "12GB": 11_700_000,
    }
    # 가장 가까운 클래스 선택
    name, base_kb = min(classes.items(), key=lambda kv: abs(memtotal_kb - kv[1]))
    return name, base_kb

def _compute_dynamic_thresholds():
    """
    동적 기준(버킷팅 버전):
      - CPU: WARN=0.60×100×코어수, CRIT=0.80×100×코어수
      - MEM: MemTotal을 가장 가까운 RAM 클래스 표준값으로 스냅 → WARN/CRIT = MEM_WARN_PCT/MEM_CRIT_PCT 적용
    """
    cores = _get_device_cores()
    memkb_real = _get_memtotal_kb()

    # 램 클래스 스냅 + 보수적 비율 적용
    ram_class_name, ram_class_kb = _nearest_ram_class_kb(memkb_real)
    mem_warn = int(MEM_WARN_PCT * ram_class_kb)
    mem_crit = int(MEM_CRIT_PCT * ram_class_kb)

    cpu_warn = int(CPU_WARN_PCT * 100 * cores)
    cpu_crit = int(CPU_CRIT_PCT * 100 * cores)

    print(
        f"[QAGrad] Dynamic thresholds → cores={cores}, "
        f"MemTotal(real)={memkb_real:,}KB → RAM class={ram_class_name}({ram_class_kb:,}KB), "
        f"MEM WARN/CRIT={mem_warn:,}/{mem_crit:,} KB (pct {MEM_WARN_PCT:.2f}/{MEM_CRIT_PCT:.2f})"
    )
    # ⬇ 램 클래스 정보까지 반환
    return cores, memkb_real, ram_class_name, ram_class_kb, cpu_warn, cpu_crit, mem_warn, mem_crit


def apply_dynamic_thresholds():
    """전역 임계치 덮어쓰고, 메타값도 전역에 저장(보고서에서 사용)"""
    global CPU_WARN, CPU_CRIT, MEM_WARN_KB, MEM_CRIT_KB
    global CORE_COUNT, RAM_TOTAL_KB_REAL, RAM_CLASS_NAME, RAM_CLASS_KB

    (cores, memkb_real, ram_name, ram_kb,
     cw, cc, mw, mc) = _compute_dynamic_thresholds()

    CPU_WARN, CPU_CRIT, MEM_WARN_KB, MEM_CRIT_KB = cw, cc, mw, mc
    CORE_COUNT, RAM_TOTAL_KB_REAL, RAM_CLASS_NAME, RAM_CLASS_KB = cores, memkb_real, ram_name, ram_kb

    return cores, memkb_real


# =========================
# 파서 (기존 포맷 유지)
#  - [YYYY-MM-DD HH:MM:SS]
#  - CPU: top 행의 9번째 컬럼을 %CPU로 사용(헤더 제외)
#  - Memory: 'TOTAL <숫자>'를 PSS(KB)로 사용
#  - BOM 보정 추가
# =========================
def parse_resource_log(file_path):
    timestamps, cpu_values, mem_pss = [], [], []
    current_timestamp = None
    current_cpu = None
    current_mem = None

    with open(file_path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = _strip_bom(raw.strip())

            # [타임스탬프]
            m_ts = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if m_ts:
                current_timestamp = datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")
                continue

            # CPU 라인(헤더 제외)
            if re.match(r"^\d+\s+\S+", line) and "%CPU" not in line:
                parts = line.split()
                if len(parts) > 8:
                    try:
                        current_cpu = float(parts[8])  # 0-based → 9번째 컬럼
                    except ValueError:
                        current_cpu = None
                continue

            # Memory TOTAL (신/구 포맷 모두 지원)
            # 예)
            #   TOTAL PssTotal 255,064 kB    VmRSS 255,064 kB    Threads 76
            #   TOTAL     255,064 kB    255,064 kB      76
            #   TOTAL 255064
            m_new1 = re.search(r'^TOTAL\s+PssTotal\s+([\d,]+)\s*kB', line, re.I)
            m_new2 = re.search(r'^TOTAL\s+([\d,]+)\s*kB', line, re.I)
            m_old  = None if (m_new1 or m_new2) else re.search(r'^TOTAL\s+(\d+)\b', line)
            m_na   = re.search(r'^TOTAL\s+N/?A\b', line, re.I)

            if m_na:
                current_mem = None  # N/A는 샘플 생략
            elif m_new1 or m_new2 or m_old:
                raw = (m_new1 or m_new2 or m_old).group(1)
                current_mem = int(raw.replace(',', ''))
                if current_timestamp and (current_cpu is not None):
                    timestamps.append(current_timestamp)
                    cpu_values.append(current_cpu)
                    mem_pss.append(current_mem)
                    current_cpu = None
                    current_mem = None
                continue

    return timestamps, cpu_values, mem_pss


# =========================
# KPI 계산 및 리포트 생성
#  - CSV/JSON 동시 생성
#  - 경고/임계 구간 음영(axvspan)
#  - P95/최대·최소 주석, 범례 라벨
#  - y축: 데이터+가이드라인 기준으로 산정(임계선 항상 보이기)
# =========================
def generate_report(file_path, timestamps, cpu_values, mem_pss, output_path):
    if not timestamps:
        messagebox.showerror("오류", "파싱된 데이터가 없습니다. 로그 포맷을 확인하세요.")
        return
    
    # ▶▶ 추가: 메타 추출
    meta_pkg, meta_pid, meta_serial = _extract_meta_from_log(file_path)

    # 출력 경로들
    base = os.path.splitext(output_path)[0]
    pdf_path = base + ".pdf"
    csv_path = base + ".csv"
    ev_csv_path = base + "_events.csv"
    json_path = base + ".json"

    # P95 계산
    cpu_p95 = _percentile(sorted(cpu_values), 95.0)
    mem_p95 = _percentile(sorted(mem_pss), 95.0)

    # KPI: 평균/최대/P95, 연속 초과 구간, 누수 추세
    cpu_max = max(cpu_values)
    cpu_min = min(cpu_values)
    mem_max = max(mem_pss)
    mem_min = min(mem_pss)

    cpu_avg = sum(cpu_values) / len(cpu_values)
    mem_avg = sum(mem_pss) / len(mem_pss)

    cpu_warn_spans = _contiguous_spans_over(cpu_values, timestamps, CPU_WARN)
    cpu_crit_spans = _contiguous_spans_over(cpu_values, timestamps, CPU_CRIT)
    mem_warn_spans = _contiguous_spans_over(mem_pss, timestamps, MEM_WARN_KB)
    mem_crit_spans = _contiguous_spans_over(mem_pss, timestamps, MEM_CRIT_KB)

    mem_slope = _linear_slope_kb_per_min(timestamps, mem_pss)

    # PASS/FAIL 판정
    verdict_notes = []
    if cpu_crit_spans:
        verdict_notes.append("CPU 임계치 초과 발생")
    if mem_crit_spans:
        verdict_notes.append("메모리 임계치 초과 발생")
    if mem_slope >= LEAK_SUSPECT_KB_PER_MIN:
        verdict_notes.append(f"메모리 누수 의심(분당 +{int(mem_slope):,} KB)")
    if not verdict_notes and (cpu_warn_spans or mem_warn_spans):
        verdict_notes.append("경고 구간 존재(임계치 미만)")

    overall = "FAIL" if (cpu_crit_spans or mem_crit_spans or mem_slope >= LEAK_SUSPECT_KB_PER_MIN) else "PASS"

    # CSV 저장(원시 시계열)
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "cpu_percent", "mem_pss_kb"])
            for t, c, m in zip(timestamps, cpu_values, mem_pss):
                w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), f"{c:.2f}", f"{int(m)}"])
    except Exception as e:
        print(f"[WARN] CSV 저장 실패: {e}")

    # --- 이벤트 읽기 & 요약(리포트 범위 ±10분) ---
    from collections import Counter
    from datetime import timedelta

    def read_events_csv(csv_path):
        out = []
        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                r = csv.DictReader(f)
                for row in r:
                    t = dt.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                    out.append((t, row["type"], row["detail"], row["level"]))
        except FileNotFoundError:
            pass
        return out

    _ev_all = read_events_csv(os.path.join(os.path.dirname(file_path), "events.csv"))
    if not _ev_all:
        _p2 = os.path.abspath(os.path.join(os.path.dirname(file_path), os.pardir, "events.csv"))
        if os.path.exists(_p2):
            _ev_all = read_events_csv(_p2)

    _t0 = timestamps[0] - timedelta(minutes=1)
    _t1 = timestamps[-1] + timedelta(minutes=1)
    events_in = [(t, typ, detail, lvl) for (t, typ, detail, lvl) in _ev_all if _t0 <= t <= _t1]
    ev_counts = Counter([typ for _, typ, _, _ in events_in])

    # 이벤트 전용 CSV 저장(리포트 범위 내만)
    try:
        with open(ev_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "type", "level", "detail"])
            for t, typ, detail, lvl in sorted(events_in, key=lambda x: x[0]):
                w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), typ, lvl, detail])
    except Exception as e:
        print(f"[WARN] 이벤트 CSV 저장 실패: {e}")

    # JSON 저장(KPI + 이벤트 요약)
    try:
        summary_obj = {
            "file": os.path.basename(file_path),
            "range": {"start": str(timestamps[0]), "end": str(timestamps[-1])},
            "samples": len(timestamps),
            "meta": {                            # ▶▶ 추가
                "package": meta_pkg,
                "pid": meta_pid,
                "serial": meta_serial,
            },
            "criteria": {
                "cpu_warn_percent": int(CPU_WARN),
                "cpu_crit_percent": int(CPU_CRIT),
                "mem_warn_kb": int(MEM_WARN_KB),
                "mem_crit_kb": int(MEM_CRIT_KB),
                "leak_suspect_kb_per_min": int(LEAK_SUSPECT_KB_PER_MIN),
            },
            "cpu": {
                "max": cpu_max, "min": cpu_min, "avg": cpu_avg, "p95": cpu_p95,
                "warn_spans": cpu_warn_spans, "crit_spans": cpu_crit_spans
            },
            "mem": {
                "max": mem_max, "min": mem_min, "avg": mem_avg, "p95": mem_p95,
                "warn_spans": mem_warn_spans, "crit_spans": mem_crit_spans,
                "slope_kb_per_min": mem_slope
            },
            "verdict": {"overall": overall, "notes": verdict_notes or ["이상 없음"]
            },
            "events": {
                "count": len(events_in),
                "by_type": {k: int(v) for k, v in ev_counts.items()}
            },
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] JSON 저장 실패: {e}")

    # PDF 생성
    with PdfPages(pdf_path) as pdf:
        # --- 1) 시계열 그래프 ---
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax1.grid(True, alpha=0.25)
        _set_time_ticks(ax1, timestamps)
        ax1.set_xlim(timestamps[0], timestamps[-1])

        # CPU (좌축)
        ax1.set_xlabel("Timestamp")
        ax1.set_ylabel("CPU Usage (%)", color="tab:blue")
        line_cpu, = ax1.plot(timestamps, cpu_values, label="CPU (%)", color="tab:blue", linewidth=2)
        ax1.tick_params(axis='y', labelcolor="tab:blue")

        # MEM (우축)
        ax2 = ax1.twinx()
        ax2.set_ylabel("Memory PSS (KB)", color="tab:orange")
        line_mem, = ax2.plot(timestamps, mem_pss, label="Memory PSS", color="tab:orange", linewidth=2)
        ax2.tick_params(axis='y', labelcolor="tab:orange")

        # ── 가이드라인(경고/임계/P95) + 범례 라벨 ──
        cpu_warn_line = ax1.axhline(CPU_WARN, color="tab:blue", linestyle=":",  linewidth=1, label="CPU 경고선 (WARN)")
        cpu_crit_line = ax1.axhline(CPU_CRIT, color="tab:blue", linestyle="--", linewidth=1, label="CPU 임계선 (CRIT)")
        cpu_p95_line = None
        if cpu_p95 == cpu_p95:  # not NaN
            cpu_p95_line = ax1.axhline(cpu_p95, color="tab:blue", linestyle="-.", linewidth=1, label="CPU P95")

        mem_warn_line = ax2.axhline(MEM_WARN_KB, color="tab:orange", linestyle=":",  linewidth=1, label="MEM 경고선 (WARN)")
        mem_crit_line = ax2.axhline(MEM_CRIT_KB, color="tab:orange", linestyle="--", linewidth=1, label="MEM 임계선 (CRIT)")
        mem_p95_line = None
        if mem_p95 == mem_p95:
            mem_p95_line = ax2.axhline(mem_p95, color="tab:orange", linestyle="-.", linewidth=1, label="MEM P95")

        # ── 임계/경고 구간 음영(axvspan) ──
        for s, e, _ in cpu_crit_spans:
            ax1.axvspan(timestamps[s], timestamps[e], color="tab:blue", alpha=0.12)
        for s, e, _ in cpu_warn_spans:
            ax1.axvspan(timestamps[s], timestamps[e], color="tab:blue", alpha=0.06)

        for s, e, _ in mem_crit_spans:
            ax2.axvspan(timestamps[s], timestamps[e], color="tab:orange", alpha=0.12)
        for s, e, _ in mem_warn_spans:
            ax2.axvspan(timestamps[s], timestamps[e], color="tab:orange", alpha=0.06)

        # ── y축: 데이터 + 가이드라인을 모두 포함하도록 산정(임계선이 항상 보이게) ──
        cpu_guides = [CPU_WARN, CPU_CRIT]
        if cpu_p95 == cpu_p95:
            cpu_guides.append(cpu_p95)
        y1_lo = min([cpu_min] + cpu_guides)
        y1_hi = max([cpu_max] + cpu_guides)
        y1_margin = max(5.0, (y1_hi - y1_lo) * 0.10)  # 최소 마진 5%
        ax1.set_ylim(y1_lo - y1_margin, y1_hi + y1_margin)

        mem_guides = [MEM_WARN_KB, MEM_CRIT_KB]
        if mem_p95 == mem_p95:
            mem_guides.append(mem_p95)
        y2_lo = min([mem_min] + mem_guides)
        y2_hi = max([mem_max] + mem_guides)
        y2_margin = max(20480.0, (y2_hi - y2_lo) * 0.10)  # 최소 마진 20MB
        ax2.set_ylim(y2_lo - y2_margin, y2_hi + y2_margin)

        # ── 최대/최소 화살표 주석 ──
        i_cpu_max = cpu_values.index(cpu_max)
        i_cpu_min = cpu_values.index(cpu_min)
        ax1.annotate(f"최대 {cpu_values[i_cpu_max]:.1f}%",
                     xy=(timestamps[i_cpu_max], cpu_values[i_cpu_max]),
                     xytext=(10, 12), textcoords="offset points",
                     arrowprops=dict(arrowstyle="->", color="tab:blue"),
                     color="tab:blue", fontsize=9)
        ax1.annotate(f"최소 {cpu_values[i_cpu_min]:.1f}%",
                     xy=(timestamps[i_cpu_min], cpu_values[i_cpu_min]),
                     xytext=(10, -18), textcoords="offset points",
                     arrowprops=dict(arrowstyle="->", color="tab:blue"),
                     color="tab:blue", fontsize=9)

        i_mem_max = mem_pss.index(mem_max)
        i_mem_min = mem_pss.index(mem_min)
        ax2.annotate(f"최대 {mem_pss[i_mem_max]:,}KB",
                     xy=(timestamps[i_mem_max], mem_pss[i_mem_max]),
                     xytext=(10, 12), textcoords="offset points",
                     arrowprops=dict(arrowstyle="->", color="tab:orange"),
                     color="tab:orange", fontsize=9)
        ax2.annotate(f"최소 {mem_pss[i_mem_min]:,}KB",
                     xy=(timestamps[i_mem_min], mem_pss[i_mem_min]),
                     xytext=(10, -18), textcoords="offset points",
                     arrowprops=dict(arrowstyle="->", color="tab:orange"),
                     color="tab:orange", fontsize=9)

        # ── 범례(두 축 라인 모두 합치기) ──
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, loc="upper left", framealpha=0.9)

        # === 이벤트 마커 표시 ===
        for t, typ, detail, lvl in events_in:
            color, style, mark = ("gray", ":", "•")
            if   typ == "CRASH": color, style, mark = ("crimson","-","💥")
            elif typ == "ANR":   color, style, mark = ("purple","-.", "⛔")
            elif typ == "GC":    color, style, mark = ("gray", ":", "⚙")
            elif typ == "STEP":  color, style, mark = ("teal", ":", "🔖")
            ax1.axvline(t, color=color, linestyle=style, alpha=0.5)
            ax1.text(t, ax1.get_ylim()[1], mark, ha="center", va="bottom", fontsize=10)

        # === 상단 타이틀/메타 라인 구성 ==========================================
        # 메인 타이틀(기존 ax1.set_title 이 있으면 그대로 두고, 없으면 아래처럼 메인 타이틀을 넣어도 됩니다)
        main_title = f"Resource Report - {os.path.basename(file_path)}"
        try:
            # 메인 타이틀을 '그림 전체 제목'으로(굵게)
            fig.suptitle(main_title, fontsize=13, fontweight="bold", y=0.98)
        except Exception:
            pass

        # 메타 문자열(패키지/ PID/ 시리얼) — 너무 길면 잘라서 표시
        def _shorten(s, n=60):
            return (s[:n-1] + "…") if (s and len(s) > n) else (s or "-")

        meta_str = "  |  ".join([
            f"📦 {_shorten(meta_pkg)}",
            f"🧩 PID {meta_pid}",
            f"🔌 {_shorten(meta_serial, 40)}"
        ])

        # 메타는 메인 타이틀 바로 아래 '얇은 서브타이틀'처럼 중앙 정렬로 배치
        fig.text(0.5, 0.945, meta_str, ha="center", va="top", fontsize=10, alpha=0.95)

        # 타이틀 2줄을 위한 상단 여백 확보
        # (둘 중 하나만 쓰면 됩니다. 선호에 따라 선택)
        # 방법 A) tight_layout 영역 줄이기
        # fig.tight_layout(rect=[0, 0.0, 1, 0.92])

        # 방법 B) 여백만 직접 늘리기(이미 tight_layout을 쓰는 경우 권장)
        plt.subplots_adjust(top=0.88)
        # ========================================================================

        fig.tight_layout()
        pdf.savefig()
        plt.close(fig)

        # --- 2) KPI & 판정 페이지 ---
        def _fmt_spans(spans):
            return "없음" if not spans else "; ".join(
                [f"{timestamps[s].strftime('%H:%M:%S')}~{timestamps[e].strftime('%H:%M:%S')}({int(dt)}s)" for s, e, dt in spans]
            )

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.subplots_adjust(left=0.05, right=0.98, top=0.95, bottom=0.08)
        lines = []
        lines.append(f"📄 파일: {os.path.basename(file_path)}")
        lines.append(f"🕒 범위: {timestamps[0]} ~ {timestamps[-1]}")
        lines.append(f"📊 샘플 수: {len(timestamps)}")
        core_str = str(CORE_COUNT) if CORE_COUNT is not None else "-"
        ram_class_str = f"{RAM_CLASS_NAME}={RAM_CLASS_KB:,}KB" if RAM_CLASS_KB else "-"

        lines.append(
            f"기준값 | CPU WARN/CRIT(Core:{core_str}): {int(CPU_WARN)}% / {int(CPU_CRIT)}%  "
            f"|  MEM WARN/CRIT(RAM:{ram_class_str}): {int(MEM_WARN_KB):,}KB / {int(MEM_CRIT_KB):,}KB"
        )
        lines.append("")
        lines.append(f"CPU  | max {cpu_max:.1f}%  avg {cpu_avg:.1f}%  p95 {cpu_p95:.1f}%")
        lines.append(f"MEM  | max {mem_max:,}KB  avg {int(mem_avg):,}KB  p95 {int(mem_p95):,}KB")
        lines.append(f"LEAK | 추세 기울기: {int(mem_slope):,} KB/분 (기준 {LEAK_SUSPECT_KB_PER_MIN:,} KB/분)")
        lines.append("")
        lines.append(f"⚠ CPU 경고 구간: {_fmt_spans(cpu_warn_spans)}")
        lines.append(f"🚨 CPU 임계 구간: {_fmt_spans(cpu_crit_spans)}")
        lines.append(f"⚠ MEM 경고 구간: {_fmt_spans(mem_warn_spans)}")
        lines.append(f"🚨 MEM 임계 구간: {_fmt_spans(mem_crit_spans)}")
        lines.append("")
        lines.append(f"✅ 판정: {overall}")
        for note in verdict_notes or ["이상 없음"]:
            lines.append(f" - {note}")

        render_summary(ax, lines, fontsize=12, spacing=1.10, top=0.02, bottom=0.08)   # ← 한 줄씩 안전 배치
        pdf.savefig()
        plt.close(fig)

        # --- 3) 이벤트 타임라인 요약(최근 30건, 시간순) ---
        if events_in:
            # 높이를 키워 글자 겹침 방지
            fig, ax = plt.subplots(figsize=(12, 6.2))

            lines = []
            lines.append(
                f"🧷 이벤트 요약: 총 {len(events_in)}건"
                f" (ANR {ev_counts.get('ANR',0)}, CRASH {ev_counts.get('CRASH',0)}, "
                f"GC {ev_counts.get('GC',0)}, STEP {ev_counts.get('STEP',0)})"
            )
            lines.append("※ 아래 목록은 최근 30건(시간순) 기준입니다.")
            lines.append("")

            # 🔽 여기서 최신순으로 정렬
            for t, typ, detail, lvl in sorted(events_in, key=lambda x: x[0])[-30:]:
                mark = {"CRASH":"💥","ANR":"⛔","GC":"⚙","STEP":"🔖"}.get(typ, "•")
                lines.append(
                    f"{t.strftime('%H:%M:%S')} {mark} {typ} [{lvl}]  {_truncate(detail, 100)}"
                )

            # 줄 수가 많으면 폰트 크기 살짝 낮춤 + 줄간격 넉넉히
            fs = 11
            if len(lines) > 28: fs = 10
            if len(lines) > 36: fs = 9
            render_summary(ax, lines, fontsize=fs, spacing=1.20)

            pdf.savefig()
            plt.close(fig)

    # 자동 열기(Windows 등)
    # try:
    #     if platform.system() == "Windows":
    #         os.startfile(pdf_path)
    #     elif platform.system() == "Darwin":
    #         subprocess.run(["open", pdf_path])
    #     else:
    #         subprocess.run(["xdg-open", pdf_path])
    # except Exception:
    #     pass

    # print(f"[OK] PDF: {pdf_path}")
    # print(f"[OK] CSV: {csv_path}")
    # print(f"[OK] EVENTS_CSV: {ev_csv_path}")
    # print(f"[OK] JSON: {json_path}")


# --- [추가] 인자 파서 + 비대화형 경로 ---
def main():
    ap = argparse.ArgumentParser(description="Resource Report Generator")
    ap.add_argument("-i", "--in", dest="in_path", help="입력 로그(resource_*.txt)")
    ap.add_argument("-o", "--out", dest="out_path", help="출력 파일 경로(prefix). 예: C:\\...\\resource_report_250904_1015.pdf")
    args = ap.parse_args()

    if args.in_path:
        log_path = args.in_path
    else:
        # 기존 Tk 파일 선택창 (무인자 시만)
        root = tk.Tk(); root.withdraw()
        log_path = filedialog.askopenfilename(
            title="리소스 로그 파일을 선택하세요",
            filetypes=[("Text files", "*.txt")]
        )
        if not log_path:
            print("[Err] 로그 파일이 선택되지 않았습니다.")
            return

    # 로그 파싱
    timestamps, cpu_values, mem_pss = parse_resource_log(log_path)
    if not timestamps:
        print("[Err] 파싱된 데이터가 없습니다. 로그 포맷을 확인하세요.")
        return

    # 🔄 동적 임계치 적용(ADB 연결 실패 시 기본값 유지)
    if DYNAMIC_THRESHOLDS:
        try:
            apply_dynamic_thresholds()
        except Exception as e:
            print(f"[WARN] 동적 임계치 설정 실패: {e}")

    if args.out_path:
        output_file = args.out_path  # 확장자는 내부 generate_report가 자동 부여
    else:
        ts_now = datetime.now().strftime("%y%m%d_%H%M")
        output_file = os.path.join(os.path.dirname(log_path), f"resource_report_{ts_now}.pdf")

    generate_report(log_path, timestamps, cpu_values, mem_pss, output_file)

if __name__ == "__main__":
    main()

