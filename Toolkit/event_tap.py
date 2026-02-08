# ==========================================================
# 🛠️ Tool: event_tap (ADB logcat event collector)
# 👤 Author: Eden Kim
# 📅 Date: 2025-10-02 - 다중 기기 지원, 단일 실행 오류 수정
# • 목적: logcat -v epoch -T 1에서 ANR/CRASH/GC/[STEP] 추출 → events.csv 기록(UTF-8-SIG)
#   - STEP 입력: adb shell log -t QA "[STEP] 샘플"
# • 필터: GC는 package/시작PID 포함 + 최소 간격, CRASH는 Process:<pkg> 문맥 보조
# • 시간: device epoch ↔ host offset 보정 → 호스트 시각으로 일관 기록
# • 입력: -p <package> -o <out dir>
# • 산출물: events.csv
# • 주의: stale stop.flag 제거 후 시작, 끊기면 재시도, UTF-8 엄격 디코딩(errors=replace)
# ==========================================================
# -*- coding: utf-8 -*-
import argparse, os, re, csv, json, time, threading, subprocess, sys, io
from datetime import datetime

# ----------------------------
# 설정(필요시 조정)
# ----------------------------
GC_MIN_GAP_SEC = 1          # GC 이벤트 최소 간격(스팸 방지)
STEP_TAG = "STEP"           # [STEP] 마커 태그

EVENT_PATTERNS = [
    ("ANR",   re.compile(r"\bANR in ([\w\.]+)\b")),
    ("CRASH", re.compile(r"FATAL EXCEPTION", re.I)),
    ("GC",    re.compile(r"\bGC_|concurrent copying GC|Concurrent mark sweep", re.I)),
    (STEP_TAG, re.compile(r"\[STEP\]\s*(.+)")),  # Airtest에서 logcat으로 남기는 단계 마커
]

# argparse 위·아래 어느 쪽이든 전역에서 사용 가능하게
SER = os.getenv("ANDROID_SERIAL") or os.getenv("ADB_SERIAL")

# ----------------------------
# 공통 유틸
# ----------------------------
def sh(cmd):
    base = ["adb"]
    if SER:
        base += ["-s", SER]
    # cmd가 ["shell",...]처럼 들어온다고 가정
    return subprocess.check_output(base + cmd, encoding="utf-8", errors="ignore")

def get_device_epoch():
    # 안드로이드 date +%s (정수 초)
    out = sh(["shell","date","+%s"]).strip()
    try:
        return float(out)
    except Exception:
        return time.time()  # 폴백: 호스트 시각

def get_time_offset():
    # host_now - device_epoch = offset
    dev = get_device_epoch()
    host = time.time()
    return host - dev

def to_host_dt_from_epoch(dev_epoch, offset):
    return datetime.fromtimestamp(dev_epoch + offset)

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_pid(package):
    try:
        out = sh(["shell","pidof",package]).strip()
        return int(out) if out else None
    except Exception:
        return None

# ----------------------------
# 수집 스레드: logcat 이벤트  (교체)
# ----------------------------
def collect_logcat_events(out_csv_path, package, stop_evt, time_offset, pid=None):
    """
    logcat -v epoch -T 1 을 '지금부터' 읽어 ANR/CRASH/GC/[STEP]만 필터링해 CSV에 append.
    - epoch pid tid level tag: msg  형식에 맞춰 파싱
    - GC는 package 또는 pid 포함 + 최소 간격 필터
    """

    # 헤더 보장(없거나 0바이트면 생성)
    if (not os.path.exists(out_csv_path)) or os.path.getsize(out_csv_path) == 0:
        with open(out_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["timestamp","type","detail","level"])

    last_gc_ts = 0.0
    prev_lines = []  # crash 문맥 보조
    last_process_pkg = None      # ★ 추가: 최근 'Process:'에서 본 패키지
    last_process_ts  = 0.0       # ★ 추가: 그 시각(초)

    # 끊기면 재시도 루프
    while not stop_evt.is_set():
        try:
            # ✅ ADB 심볼 없이 직접 "adb" 사용
            ser = os.getenv("ANDROID_SERIAL") or os.getenv("ADB_SERIAL")
            prefix = ["-s", ser] if ser else []
            proc = subprocess.Popen(["adb", *prefix, "logcat", "-v", "epoch", "-T", "1"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stream = io.TextIOWrapper(proc.stdout, encoding="utf-8",
                                      errors="replace", newline="")
        except Exception as e:
            sys.stderr.write(f"[event_tap] logcat spawn fail: {e}\n")
            time.sleep(1.0)
            continue

        try:
            for line in stream:
                if stop_evt.is_set():
                    break
                s = line.strip()
                if not s or s.startswith("--------- beginning of "):
                    continue

                # epoch pid tid level tag: msg  ← 실제 epoch 포맷
                m = re.match(
                    r"^\s*(\d+(?:\.\d+)?)\s+\d+\s+\d+\s+([VDIWEAF])\s+([^:]+):\s*(.*)$",
                    s
                )
                if not m:
                    continue
                dev_epoch = float(m.group(1))
                level     = m.group(2)
                tag       = m.group(3).strip()     # ★ 공백 제거(예: "QA      " → "QA")
                msg       = m.group(4).lstrip()    # (선두 공백 방지용, 선택)

                matched = None
                for tname, pat in EVENT_PATTERNS:
                    m2 = pat.search(msg)
                    if not m2:
                        continue

                    if tname == "ANR":
                        # 시스템 라인 'ANR in <pkg>'만 채택
                        if re.search(rf"\bANR in {re.escape(package)}\b", msg):
                            matched = (tname, msg)
                        else:
                            continue
                        break

                    if tname == "CRASH":
                        # ---- 개선된 CRASH 매칭 ----
                        # 1) 'Process: <pkg>' 문맥 추적 (최근 3초 내)
                        if msg.startswith("Process: "):
                            last_process_pkg = msg.split("Process:", 1)[1].strip()
                            last_process_ts = time.time()
                            # Process 라인은 그대로 다음 라인(=FATAL) 보조용이므로 기록은 하지 않음
                            break

                        # 2) FATAL EXCEPTION 이면 패키지 유무와 무관하게 기록,
                        #    패키지는 (최근 Process 패키지 → -p 인자 → 공백) 우선순위로 채움
                        if "FATAL EXCEPTION" in msg:
                            use_pkg = None
                            if last_process_pkg and (time.time() - last_process_ts) <= 3.0:
                                use_pkg = last_process_pkg
                            elif package:
                                use_pkg = package
                            else:
                                use_pkg = ""
                            matched = (tname, use_pkg if use_pkg else msg)
                        break

                    if tname == "GC":
                        # 패키지/시작 PID 포함 라인 + 최소 간격
                        if (package and package in msg) or (pid and re.search(rf"\b{pid}\b", s)):
                            now = time.time()
                            if now - last_gc_ts >= GC_MIN_GAP_SEC:
                                last_gc_ts = now
                                matched = (tname, msg)
                        else:
                            continue
                        break

                    # 2) STEP 분기에서 QA 태그만 인정 + 선두 고정 매칭
                    if tname == STEP_TAG:
                        if tag != "QA":                # ★ adbd 등 시스템 로그 배제
                            continue
                        m_step = re.match(r"^\[STEP\]\s*(.+)$", msg)
                        if not m_step:
                            continue
                        matched = (tname, m_step.group(1).strip())
                        break

                prev_lines.append(msg)
                if len(prev_lines) > 12:
                    prev_lines.pop(0)

                if matched:
                    host_dt = to_host_dt_from_epoch(dev_epoch, time_offset)
                    with open(out_csv_path, "a", newline="", encoding="utf-8-sig") as f:
                        csv.writer(f).writerow([
                            host_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            matched[0],
                            matched[1][:300],
                            level
                        ])
        finally:
            try:
                proc.kill()
            except Exception:
                pass

# ----------------------------
# 메인
# ----------------------------
def main():
    ap = argparse.ArgumentParser(description="ADB logcat event collector (ANR/CRASH/GC/STEP)")
    ap.add_argument("-p","--package", required=True, help="패키지명(ex. com.company.app)")
    ap.add_argument("-o","--out", required=True, help="출력 폴더")
    args = ap.parse_args()

    ensure_dir(args.out)
    events_csv = os.path.join(args.out, "events.csv")
    stop_flag = os.path.join(args.out, "stop.flag")

    # 1) stale stop.flag 제거 (즉시종료 방지)
    if os.path.exists(stop_flag):
        try:
            os.remove(stop_flag)
            print(f"[event_tap] removed stale stop.flag: {stop_flag}", flush=True)
        except Exception as e:
            print(f"[event_tap] cannot remove stop.flag: {e}", file=sys.stderr, flush=True)

    # 시간 오프셋(디바이스→호스트) 계산
    offset = get_time_offset()
    pid = get_pid(args.package)

    stop_evt = threading.Event()
    th_ev = threading.Thread(target=collect_logcat_events,
                             args=(events_csv, args.package, stop_evt, offset, pid),
                             daemon=True)
    th_ev.start()

    print(f"[event_tap] running... pkg={args.package} pid={pid} out={events_csv}", flush=True)
    try:
        while not os.path.exists(stop_flag):
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass

    # 종료 처리
    stop_evt.set()
    th_ev.join(timeout=3.0)
    # --- 종료 정리: stop.flag 자체 삭제 ---
    try:
        # out_dir 변수가 이벤트 탭 출력 폴더를 가리키고 있다고 가정
        sflag = os.path.join(args.out, "stop.flag")
        if os.path.exists(sflag):
            os.remove(sflag)
    except Exception:
        pass

    print("[event_tap] stopped.")

if __name__ == "__main__":
    main()
