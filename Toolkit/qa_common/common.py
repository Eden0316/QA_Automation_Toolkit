# ==========================================================
# QA 자동화 공통 모듈
# 👤 Author: Eden Kim
# 📅 Date: 2026-02-11 - v1.0.6
#   - 진행률 헬퍼 추가: parse_progress()
#   - get_label() 함수 수정: index가 있을 경우 index 포함하여 출력
#   - tap_color_words() 함수에 오류 발생 시 예외처리 진행 추가
#   - 템플릿 매칭 개선 함수 추가: exists_strict_template(), pick_best_template()
#   - Airtest 포터블 리포트 생성 추가: Airtest 없는 PC에서도 단독 실행
#   - 리포트 첨부 파일 지원: Airtest 리포트 zip 압축 후 Google Drive 업로드 및 메일 전송 기능 추가
#   - 템플릿 매칭 함수 수정: 컬러값 배제 후 매칭하는 옵션 추가하여 범용성 개선
#   - Google Drive 관련 설정 QAEnv로 이관
#   - use_env() 인자 없이도 가용하게끔 수정
#   - tap_images() 중복처리 반경 수정
# ==========================================================
#   - Airtest + Poco 기반 안드로이드 앱 자동화 공통 함수
#   - 리소스 모니터링, 메일 발송, 안전 클릭/입력, 스크롤 등
#   - Windows 전용 기능 포함 (파일 잠금 대기 등)
#   - Python 3.6 이상 권장 (f-string 사용)
#   - Airtest 1.2.5 이상, Poco 1.0.86 이상 필요
# ==========================================================
# -*- coding: utf-8 -*-
import os, time, subprocess, pathlib, re, glob, sys, shutil, json, uuid, msvcrt, webbrowser, datetime
import ctypes, smtplib, mimetypes, socket, math, inspect, hashlib, cv2, tempfile
from pathlib import Path
from ctypes import wintypes
from typing import Optional, Tuple, Callable, Dict, List, Union, Any
from poco.drivers.unity3d import UnityPoco
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from poco.exceptions import PocoNoSuchNodeException, PocoTargetTimeout
from email.message import EmailMessage
from airtest.core.api import (G, log, snapshot, start_app, stop_app, text,
                              keyevent, connect_device, set_current, device, device as current_device,
                              swipe, sleep, shell, touch, assert_equal, Template, exists, wait)
from airtest.core.android import android as _air_android
from airtest.core.settings import Settings as ST  # ⬅ 전역 세팅 튜닝용
from airtest.report.report import simple_report
from airtest.aircv import find_all_template, imread
# numpy는 airtest snapshot/aircv 결과에서 이미 사실상 의존 중
import numpy as np
# --- Google Drive (optional) ---
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# 합리적인 기본값(필요 시 조정)
ST.FIND_TIMEOUT = 1.5         # 기본 3s → 1.5s
ST.FIND_TIMEOUT_TMP = 0.5     # 임시 탐색 기본 0.5s
ST.SNAPSHOT_QUALITY = 10      # 기본 80 → 10 (용량/속도 절충)
# ST.IMAGE_MAXSIZE = 1200     # 고해상도 기기에서 다운스케일 원하면 주석 해제
ST.LOG_DIR = None              # Airtest 기본 리포트 스냅샷 폴더 미생성(별도 리포트 사용시)

# 현재 실행 중인 QAEnv (옵션)
_CURRENT_ENV: "QAEnv | None" = None

def set_current_env(env: "QAEnv | None"):
    """TC 진입/런너에서 현재 env를 등록해두고, 공통 함수들이 폴백용으로 사용."""
    global _CURRENT_ENV
    _CURRENT_ENV = env

def get_current_env() -> "QAEnv | None":
    return _CURRENT_ENV

def use_env(env: "QAEnv | None" = None) -> "QAEnv | None":
    """공통 함수에서 env 인자를 안 넘겼을 때 전역 current_env 로 폴백."""
    return env if env is not None else _CURRENT_ENV

# 환경 설정 및 공통 함수
class QAEnv:
    def __init__(self, package: str, script_dir: str, out_dir_root: str,
                 serial: Optional[str] = None, per_device_dir: bool = True,
                 restart_delay: float = 1.0,
                 ui_mode: str = "native", # ⬅️ 추가: unity | native
                 app_start=None,
                 # 🔹 신규 필드(앱별 기본 콜백)
                 on_ready: Optional[Callable[[], None]] = None,
                 on_close: Optional[Callable[[], None]] = None,
                 airtest_script=None,
                 suite: str = "tc_suite",
                 runner: str = "local",
                 use_run: bool = True,
                 mail_max_attach: int = 20,
                 gdrive_enable: bool = False,
                 gdrive_folder_id: str = None,
                 gdrive_share_anyone: bool = False,
                 ):
        self.package = package
        self.script_dir = os.path.abspath(script_dir)
        self.serial = serial or resolve_serial()

        # per-device root (기존 out_dir 의미를 보존)
        device_root = (os.path.join(os.path.abspath(out_dir_root), self.serial or "default")
                    if per_device_dir else os.path.abspath(out_dir_root))
        self.device_out_dir = os.path.abspath(device_root)
        pathlib.Path(self.device_out_dir).mkdir(parents=True, exist_ok=True)

        # Poco 비활성화 타이머
        self._poco_disabled_until = 0.0

        # Run 표준 정보
        self.run_suite = suite
        self.run_runner = runner

        self.run_started_ts = time.time()
        self.run_started_at = _kst_now_iso()
        self.run_ended_at = ""
        self.run_duration_sec = 0
        self.run_counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "SKIP": 0}
        self.run_notes: List[str] = []
        self.run_artifacts: Dict[str, str] = {}
        self.run_fail_logs: List[Dict[str, str]] = []
        self.run_warn_logs: List[Dict[str, str]] = []

        self.mail_max_attach = mail_max_attach

        self.gdrive_enable = gdrive_enable
        self.gdrive_folder_id = gdrive_folder_id
        self.gdrive_share_anyone = gdrive_share_anyone

        # ✅ 실패 누적 카운터(메인/서브 공통)
        self.total_fail: int = 0

        # ✅ 실패 로그(메인/서브 공통)
        # 예: {"kind":"flow"|"subflow", "iter":1, "flow":"Basic", "name":"서브단계", "error":"..."}
        self.fail_logs: List[Dict[str, object]] = []

        # ✅ 실행 컨텍스트(서브플로우가 iter/부모 flow를 알 수 있도록)
        self._ctx_iter: Optional[int] = None
        self._ctx_flow: Optional[str] = None


        # Run 디렉토리 구성
        self.run_id = _make_run_id(self.package, self.run_suite, self.run_runner)

        # out_dir을 Run 디렉토리로 승격(= 기존 코드 호환 핵심)
        if use_run:
            self.run_dir = os.path.join(self.device_out_dir, self.run_id)
        else:
            self.run_dir = self.device_out_dir

        _safe_mkdir(self.run_dir)

        self.run_meta_path = os.path.join(self.run_dir, "meta.json")
        self.run_summary_path = os.path.join(self.run_dir, "summary.html")
        self.run_log_path = os.path.join(self.run_dir, "run.log")

        # 기존 코드가 기대하는 out_dir은 run_dir로 설정
        self.out_dir = self.run_dir

        # 디바이스/앱 정보 수집(실패해도 무시)
        try:
            _collect_device_app_info(self)
        except Exception:
            pass


        # 드라이버 핸들
        self.apoco = None        # AndroidUiautomationPoco (Native)
        self.upoco = None        # UnityPoco (Unity)
        self.poco = None         # ⬅️ 항상 "현재 모드"의 드라이버를 가리키도록 유지
        self.poco_active = None  # ⬅️ 동의어

        self.ui_mode = ui_mode.lower().strip()  # 'unity' or 'native'
        self.restart_delay = restart_delay
        self._rm_proc = None

        # 🔹 앱별 스타트 콜백 (예: literacy_start)
        self.app_start = app_start    # type: Optional[Callable[[], None]]

        # 🔹 신규: 앱별 기본 콜백
        self.on_ready = on_ready               # 앱 준비 완료 콜백
        self.on_close = on_close               # 앱 종료 전 처리 콜백

        self.handle_exceptions: Optional[Callable[[Exception, 'QAEnv'], int]] = None  # 예외 처리기

        # 🔹 Airtest 리포트 관련 정보(옵션)
        self.airtest_script  = airtest_script   # __file__ of TC script
        self.airtest_log_dir = os.path.join(self.out_dir, "airtest_log")   # airtest_log 디렉터리
        pathlib.Path(self.airtest_log_dir).mkdir(parents=True, exist_ok=True)

    def set_ui_mode(self, mode: str):
        self.ui_mode = (mode or "").lower().strip()
        # 드라이버가 이미 만들어져 있다면 포인터만 교체
        if self.ui_mode == "native" and self.apoco:
            self.poco_active = self.apoco
        elif self.ui_mode == "unity" and self.upoco:
            self.poco_active = self.upoco
        else:
            self.poco_active = None
        self.poco = self.poco_active  # 동기화


# 연결된 장치가 하나일 때 그 시리얼 반환, 없거나 둘 이상이면 None
def resolve_serial() -> Optional[str]:
    s = os.environ.get("ANDROID_SERIAL") or os.environ.get("ADB_SERIAL")
    if s: return s
    try:
        out = subprocess.check_output(["adb","devices"], encoding="utf-8", errors="ignore")
        ser = [ln.split()[0] for ln in out.splitlines() if ln.strip().endswith("device") and "List" not in ln]
        return ser[0] if len(ser)==1 else None
    except Exception:
        return None

# ADB 환경 변수 설정
def adb_env(env: QAEnv):
    e = dict(os.environ)
    if env.serial: 
        e["ADB_SERIAL"] = env.serial
        e["ANDROID_SERIAL"] = env.serial   # ← 추가
    e["RESULT_DIR"] = env.out_dir
    return e

# 문자열을 쉘 로그용으로 변환 (특수문자 제거/치환)
def _sanitize_for_shell_log(msg: str) -> str:
    s = str(msg)
    # 줄바꿈/탭 -> 공백
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 따옴표 정리
    s = s.replace('"', "'")
    # 쉘에서 의미를 갖는 심볼 최소화
    # (){}[] ; | & < > $ ` \  등을 제거 또는 공백 치환
    s = re.sub(r"[(){}<>$`\\]", "", s)
    s = s.replace("->", " to ")
    s = s.replace("|", " | ")
    s = s.replace("&", " and ")
    s = s.replace(";", " ; ")
    # 쉼표는 토큰 구분이 명확하도록 앞에 공백
    s = s.replace(",", " ,")
    # 공백 정리(여러 개 → 하나)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ==========================================================
# ✅ Run Standard v1.0 (Suite: literacy)
#  - Run dir: Tools\result\<serial>\<run_id>\
#  - 최소 산출물: meta.json / summary.html / run.log
#  - 상태: PASS / FAIL / WARN / N/A / SKIP
# ==========================================================
def build_portable_airtest_report(script_path: str, log_dir: str, out_dir: str, ts: str):
    """
    Portable Airtest report bundle:
    - out_dir/airtest_portable_<ts>/index.html
    - out_dir/airtest_portable_<ts>/_airtest_report/...   (Airtest report static assets)
    - out_dir/airtest_portable_<ts>/airtest_log/...       (log.txt + screenshots etc)
    스크립트(.air) 폴더는 절대 복사하지 않음.
    """
    script_path = str(script_path)
    log_dir = str(log_dir)
    out_dir = str(out_dir)

    portable_dir = os.path.join(out_dir, f"airtest_portable_{ts}")
    os.makedirs(portable_dir, exist_ok=True)

    # 1) 임시 폴더에 report 생성 (드라이브 mismatch 방지)
    base_tmp_dir = out_dir
    d_out = os.path.splitdrive(os.path.abspath(out_dir))[0].upper()
    d_log = os.path.splitdrive(os.path.abspath(log_dir))[0].upper()
    if d_log and d_out and (d_log != d_out):
        base_tmp_dir = log_dir

    tmp = tempfile.mkdtemp(prefix="airtest_rep_", dir=base_tmp_dir)
    try:
        tmp_html = os.path.join(tmp, "index.html")
        simple_report(script_path, logpath=log_dir, output=tmp_html)

        # 2) Airtest 정적 리소스(site-packages/airtest/report) 통째로 복사
        try:
            import airtest  # type: ignore
            airtest_pkg_dir = os.path.dirname(airtest.__file__)
            report_src_dir = os.path.join(airtest_pkg_dir, "report")  # .../airtest/report
            report_dst_dir = os.path.join(portable_dir, "_airtest_report")

            if os.path.isdir(report_src_dir):
                shutil.copytree(report_src_dir, report_dst_dir, dirs_exist_ok=True)
            else:
                step(f"⚠️ [WARN] airtest report 폴더를 찾지 못했습니다: {report_src_dir}")
        except Exception as e:
            step(f"⚠️ [WARN] airtest report 리소스 복사 실패: {e}")

        # 3) index.html 내부 경로를 포터블 상대경로로 치환 후 저장
        try:
            with open(tmp_html, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()

            # ------------------------------------------------------------
            # (A) Airtest report 정적리소스 경로 치환
            #   C:\...\site-packages\airtest\report\  -> ./_airtest_report/
            #   C:/.../site-packages/airtest/report/  -> ./_airtest_report/
            #   (drive 포함 절대경로를 통째로 제거)
            # ------------------------------------------------------------
            html = re.sub(
                r'[A-Za-z]:(?:\\|/)[^"\']*?airtest(?:\\|/)report(?:\\|/)',
                r'./_airtest_report/',
                html
            )

            # ------------------------------------------------------------
            # (B) 로그/스크린샷 경로 치환 (log_dir 절대경로 -> ./airtest_log/<tail>)
            #   - file:///D:/.../airtest_log/xxx.png
            #   - D:/.../airtest_log/xxx.png
            #   - D:\...\airtest_log\xxx.png
            #   - JSON escaped: D:\\...\airtest_log\\xxx.png
            #   - airtest_log/\177.... 같은 "/\" 혼합 구분자까지 정규화
            # ------------------------------------------------------------
            log_abs = os.path.abspath(log_dir)

            log_abs_slash = log_abs.replace("\\", "/").rstrip("/")
            log_abs_back  = log_abs.replace("/", "\\").rstrip("\\")
            log_abs_url   = log_abs_slash.replace(" ", "%20")
            log_abs_back_escaped = log_abs_back.replace("\\", "\\\\")  # D:\\a\\b 형태

            def _repl_tail(m):
                tail = (m.group("tail") or "").lstrip("/\\")
                tail = tail.replace("\\", "/")  # tail 내부 역슬래시 정규화
                return f"./airtest_log/{tail}"

            # 1) file:///...
            pat_file = re.compile(
                r"(?:file:///)" + re.escape(log_abs_url) + r"[\\/](?P<tail>[^\"'>\s]+)",
                re.IGNORECASE
            )
            html = pat_file.sub(_repl_tail, html)

            # 2) D:/...
            pat_slash = re.compile(
                re.escape(log_abs_slash) + r"[\\/](?P<tail>[^\"'>\s]+)",
                re.IGNORECASE
            )
            html = pat_slash.sub(_repl_tail, html)

            # 3) D:\...
            pat_back = re.compile(
                re.escape(log_abs_back) + r"[\\/](?P<tail>[^\"'>\s]+)",
                re.IGNORECASE
            )
            html = pat_back.sub(_repl_tail, html)

            # 4) D:\\... (JSON escaped)
            pat_back_esc = re.compile(
                re.escape(log_abs_back_escaped) + r"(?:\\\\|/)(?P<tail>[^\"'>\s]+)",
                re.IGNORECASE
            )
            html = pat_back_esc.sub(_repl_tail, html)

            # ------------------------------------------------------------
            # (C) 남아있는 상대경로/혼합 구분자 정리
            #   - ..\airtest_log\  -> ./airtest_log/
            #   - airtest_log/\177... -> airtest_log/177...
            # ------------------------------------------------------------
            html = html.replace("..\\airtest_log\\", "./airtest_log/")
            html = html.replace("..\\airtest_log/", "./airtest_log/")
            html = html.replace("../airtest_log/", "./airtest_log/")

            # "/\" 또는 "\/" 혼합 제거 (핵심)
            html = re.sub(r"\./airtest_log[\\/]+", "./airtest_log/", html)
            html = html.replace("./airtest_log/\\", "./airtest_log/")
            html = html.replace("./airtest_log\\", "./airtest_log/")
            html = html.replace("airtest_log/\\", "airtest_log/")
            html = html.replace("airtest_log\\", "airtest_log/")

            out_index = os.path.join(portable_dir, "index.html")
            with open(out_index, "w", encoding="utf-8", errors="ignore") as f:
                f.write(html)

        except Exception as e:
            shutil.copy2(tmp_html, os.path.join(portable_dir, "index.html"))
            step(f"⚠️ [WARN] index.html 경로 치환 실패(원본 복사로 대체): {e}")

        # 4) log_dir 산출물 복사 (스크립트 폴더는 제외)
        log_bundle = os.path.join(portable_dir, "airtest_log")
        os.makedirs(log_bundle, exist_ok=True)

        allow_ext = {".txt", ".log", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".json", ".csv", ".xml", ".html"}
        for root, dirs, files in os.walk(log_dir):
            dirs[:] = [d for d in dirs if not d.lower().endswith(".air")]

            rel = os.path.relpath(root, log_dir)
            dst_root = os.path.join(log_bundle, rel) if rel != "." else log_bundle
            os.makedirs(dst_root, exist_ok=True)

            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in allow_ext:
                    shutil.copy2(os.path.join(root, fn), os.path.join(dst_root, fn))

        return portable_dir, os.path.join(portable_dir, "index.html")

    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

def _kst_now_iso() -> str:
    dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    return dt.isoformat(timespec="seconds")

def _run_id_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def _guess_tools_dir_from_script_dir(script_dir: str) -> str:
    """
    운영 기준:
      - QA_SCRIPT가 Tools 루트로 쓰이지만, common에서는 script_dir 기반으로 역추정도 허용
      - script_dir가 Tools 하위(예: Tools\qa_common)라면 한 단계 위가 Tools일 확률이 높음
    """
    # 1) QA_SCRIPT 환경변수 우선
    qs = os.environ.get("QA_SCRIPT")
    if qs:
        return os.path.abspath(qs)

    # 2) script_dir 기준 폴백
    sd = os.path.abspath(script_dir or "")
    parent = os.path.abspath(os.path.join(sd, os.pardir))
    return parent

def _result_root_dir(script_dir: str) -> str:
    # 표준: Tools\result
    tools_dir = _guess_tools_dir_from_script_dir(script_dir)
    return os.path.join(tools_dir, "result")

def _make_run_id(package: str, suite: str, runner: str) -> str:
    ts = _run_id_timestamp()
    pkg = (package or "unknown").strip()
    st = (suite or "literacy").strip()
    rn = (runner or "local").strip()
    return f"{ts}_{pkg}_{st}_{rn}"

def _safe_mkdir(path: str) -> str:
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    return path

def _write_json(path: str, obj: Dict[str, Any]):
    _safe_mkdir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _append_line(path: str, line: str):
    _safe_mkdir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# 파일 상단(또는 함수 위)에서 컴파일 권장
# '단어 경계'를 공백만으로 제한하지 않고, 구두점/이모지/콜론 등도 경계로 인정
# 다만 변수명/객체명에 흔한 '_'는 "단어 내부"로 취급하여 btn_skip 같은 건 매치되지 않게 함.
_TOKEN_PATTERNS = {
    "FAIL": re.compile(r'(^|[^A-Z0-9_])FAIL([^A-Z0-9_]|$)'),
    "PASS": re.compile(r'(^|[^A-Z0-9_])PASS([^A-Z0-9_]|$)'),
    "WARN": re.compile(r'(^|[^A-Z0-9_])WARN([^A-Z0-9_]|$)'),
    "SKIP": re.compile(r'(^|[^A-Z0-9_])SKIP([^A-Z0-9_]|$)'),
    # N/A는 특수문자 포함이라 별도 처리
    "NA_SLASH": re.compile(r'(^|[^A-Z0-9_])N\s*/\s*A([^A-Z0-9_]|$)'),
    # "NA" 단독을 쓰는 경우까지 지원하고 싶으면 활성화(오염 위험은 낮지만 제로는 아님)
    # "NA": re.compile(r'(^|[^A-Z0-9_])NA([^A-Z0-9_]|$)'),
}

def _normalize_status_from_msg(msg: str) -> Optional[str]:
    u = (msg or "").upper()

    # 우선순위: FAIL이 PASS보다 앞 (예: "FAIL PASS" 같은 혼재 시 FAIL 우선)
    if _TOKEN_PATTERNS["FAIL"].search(u):
        return "FAIL"
    if _TOKEN_PATTERNS["PASS"].search(u):
        return "PASS"
    if _TOKEN_PATTERNS["WARN"].search(u):
        return "WARN"
    if _TOKEN_PATTERNS["SKIP"].search(u):
        return "SKIP"

    if _TOKEN_PATTERNS["NA_SLASH"].search(u):
        return "N/A"

    # 필요 시: "N A" 형태도 허용하고 싶으면 아래 추가 (현재는 보수적으로 비활성)
    # if re.search(r'(^|[^A-Z0-9_])N\s+A([^A-Z0-9_]|$)', u):
    #     return "N/A"
    return None

def _pick_overall_result(counts: Dict[str, int]) -> str:
    """
    전체 결과 산정 룰(v1.0):
      - FAIL > WARN > PASS > N/A > SKIP
      - 단, PASS/FAIL/WARN이 모두 0이고 N/A만 있으면 N/A
      - 아무 것도 없으면 SKIP
    """
    fail = int(counts.get("FAIL", 0))
    warn = int(counts.get("WARN", 0))
    pas  = int(counts.get("PASS", 0))
    na   = int(counts.get("N/A", 0))
    sk   = int(counts.get("SKIP", 0))

    if fail > 0:
        return "FAIL"
    if warn > 0:
        return "WARN"
    if pas > 0:
        return "PASS"
    if na > 0 and (pas == 0 and fail == 0 and warn == 0):
        return "N/A"
    return "SKIP"

def _overall_decision(counts: Dict[str, int], *, forced: Optional[str] = None) -> Dict[str, Any]:
    """
    전체 결과 + 결정 근거를 함께 산출.
    - forced 가 있으면(상위에서 result를 강제로 지정) overall은 forced를 따르되,
      reason_code로 'FORCED_RESULT'를 남긴다.
    """
    # 정규화
    c_fail = int((counts or {}).get("FAIL", 0))
    c_warn = int((counts or {}).get("WARN", 0))
    c_pass = int((counts or {}).get("PASS", 0))
    c_na   = int((counts or {}).get("N/A", 0))
    c_skip = int((counts or {}).get("SKIP", 0))

    precedence = ["FAIL", "WARN", "PASS", "N/A", "SKIP"]

    # 강제 결과가 있으면 그걸 사용
    if forced:
        ov = str(forced).upper().strip()
        return {
            "rule_version": "1.0",
            "overall": ov,
            "reason_code": "FORCED_RESULT",
            "reason_text": f"Overall result is forced to {ov} by caller (finalize_run result parameter).",
            "precedence": precedence,
            "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
        }

    # 룰(v1.0): FAIL > WARN > PASS > N/A(단독) > SKIP
    if c_fail > 0:
        return {
            "rule_version": "1.0",
            "overall": "FAIL",
            "reason_code": "FAIL_COUNT_GT_0",
            "reason_text": f"FAIL count is {c_fail} (>0), so overall result is FAIL by precedence.",
            "precedence": precedence,
            "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
        }

    if c_warn > 0:
        return {
            "rule_version": "1.0",
            "overall": "WARN",
            "reason_code": "WARN_COUNT_GT_0",
            "reason_text": f"WARN count is {c_warn} (>0) and FAIL is 0, so overall result is WARN by precedence.",
            "precedence": precedence,
            "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
        }

    if c_pass > 0:
        return {
            "rule_version": "1.0",
            "overall": "PASS",
            "reason_code": "PASS_COUNT_GT_0",
            "reason_text": f"PASS count is {c_pass} (>0) and FAIL/WARN are 0, so overall result is PASS by precedence.",
            "precedence": precedence,
            "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
        }

    if c_na > 0 and (c_pass == 0 and c_fail == 0 and c_warn == 0):
        return {
            "rule_version": "1.0",
            "overall": "N/A",
            "reason_code": "NA_ONLY",
            "reason_text": f"N/A count is {c_na} and PASS/FAIL/WARN are 0, so overall result is N/A.",
            "precedence": precedence,
            "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
        }

    return {
        "rule_version": "1.0",
        "overall": "SKIP",
        "reason_code": "EMPTY_OR_SKIP",
        "reason_text": "No PASS/FAIL/WARN (and no N/A-only case). Overall is SKIP.",
        "precedence": precedence,
        "counts": {"FAIL": c_fail, "WARN": c_warn, "PASS": c_pass, "N/A": c_na, "SKIP": c_skip},
    }

def _summary_html_text(env: "QAEnv") -> str:
    def esc(s: str) -> str:
        s = "" if s is None else str(s)
        return (s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    c = getattr(env, "run_counts", {}) or {}
    # ----- Status UI (emoji + color) -----
    def status_emoji(st: str) -> str:
        s = (st or "").upper()
        return {
            "PASS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️",
            "N/A":  "➖",
            "SKIP": "⏭️",
        }.get(s, "📌")

    run_result = (getattr(env, "run_result", "") or "").upper()
    result_emoji = status_emoji(run_result)

    def cnt_class(label: str) -> str:
        s = (label or "").upper()
        return {
            "PASS": "cnt pass",
            "FAIL": "cnt fail",
            "WARN": "cnt warn",
            "N/A":  "cnt na",
            "SKIP": "cnt skip",
        }.get(s, "cnt")

    def result_badge_class(st: str) -> str:
        s = (st or "").upper()
        return {
            "PASS": "badge ok",
            "FAIL": "badge bad",
            "WARN": "badge warn",
            "N/A":  "badge na",
            "SKIP": "badge skip",
        }.get(s, "badge")

    pass_cnt = int(c.get("PASS", 0))
    # run_counts는 "FAIL 로그 수"에 가깝고,
    # total_fail은 "실패 플로우 건수"라 요약에서는 total_fail을 우선 사용
    total_fail = int(getattr(env, "total_fail", 0) or 0)
    fail_cnt = total_fail if total_fail > 0 else int(c.get("FAIL", 0))
    warn_cnt = int(c.get("WARN", 0))
    na_cnt   = int(c.get("N/A", 0))
    skip_cnt = int(c.get("SKIP", 0))

    started = getattr(env, "run_started_at", "") or ""
    ended   = getattr(env, "run_ended_at", "") or ""
    dur     = int(getattr(env, "run_duration_sec", 0) or 0)

    model = getattr(env, "device_model", "") or ""
    osv   = getattr(env, "device_os_version", "") or ""
    sdk   = getattr(env, "device_sdk", "") or ""
    vname = getattr(env, "app_version_name", "") or ""
    vcode = getattr(env, "app_version_code", "") or ""
    # ----- Warnings / Failures / Notes 섹션 -----
    warns = getattr(env, "run_warn_logs", []) or []
    failures = getattr(env, "run_fail_logs", []) or []
    notes = getattr(env, "run_notes", []) or []

    # Warnings
    if warns:
        warn_rows = []
        for w in warns:
            wt = esc(w.get("time", ""))
            wm = esc(w.get("msg", ""))
            warn_rows.append(f"<tr><td>{wt}</td><td><code>{wm}</code></td></tr>")
        warnings_html = (
            "<table>"
            "<tr><th>Time</th><th>Message</th></tr>"
            + "".join(warn_rows) +
            "</table>"
        )
    else:
        warnings_html = "<div class='muted'>(경고 없음)</div>"

    # Failures
    if failures:
        fail_rows = []
        for f in failures:
            it = esc(f.get("iter", ""))
            nm = esc(f.get("name", ""))
            er = esc(f.get("error", ""))
            fail_rows.append(f"<tr><td>{it}</td><td>{nm}</td><td><code>{er}</code></td></tr>")
        failures_html = (
            "<table>"
            "<tr><th>Iter</th><th>Flow</th><th>Error</th></tr>"
            + "".join(fail_rows) +
            "</table>"
        )
    else:
        failures_html = "<div class='muted'>(실패 없음)</div>"

    # Notes
    if notes:
        notes_html = "<ul>" + "".join([f"<li>{esc(x)}</li>" for x in notes]) + "</ul>"
    else:
        notes_html = "<div class='muted'>(노트 없음)</div>"


    # 항상 존재하는 기본 링크(상대경로)
    links = [
        ("meta.json", "meta.json"),
        ("run.log", "run.log"),
        ("summary.html", "summary.html"),
    ]

    # 옵션 산출물(상대경로) — env.run_artifacts 에 들어있는 값은 "상대경로"를 전제로 한다.
    arts = getattr(env, "run_artifacts", {}) or {}
    for k, relp in arts.items():
        if not relp:
            continue
        relp = str(relp).replace("\\", "/")
        # 기본 링크와 중복이면 건너뜀
        if relp in ("meta.json", "run.log", "summary.html"):
            continue
        links.append((str(k), relp))

    # 표 렌더
    rows = []
    for title, href in links:
        rows.append(
            "<tr>"
            f"<td>{esc(title)}</td>"
            f"<td><a href='{esc(href)}'>{esc(href)}</a></td>"
            "</tr>"
        )
    rows_html = "\n".join(rows)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QA Run Summary</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; }}
  h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
  h2 {{ margin-top: 18px; font-size: 16px; }}
  .small {{ color:#666; font-size: 12px; margin-top: 2px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
  td, th {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; }}
  th {{ background: #f6f6f6; text-align:left; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }}
  .card {{ border: 1px solid #e5e5e5; border-radius: 10px; padding: 12px; }}
  .muted {{ color:#888; font-size: 13px; }}
  code {{ white-space: pre-wrap; }}
  /* --- Status palette --- */
  .title {{ display:flex; align-items:center; gap:10px; }}
  .title .mark {{ font-size: 22px; }}
  .badge {{ display:inline-block; padding:4px 10px; border-radius: 999px; background:#eee; font-weight: 600; }}
  .badge.ok   {{ background:#e8f5e9; color:#1b5e20; }}
  .badge.bad  {{ background:#ffebee; color:#b71c1c; }}
  .badge.warn {{ background:#fff8e1; color:#e65100; }}
  .badge.na   {{ background:#eef2f7; color:#37474f; }}
  .badge.skip {{ background:#f3e5f5; color:#4a148c; }}

  .cnt {{ font-weight: 700; }}
  .cnt.pass {{ color:#1b5e20; }}
  .cnt.fail {{ color:#b71c1c; }}
  .cnt.warn {{ color:#e65100; }}
  .cnt.na   {{ color:#37474f; }}
  .cnt.skip {{ color:#4a148c; }}

  .pill {{ display:inline-block; padding:2px 8px; border-radius: 999px; border:1px solid #ddd; font-size:12px; color:#555; background:#fafafa; }}
  .prebox {{ background:#0b0f14; color:#e6edf3; padding:12px; border-radius:10px; overflow:auto; font-size:12px; line-height:1.5; }}
</style>
</head>
<body>
  <div class="title">
    <div class="mark">🧾</div>
    <h1>QA Run Summary</h1>
    <span class="pill">{esc(getattr(env,'run_suite',''))}</span>
    <span class="pill">{esc(getattr(env,'run_runner',''))}</span>
  </div>

  <div class="small">Run ID: <b>{esc(getattr(env,'run_id',''))}</b></div>
  <div class="small">Result: <span class="{result_badge_class(run_result)}">{result_emoji} {esc(run_result)}</span></div>

  <div class="grid">
    <div class="card">
      <h2>📋 환경 정보</h2>
      <div class="small">Device: {esc(model)} / {esc(getattr(env,'serial',''))}</div>
      <div class="small">Android: {esc(osv)} (SDK {esc(sdk)})</div>
      <div class="small">App: {esc(getattr(env,'package',''))} {esc(vname)} ({esc(vcode)})</div>
    </div>
    <div class="card">
      <h2>⏱️ 시간</h2>
      <div class="small">Started: {esc(started)}</div>
      <div class="small">Ended: {esc(ended)}</div>
      <div class="small">Duration: {esc(dur)}s</div>
    </div>
  </div>

  <h2>📊 집계</h2>
  <table>
    <tr>
      <th>✅ PASS</th><th>❌ FAIL</th><th>⚠️ WARN</th><th>➖ N/A</th><th>⏭️ SKIP</th>
    </tr>
    <tr>
      <td class="{cnt_class('PASS')}">{pass_cnt}</td>
      <td class="{cnt_class('FAIL')}">{fail_cnt}</td>
      <td class="{cnt_class('WARN')}">{warn_cnt}</td>
      <td class="{cnt_class('N/A')}">{na_cnt}</td>
      <td class="{cnt_class('SKIP')}">{skip_cnt}</td>
    </tr>
  </table>

  <h2>⚠️ Warnings</h2>
  {warnings_html}

  <h2>❌ Failures</h2>
  {failures_html}

  <h2>📝 Notes</h2>
  {notes_html}

  <h2>🗂️ Artifacts</h2>
  <table>
    <tr><th>Item</th><th>Link</th></tr>
    {rows_html}
  </table>
</body>
</html>"""

def _collect_device_app_info(env: "QAEnv"):
    """
    meta/summary에 넣기 위한 최소 정보 수집.
    실패해도 테스트 흐름은 깨지지 않도록 예외 삼킴.
    """
    try:
        # device
        env.device_model = (_adb_exec(env, "shell", "getprop", "ro.product.model") or "").strip()
        env.device_os_version = (_adb_exec(env, "shell", "getprop", "ro.build.version.release") or "").strip()
        env.device_sdk = (_adb_exec(env, "shell", "getprop", "ro.build.version.sdk") or "").strip()
    except Exception:
        pass

    try:
        # app version (dumpsys package)
        out = _adb_exec(env, "shell", "dumpsys", "package", env.package) or ""
        m1 = re.search(r"\bversionName=([^\s]+)", out)
        m2 = re.search(r"\bversionCode=(\d+)", out)
        env.app_version_name = m1.group(1) if m1 else ""
        env.app_version_code = m2.group(1) if m2 else ""
    except Exception:
        pass

def finalize_run(env: Optional["QAEnv"] = None, result: Optional[str] = None):
    """
    Run 종료 처리:
      - ended_at/duration/result 확정
      - meta.json + summary.html 생성
    """
    env = use_env(env)
    if env is None:
        return

    # 종료 정보
    env.run_ended_at = _kst_now_iso()
    try:
        # started_at이 없다면 보호
        t0 = float(getattr(env, "run_started_ts", 0.0) or 0.0)
        env.run_duration_sec = int(max(0.0, time.time() - t0))
    except Exception:
        env.run_duration_sec = 0

    counts = getattr(env, "run_counts", None) or {}

    # ✅ overall + decision(근거) 산출
    dec = _overall_decision(counts, forced=result)
    env.run_result = str(dec.get("overall", "SKIP")).upper()

    # meta.json 구성
    meta = {
        "schema_version": "1.0",
        "run_id": env.run_id,
        "suite": env.run_suite,
        "runner": env.run_runner,
        "started_at": env.run_started_at,
        "ended_at": env.run_ended_at,
        "duration_sec": env.run_duration_sec,
        "result": env.run_result,
        # ✅ 추가: 결과 결정 근거
        "decision": {
            "rule_version": dec.get("rule_version", "1.0"),
            "overall": env.run_result,
            "reason_code": dec.get("reason_code", ""),
            "reason_text": dec.get("reason_text", ""),
            "precedence": dec.get("precedence", ["FAIL", "WARN", "PASS", "N/A", "SKIP"]),
            # counts는 meta 상단에도 이미 있지만, decision 파싱만으로 근거를 완결시키기 위해 중복 저장
            "counts": dec.get("counts", {}),
        },
        "device": {
            "serial": env.serial,
            "model": getattr(env, "device_model", "") or "",
            "os_version": getattr(env, "device_os_version", "") or "",
            "sdk": getattr(env, "device_sdk", "") or "",
        },
        "app": {
            "package": env.package,
            "version_name": getattr(env, "app_version_name", "") or "",
            "version_code": getattr(env, "app_version_code", "") or "",
        },
        "counts": {
            "pass": int(counts.get("PASS", 0)),
            "fail": int(counts.get("FAIL", 0)),
            "warn": int(counts.get("WARN", 0)),
            "na": int(counts.get("N/A", 0)),
            "skip": int(counts.get("SKIP", 0)),
        },
        "artifacts": getattr(env, "run_artifacts", {}) or {},
        "notes": getattr(env, "run_notes", []) or [],
        "warnings": getattr(env, "run_warn_logs", []) or [],
        "failures": getattr(env, "run_fail_logs", []) or [],
    }

    try:
        _write_json(env.run_meta_path, meta)
    except Exception:
        pass

    try:
        html = _summary_html_text(env)
        with open(env.run_summary_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass

# ========================================================
# 스크립트 활용 로그 기록 유틸
#   - 기본 단계 로그 기록: step() - run_log, adb, 스냅샷(옵션), FAIL 문구 assertion(Airtest Fail로그) 기록
#   - 실패 단계 로그 기록: soft_fail() - run_log, adb, assertion 기본 기록(스냅샷 디폴트), 추가 스냅샷(옵션)
# ========================================================
# 단계 표시 및 스냅샷/로그캣 기록 (adb용만 sanitize)
def step(msg: str, shot: bool=False, env: Optional[QAEnv]=None):
    # 사람이 보는 콘솔/리포트 로그는 원문 유지
    env = use_env(env)
    try:
        log(f"🔖 {msg}")
    except Exception:
        pass

    if shot:
        try:
            snapshot(msg=f"🔖 {msg}")
        except Exception:
            pass
    
    # ✅ Run 표준 로그 기록 + 카운트 누적 (기존 동작에 영향 없음)
    try:
        if env is not None and getattr(env, "run_log_path", None):
            ts = time.strftime("%H:%M:%S")
            _append_line(env.run_log_path, f"[{ts}] {msg}")
            st = _normalize_status_from_msg(msg)
            if st:
                env.run_counts[st] = int(env.run_counts.get(st, 0)) + 1

                # ✅ WARN 상세 누적 (summary/meta 출력용)
                if st == "WARN":
                    try:
                        if not hasattr(env, "run_warn_logs") or env.run_warn_logs is None:
                            env.run_warn_logs = []
                        env.run_warn_logs.append({
                            "time": ts,
                            "msg": str(msg),
                        })
                    except Exception:
                        pass
                
                # ✅ FAIL 상세 누적 (summary/meta 출력용), total_fail도 증가 (record_fail 제거 후에도 최종 실패 건수 유지)
                if st == "FAIL":
                    try:
                        assert_equal(True, False, msg)
                    except AssertionError:
                        pass
                    except Exception:
                        pass
                    try:
                        # total_fail도 동기화
                        if not hasattr(env, "total_fail") or env.total_fail is None:
                            env.total_fail = 0
                        env.total_fail = int(env.total_fail) + 1
                        
                        # Failures 상세 누적
                        if not hasattr(env, "run_fail_logs") or env.run_fail_logs is None:
                            env.run_fail_logs = []

                        # iter가 있으면 iter, 없으면 시간으로 대체(= run_flows 이전 FAIL도 표시 가능)
                        iter_val = getattr(env, "_ctx_iter", None)
                        iter_show = str(iter_val) if iter_val is not None else ts

                        env.run_fail_logs.append({
                            "iter": iter_show,
                            "name": str(getattr(env, "_ctx_flow", "") or "STEP"),
                            "error": str(msg),
                            # 확장 필드(템플릿이 무시해도 무방)
                            "kind": "step",
                            "flow": str(getattr(env, "_ctx_flow", "") or ""),
                            "time": ts,
                        })
                    except Exception:
                        pass

    except Exception:
        pass

    # adb shell 로 전달하는 메시지에서만 특수문자 정규화
    try:
        safe = _sanitize_for_shell_log(msg)
        adb_env_map = adb_env(env) if env else None
        subprocess.call(
            ["adb", "shell", "log", "-t", "QA", f"[STEP] {safe}"],
            env=adb_env_map
        )
    except Exception:
        # 로깅 실패가 테스트를 깨뜨리지 않도록 무시
        pass

# 실패 assertion 기록 및 플로우 계속 진행 유틸
def soft_fail(msg: str, *, shot: bool = False, env: Optional[QAEnv] = None) -> bool:
    """
    Airtest 리포트에 '실패 assertion'을 남기기만 하는 용도.
    호출 후에는 기존 흐름대로 raise를 던지면 run_flows가 캐치하여 계속 진행 가능.
    """
    env = use_env(env)
    # 핵심: 실패 assertion을 남기되, AssertionError는 즉시 catch
    try:
        assert_equal(True, False, msg)
    except AssertionError:
        pass
    except Exception:
        pass

    try:
        log(f"❌ {msg}")
    except Exception:
        pass

    # 필요 시 스냅샷(assert_equal에서 실패 시 남기지 못했을 때 대비)
    if shot:
        try:
            snapshot(msg=f"❌ {msg}")
        except Exception:
            pass
    
    # ✅ Run 표준 FAIL 1건으로 누적 (msg 내용과 무관하게 항상 실패로 기록)
    try:
        if env is not None and getattr(env, "run_log_path", None):
            ts = time.strftime("%H:%M:%S")
            _append_line(env.run_log_path, f"[{ts}] {msg}")
            st = _normalize_status_from_msg(msg)
            # 카운트/누적
            env.run_counts[st] = int(env.run_counts.get(st, 0)) + 1

            # total_fail도 동기화
            if not hasattr(env, "total_fail") or env.total_fail is None:
                env.total_fail = 0
            env.total_fail = int(env.total_fail) + 1

            # Failures 상세 누적
            if not hasattr(env, "run_fail_logs") or env.run_fail_logs is None:
                env.run_fail_logs = []

            # iter가 있으면 iter, 없으면 시간으로 대체(= run_flows 이전 FAIL도 표시 가능)
            iter_val = getattr(env, "_ctx_iter", None)
            iter_show = str(iter_val) if iter_val is not None else ts

            env.run_fail_logs.append({
                "iter": iter_show,
                "name": str(getattr(env, "_ctx_flow", "") or "STEP"),
                "error": str(msg),
                "kind": "soft_fail",
                "flow": str(getattr(env, "_ctx_flow", "") or ""),
                "time": ts,
            })
    except Exception:
        pass

    # adb shell 로 전달하는 메시지에서만 특수문자 정규화
    try:
        safe = _sanitize_for_shell_log(msg)
        adb_env_map = adb_env(env) if env else None
        subprocess.call(
            ["adb", "shell", "log", "-t", "QA", f"[STEP] {safe}"],
            env=adb_env_map
        )
    except Exception:
        # 로깅 실패가 테스트를 깨뜨리지 않도록 무시
        pass

# 메모 추가
def note(msg: str, env: Optional[QAEnv] = None):
    """Run Notes(사람용 메모) 누적. summary/meta에 표시됨."""
    env = use_env(env)
    try:
        env.run_notes.append(str(msg))
        # run.log에도 남기고 싶으면(선택)
        if getattr(env, "run_log_path", None):
            ts = time.strftime("%H:%M:%S")
            _append_line(env.run_log_path, f"[{ts}] [NOTE] {msg}")
    except Exception:
        pass
# 스크립트 활용 로그 기록 유틸 END =================================

def _exc_text(e: Exception) -> str:
    # 메시지 비어있는 예외를 '()'로 뭉개지 않게
    s = ""
    try:
        s = str(e).strip()
    except Exception:
        s = ""
    if s:
        return s
    # repr(e)는 AssertionError() 같은 것도 형태가 남음
    return f"{type(e).__name__} {e!r}"

# --- 안전 연결 유틸: MINICAP→(실패 시) ADBORI 폴백 ---
def _connect_with_fallback(serial: Optional[str] = None):
    """
    1) 기본은 아무 옵션도 붙이지 않고 연결한다. (minicap/javacap 가능하면 그걸 쓰게 둠)
    2) 정말 안 붙었을 때만 ADBCAP 계열로 한 번 더 시도한다.
    3) QA_USE_MINICAP=1 이면 1순위로 minicap을 시도하고, 안되면 평범한 기본 연결로 떨어뜨린다.
    """
    base = "Android:///"
    env_serial = os.environ.get("ANDROID_SERIAL") or os.environ.get("ADB_SERIAL")
    serial = serial or env_serial

    use_minicap = os.environ.get("QA_USE_MINICAP") == "1"

    # 0) URI 조립
    if serial:
        plain_uri = f"{base}{serial}"             # ← 이게 기본
        minicap_uri = f"{base}{serial}?cap_method=MINICAP&ori_method=MINICAP&touch_method=ADB"
    else:
        plain_uri = base
        minicap_uri = f"{base}?cap_method=MINICAP&ori_method=MINICAP&touch_method=ADB"

    # 1) QA_USE_MINICAP=1 이면 먼저 minicap으로 붙어보고
    if use_minicap:
        try:
            dev = connect_device(minicap_uri)
            time.sleep(0.1)
            dev.get_current_resolution()
            print(f"[DEV] connected via MINICAP: {dev.uuid}")
            return dev
        except Exception as e:
            print(f"[DEV] minicap connect failed, fallback to plain: {e}")

    # 2) 가장 중요한 기본 경로: **옵션 없이** 붙인다
    try:
        dev = connect_device(plain_uri)
        time.sleep(0.1)
        dev.get_current_resolution()
        print(f"[DEV] connected (plain): {dev.uuid}")
        return dev
    except Exception as e:
        print(f"[DEV] plain connect failed: {e}")

    # 3) 정말 안 될 때만 ADBCAP로 최후 fallback
    if serial:
        adb_uri = f"{base}{serial}?cap_method=ADBCAP&ori_method=ADBORI&touch_method=ADB"
    else:
        adb_uri = f"{base}?cap_method=ADBCAP&ori_method=ADBORI&touch_method=ADB"

    dev = connect_device(adb_uri)
    time.sleep(0.1)
    dev.get_current_resolution()
    print(f"[DEV] connected (fallback ADB): {dev.uuid}")
    return dev


# 디바이스 보장/전환
def ensure_device(serial: Optional[str] = None):
    """
    IDE 실행: 이미 auto_setup으로 붙어 있으면 그대로 사용.
    serial 지정 시: 해당 UUID/시리얼로 current 전환(없으면 연결 후 전환).
    """
    if serial:
        try:
            set_current(serial)
            return device()
        except Exception:
            pass
        _connect_with_fallback(serial)
        set_current(serial)
        return device()

    # 시리얼 미지정
    try:
        return device()
    except Exception:
        _connect_with_fallback(None)
        set_current(0)
        return device()
    
# --- 앱 시작 공통 헬퍼 (per-app launch 지원) ------------------------------
def _adb_exec(env, *args) -> str:
    serial = getattr(env, "serial", None)
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out.decode("utf-8", "ignore")
    except subprocess.CalledProcessError as e:
        detail = ""
        try:
            detail = e.output.decode("utf-8", "ignore")
        except Exception:
            detail = str(getattr(e, "output", ""))
        # 원인 식별을 위해 cmd/rc/output을 묶어서 던짐
        raise RuntimeError(
            f"adb failed rc={e.returncode} cmd={e.cmd} output={detail}"
        ) from e

# ==========================================================
# Yosemite IME(입력기) 보정 헬퍼
#  - 프로세스는 살아있는데 default_input_method가 yosemite가 아닌 상태를 방지
#  - hard reset/force-stop 이후 타이핑 불능을 구조적으로 차단
# ==========================================================
# yosemite 프로세스 생존 확인 및 재기동
def ensure_yosemite_alive(env: Optional[QAEnv] = None, force_restart: bool = False) -> bool:
    """
    yosemite(com.netease.nie.yosemite) 프로세스가 살아있는지 확인하고,
    죽어있으면 재기동을 시도한다.

    Returns:
        True  - 살아있음(또는 복구 성공)
        False - 복구 시도했으나 살아있지 않음
    """
    env = use_env(env)
    if env is None:
        return False

    pkg = "com.netease.nie.yosemite"

    # 기기/버전별 서비스 컴포넌트명 차이를 흡수하기 위한 후보군
    service_candidates = [
        f"{pkg}/.Service",                   # dumpsys에서 확인된 현재 단말 서비스
        f"{pkg}/.service.YosemiteService",   # 과거/다른 환경 대비(기존 하드코딩)
    ]

    def _pid() -> str:
        try:
            out = _adb_exec(env, "shell", "pidof", pkg) or ""
            return out.strip()
        except Exception:
            return ""

    # 이미 살아있으면(강제 재기동이 아니면) 바로 성공
    if _pid() and not force_restart:
        return True

    # 1) startservice 시도
    for comp in service_candidates:
        try:
            _adb_exec(env, "shell", "am", "startservice", comp)
            time.sleep(0.6)
            if _pid():
                return True
        except Exception:
            pass

    # 2) start-foreground-service 시도(안드로이드 제약 대응)
    for comp in service_candidates:
        try:
            _adb_exec(env, "shell", "am", "start-foreground-service", comp)
            time.sleep(0.8)
            if _pid():
                return True
        except Exception:
            pass

    # 3) 최후: 런처 기동(monkey)
    try:
        _adb_exec(env, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(0.8)
        if _pid():
            return True
    except Exception:
        pass

    return bool(_pid())

def _get_default_ime(env: Optional['QAEnv'] = None) -> Optional[str]:
    env = use_env(env)
    if env is None:
        return None
    try:
        out = _adb_exec(env, "shell", "settings", "get", "secure", "default_input_method").strip()
        if not out or out.lower() == "null":
            return None
        return out
    except Exception:
        return None


def _list_ime_ids(env: Optional['QAEnv'] = None) -> List[str]:
    env = use_env(env)
    if env is None:
        return []
    try:
        out = _adb_exec(env, "shell", "ime", "list", "-s")
        ims = [x.strip() for x in (out or "").splitlines() if x.strip()]
        return ims
    except Exception:
        return []


def _find_yosemite_ime_id(env: Optional['QAEnv'] = None, ime_ids: Optional[List[str]] = None) -> Optional[str]:
    env = use_env(env)
    if env is None:
        return None

    ime_ids = ime_ids if ime_ids is not None else _list_ime_ids(env)
    if not ime_ids:
        return None

    # 1순위: 패키지명 정확히 포함
    for x in ime_ids:
        if "com.netease.nie.yosemite" in x:
            return x

    # 2순위: 'yosemite' 키워드 포함
    for x in ime_ids:
        if "yosemite" in x.lower():
            return x

    return None


def ensure_yosemite_ime(
    env: Optional['QAEnv'] = None,
    *,
    force_set: bool = False,
    ime_id: Optional[str] = None
) -> bool:
    """
    현재 default IME가 yosemite가 아니면 ime enable/set으로 강제 전환한다.
    - force_set=True: 이미 yosemite여도 다시 set 수행(하드리셋 직후 권장)
    """
    env = use_env(env)
    if env is None:
        return False

    try:
        ime_ids = _list_ime_ids(env)
        target = ime_id or _find_yosemite_ime_id(env, ime_ids)
        if not target:
            step("[WARN] yosemite IME id를 찾지 못했습니다(ime list -s).", env=env)
            return False

        cur = _get_default_ime(env)
        if (cur == target) and (not force_set):
            return True

        # enable → set 순서가 안정적
        try:
            _adb_exec(env, "shell", "ime", "enable", target)
        except Exception:
            pass

        _adb_exec(env, "shell", "ime", "set", target)
        time.sleep(0.25)

        cur2 = _get_default_ime(env)
        if cur2 == target:
            step(f"[OK] yosemite IME 설정 완료: {target}", env=env)
            return True

        step(f"[WARN] yosemite IME 설정 실패(현재:{cur2}, 목표:{target})", env=env)
        return False

    except Exception as e:
        step(f"[WARN] ensure_yosemite_ime 예외: {e!r}", env=env)
        return False
# Yosemite IME(입력기) 보정 헬퍼 END==================================

# UIAutomation / Poco 치명적 오류 감지
def _is_poco_uia_fatal(msg: str) -> bool:
    """
    Poco/UIAutomation 치명 오류만 '보수적으로' 감지한다.
    - 중요: 'uiautomation ready' 같은 정상 로그는 절대 fatal로 잡지 않는다(과탐 방지).
    """
    m = (msg or "").lower()

    # 1) Airtest가 uiautomation 준비를 끝없이 기다리는 상태(실패 루프의 대표 신호)
    if "still waiting for uiautomation ready" in m:
        return True

    # 2) instrumentation이 실제로 죽었음을 나타내는 신호
    if "process crashed" in m:
        return True
    if "instrument timeout" in m or "[timeout] instrument timeout" in m:
        return True

    # 3) 연결 계열 하드 에러
    if "remote end closed connection" in m:
        return True
    if "eoferror" in m:
        return True
    if "socket connection broken" in m:
        return True

    # 'instrumentation_result' 단독은 과탐 여지가 있어 제외(문맥 없이도 찍히는 경우가 있음)
    return False

# 패키지의 PID 조회
def _pidof(env, package: str) -> Optional[int]:
    if not package:
        return None

    # 1) pidof -s (가능한 기기에서 가장 깔끔)
    try:
        out = (_adb_exec(env, "shell", "pidof", "-s", package) or "").strip()
        if out:
            return int(out.split()[0])
    except Exception:
        pass

    # 2) pidof (구형/제한 환경 대비)
    try:
        out = (_adb_exec(env, "shell", "pidof", package) or "").strip()
        if out:
            return int(out.split()[0])
    except Exception:
        pass

    # 3) 최후: ps 파싱(기기별 ps 옵션 차이가 커서 보수적으로)
    try:
        out = (_adb_exec(env, "shell", "ps") or "")
        for line in out.splitlines():
            if package in line:
                cols = line.split()
                # 보통 PID는 2번째 컬럼(헤더 여부/형식 차이 존재)
                for token in cols:
                    if token.isdigit():
                        return int(token)
    except Exception:
        pass

    return None

# 공용 poco getter
def get_poco(env: Optional['QAEnv'] = None):
    """
    - env.ui_mode 기준으로 필요한 드라이버만 생성한다.
    - (중요) 현재 모드와 무관한 드라이버를 '겸사겸사' 띄우지 않는다.
      -> UnityPoco 초기화는 PocoService instrumentation을 건드려 crash/loop를 유발할 수 있음.
    """
    env = use_env(env)
    if env is None:
        raise RuntimeError("QAEnv가 설정되지 않았습니다. set_current_env(env) 먼저 호출하세요.")

    now = time.time()
    disabled_until = getattr(env, "_poco_disabled_until", 0.0)
    if now < disabled_until:
        raise RuntimeError(f"poco disabled (cooldown {disabled_until-now:.1f}s)")

    ensure_device(env.serial)

    # 이미 세팅돼 있으면 그대로 반환
    if getattr(env, "poco", None) is not None:
        return env.poco

    mode = (env.ui_mode or "").lower().strip()

    if mode == "native":
        if env.apoco is None:
            env.apoco = AndroidUiautomationPoco(
                use_airtest_input=True,
                screenshot_each_action=False
            )
            # dump는 가끔 여기서 바로 터지기도 해서, 필요 최소로만
            try:
                env.apoco.agent.hierarchy.dump()
            except Exception:
                pass
            time.sleep(0.2)

        env.poco = env.apoco
        env.poco_active = env.apoco
        return env.poco

    # default: unity
    if env.upoco is None:
        env.upoco = UnityPoco()
        try:
            env.upoco.agent.hierarchy.dump()
        except Exception:
            pass
        time.sleep(0.2)

    env.poco = env.upoco
    env.poco_active = env.upoco
    return env.poco

# ---- Poco 전역 프록시 ----
class _PocoProxy:
    """
    전역 poco 프록시.
    핵심: 매 호출마다 get_poco()를 호출하지 말고,
          이미 env.poco가 있으면 그걸 즉시 사용한다.
    """
    def _handle(self):
        env = use_env()
        if env is not None and getattr(env, "poco", None) is not None:
            return env.poco
        # env.poco가 없을 때만 생성 경로로
        return get_poco(env)

    def __call__(self, *args, **kwargs):
        # ✅ selector 첫 인자가 "패키지:id/..." 형태면 env.package로 자동 치환
        if args and isinstance(args[0], str):
            env = use_env()
            if env is not None:
                s = args[0]
                # "com.xxx:id/yyy" 형태만 처리
                if ":id/" in s:
                    pkg_part, id_part = s.split(":id/", 1)
                    aliases = getattr(env, "package_aliases", None)
                    if not aliases:
                        aliases = [getattr(env, "package", "")]
                    # pkg_part가 alias에 포함될 때만 치환 (android:id/... 등은 그대로 유지)
                    if pkg_part in aliases:
                        new_pkg = getattr(env, "package", "")
                        if new_pkg:
                            s = f"{new_pkg}:id/{id_part}"
                            args = (s,) + args[1:]

        return self._handle()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._handle(), name)

poco = _PocoProxy()

def _resolve_obj(obj_or_fn):
    return obj_or_fn() if callable(obj_or_fn) else obj_or_fn

# dumpsys에서 현재 top activity를 뽑는 보조 함수
_TOP_PATTERNS = [
    r"Resumed(Activity)?[:\s].*\s(\S+)/(\S+)",
    r"ACTIVITY\s+(\S+)/(\S+)",
    r"mCurrentFocus=Window\{[^\s]+\s+(\S+)/(\S+)\}",
]

def detect_top_component(env, expect_pkg: str = None):
    """
    현재 화면에 떠 있는 컴포넌트를 pkg/activity로 반환.
    expect_pkg가 주어지면 그 패키지만 반환.
    """
    for cmd in (
        ("shell", "cmd", "activity", "top"),
        ("shell", "dumpsys", "activity", "activities"),
        ("shell", "dumpsys", "window", "windows"),
    ):
        try:
            out = _adb_exec(env, *cmd)
        except Exception:
            continue
        for line in out.splitlines():
            line = line.strip()
            for pat in _TOP_PATTERNS:
                m = re.search(pat, line)
                if not m:
                    continue
                # 패턴마다 그룹 위치가 살짝 달라서 분기
                if "Resumed" in pat:
                    pkg, cls = m.group(2), m.group(3)
                else:
                    pkg, cls = m.group(1), m.group(2)
                if cls.startswith("."):
                    cls = pkg + cls
                if (expect_pkg is None) or (pkg == expect_pkg):
                    return pkg, cls
    return None, None

# 앱 시작 통합 진입점
def start_app_generic(env, package: str):
    """
    앱 시작 통합 진입점.
    1) 최초는 start
    2) 그래도 안되면 monkey
    3) 마지막으로 지금 떠 있는 동일 패키지 액티비티를 다시 띄움
    """
    env = use_env(env)
    # 1) 기본 start
    try:
        start_app(package)
        return
    except Exception:
        pass

    # 2) monkey fallback
    try:
        _adb_exec(
            env,
            "shell", "monkey",
            "-p", package,
            "-c", "android.intent.category.LAUNCHER",
            "1"
        )
        return
    except Exception:
        pass

    # 3) top 재실행 (내부 런처 때문에 매니페스트 런처가 안 먹을 때 대비)
    pkg, cls = detect_top_component(env, expect_pkg=package)
    if pkg and cls:
        _adb_exec(env, "shell", "am", "start", "-S", "-n", f"{pkg}/{cls}")

# 앱 재시작 및 Poco 재연결
def restart_app(retries:int=3, app_start=None, env: Optional[QAEnv]=None) -> Tuple[AndroidUiautomationPoco, UnityPoco]:
    """
    앱 재시작 + 드라이버 재연결.
    app_start가 넘어오면 그걸로 앱을 실행하고,
    없으면 start_app_generic으로(= start→monkey→top 재실행).
    """
    env = use_env(env)

    step(f"앱 재시작 중...{env.package}")
    ensure_device(env.serial)
    last_err = None
    if app_start is None:
        app_start = env.app_start

    for attempt in range(1, retries+1):
        try:
            pkg = env.package

            # 1) 앱 재시작
            stop_app(pkg)
            start_app_generic(env, pkg)
            time.sleep(1.0)

            # 2) 드라이버 초기화 후, get_poco로 재연결
            env.apoco = None
            env.upoco = None
            env.poco  = None

            get_poco(env)           # 🔹 여기서 apoco/upoco/poco 셋업
            env.set_ui_mode(env.ui_mode)

            if env.poco is None:
                raise RuntimeError("poco driver not available")
            
            # 3) 앱이 실행 중이 아니면(런처에 막힘 등) -> 이때만 app_start 실행
            if not is_app_running(pkg, env=env, debug=True):
                if callable(app_start):
                    step(f"[RESTART] 앱이 실행 중이 아님 -> app_start() 실행 ({attempt}/{retries})", env=env)
                    app_start()
                    time.sleep(1.0)

                # app_start 이후에도 실행 중이 아니면 실패 처리(재시도)
                if not is_app_running(pkg, env=env, debug=True):
                    raise RuntimeError("app_start() did not bring app to foreground")

            time.sleep(env.restart_delay)

            return env.apoco, env.upoco

        except Exception as e:
            last_err = e
            
            # 연결/소켓 계열(Windows 10053 등)일 때는 디바이스 재확인
            if "10053" in str(e) or "Connection" in str(e):
                try:
                    ensure_device(env.serial)
                except Exception as ee:
                    last_err = ee
            step(f"[RESTART][WARN] {attempt}/{retries} 실패: {last_err}", env=env, shot=True)
            time.sleep(2.0)

    raise RuntimeError(f"앱 재시작 실패({retries}회 시도): {last_err}")

# ==========================================================
# Poco 하드 리셋용 예외
#  - 환경 자체가 깨져서 스크립트 레벨 재실행이 필요할 때 사용
# ==========================================================
class PocoFatalError(RuntimeError):
    """Poco 환경이 복구 불가능하게 깨진 경우 사용하는 예외."""
    pass


# ==========================================================
# Poco 하드 리셋 헬퍼
#  - get_poco() 수준의 소프트 리셋으로 회복되지 않을 때 호출
#  - 스크립트 "처음 실행했을 때"와 최대한 비슷한 상태로 되돌리는 것을 목표
# ==========================================================
def poco_hard_reset(env: Optional[QAEnv] = None, reason: str = ""):
    """
    Poco / uiautomation / yosemite 상태가 심하게 꼬인 경우:
      1) 관련 프로세스 강제 종료 (pocoservice, yosemite)
      2) 앱 재시작 (restart_app)
      3) env의 Poco 드라이버 핸들 초기화
      4) get_poco()로 새 드라이버 생성
      5) env.on_ready() 재실행 시도

    실패 시 PocoFatalError를 발생시켜 상위에서 스크립트 재실행 등을 결정할 수 있게 한다.
    """
    env = use_env(env)
    if env is None:
        raise RuntimeError(
            "poco_hard_reset 호출 시 QAEnv가 없습니다. "
            "set_current_env(env)를 먼저 호출해 주세요."
        )

    reason_text = reason or "사유 미기재"
    step(f"[FATAL] Poco 하드 리셋 시도: {reason_text}", env=env)

    # 1) 디바이스 연결 재확인
    try:
        ensure_device(env.serial)
    except Exception as e:
        step(f"[FATAL] 장치 재연결 실패: {e!r}", env=env)
        raise PocoFatalError(f"장치 재연결 실패: {e!r}")

    # 2) poco / yosemite 관련 프로세스 강제 종료
    for pkg in ("com.netease.open.pocoservice", "com.netease.nie.yosemite"):
        try:
            _adb_exec(env, "shell", "am", "force-stop", pkg)
            step(f"[OK] 백그라운드 프로세스 종료: {pkg}", env=env)
        except Exception as e:
            # 강제 종료 실패는 치명적이진 않으므로 WARN만 남기고 계속 진행
            step(f"[WARN] 백그라운드 프로세스 종료 실패({pkg}): {e!r}", env=env)

    # 2.5) yosemite 재기동 (🔥 핵심)
    try:
        ok = ensure_yosemite_alive(env=env, force_restart=True)

        if ok:
            step("[OK] yosemite service 재기동", env=env)
            time.sleep(1.0)

            # ✅ 하드리셋/force-stop 이후 default IME가 풀리는 문제 방지
            ensure_yosemite_ime(env=env, force_set=True)
        else:
            # 기존 note/step 정책 유지
            step("[WARN] yosemite 재기동 실패: 복구 시도 후에도 pid 없음", env=env)
            note("[RISK] yosemite 재기동 실패(추가 불안정 가능): 복구 시도 후에도 pid 없음", env=env)

    except Exception as e:
        # 기존 note/step 정책 유지
        step(f"[WARN] yosemite 재기동 실패: {e!r}", env=env)
        note(f"[RISK] yosemite 재기동 실패(추가 불안정 가능): {e!r}", env=env)

    # 3) 기존 Poco 드라이버 핸들 초기화
    #    - 이후 get_poco() 호출 시 항상 새로 붙도록 만들기 위함
    try:
        env.apoco = None
        env.upoco = None
        env.poco = None
        env.poco_active = None
        step("[OK] 기존 Poco 드라이버 핸들 초기화 완료", env=env)
    except Exception as e:
        step(f"[WARN] Poco 핸들 초기화 중 예외 발생 (무시하고 계속): {e!r}", env=env)

    # 4) 앱 재시작
    try:
        restart_app(env=env)
        step(f"[OK] 앱 재시작 완료: {env.package}", env=env)
    except Exception as e:
        step(f"[FATAL] 앱 재시작 실패: {e!r}", env=env)
        raise PocoFatalError(f"앱 재시작 실패: {e!r}")

    # 5) Poco 드라이버 재생성 (현재 ui_mode 기준)
    try:
        p = get_poco(env=env)
        step(f"[OK] Poco 드라이버 재생성 완료 (ui_mode={env.ui_mode})", env=env)
    except Exception as e:
        step(f"[FATAL] Poco 드라이버 재생성 실패: {e!r}", env=env)
        raise PocoFatalError(f"Poco 드라이버 재생성 실패: {e!r}")

    # 6) on_ready 콜백 재실행 (있다면)
    try:
        if callable(env.on_ready):
            step("[INFO] on_ready 콜백 재실행 시작", env=env)
            env.on_ready()
            step("[OK] on_ready 콜백 재실행 완료", env=env)
    except Exception as e:
        # 여기서도 치명적으로 볼지, 경고로만 둘지는 정책 선택
        # 우선은 경고만 남기고 계속 진행하도록 두되,
        # 필요 시 PocoFatalError로 승격시켜도 된다.
        step(f"[WARN] on_ready 재실행 실패: {e!r}", env=env)

    # 필요 시 상위에서 바로 사용할 수 있도록 새 poco를 반환
    return p

# --- 소켓 끊김 재시도 헬퍼 ---
def _handle_socket_broken(e, env=None, *, where="[CORE]"):
    """
    통신/연결 계열 끊김 발생 시 복구:
      - ensure_device
      - Poco 드라이버 재생성(get_poco)
      - 필요 시 poco_hard_reset 1회
    """
    msg = (str(e) or "").lower()

    # ✅ 기존: socket connection broken만
    # if "socket connection broken" not in msg:
    #     return False

    # ✅ 확장: RemoteDisconnected / Connection aborted 등도 복구 대상으로 포함
    disconnect_keys = (
        "socket connection broken",
        "remote end closed connection",
        "remotedisconnected",
        "connection aborted",
        "eoferror",
        "connection reset",
        "winerror 10053",
        "winerror 10054",
        "winerror 10060",
    )
    if not any(k in msg for k in disconnect_keys):
        return False

    env = use_env(env)
    note(f"[RECOVERY] disconnect 감지 → 드라이버/서비스 복구 시도 ({where})", env=env)

    try:
        serial = getattr(env, "serial", None) if env is not None else None
        if env is not None:
            step(f"{where} WARN ⚠️ socket connection broken 감지 → 디바이스 재연결 시도")

        # 1) 디바이스 재연결
        ensure_device(serial)
        time.sleep(1.0)

        # 2) Poco 드라이버 강제 재연결
        if env is not None:
            # 기존 드라이버 핸들 초기화
            env.apoco = None
            env.upoco = None
            env.poco = None
            env.poco_active = None

            try:
                # get_poco가 env.ui_mode 기준으로 다시 apoco/upoco/poco를 붙여준다
                get_poco(env)
                step(f"{where} [INFO] 디바이스 및 Poco 드라이버 재연결 완료 → 동작 재시도 예정")
                return True
            except Exception as e3:
                step(f"{where} [ERR] Poco 드라이버 재연결 실패: {e3}", True)
                # 🔸 여기서 하드 리셋 마지막 1회 시도
                try:
                    poco_hard_reset(env, reason=f"{where} 소켓 복구 실패 → 하드 리셋")
                    step(f"{where} [INFO] Poco 하드 리셋 성공 → 동작 재시도 예정", env=env)
                    return True
                except PocoFatalError as e4:
                    step(f"{where} [FATAL] Poco 하드 리셋도 실패: {e4}", env=env, shot=True)
                    return False

        return True

    except Exception as e2:
        if env is not None:
            step(f"{where} [ERR] 디바이스 재연결 실패: {e2}", True)
        return False
# Poco 하드 리셋 유틸 END ===========================================

# 리소스 ID 셀렉터 자동 치환 헬퍼
def _translate_resource_id_selector(selector: str, env=None) -> str:
    """
    selector가 'com.xxx:id/name' 형태면 env.package로 치환.
    env.package_aliases가 있으면 alias 목록에 포함된 패키지만 치환.
    """
    if not selector or not isinstance(selector, str):
        return selector

    if ":id/" not in selector:
        return selector

    e = use_env(env)
    if e is None:
        return selector

    pkg_part, id_part = selector.split(":id/", 1)

    # android:id/... 같은 시스템 패키지 보호
    new_pkg = getattr(e, "package", None)
    if not new_pkg:
        return selector

    aliases = getattr(e, "package_aliases", None)
    if not aliases:
        aliases = [new_pkg]

    if pkg_part in aliases:
        return f"{new_pkg}:id/{id_part}"

    return selector

# 리소스 ID 셀렉터 자동 치환 헬퍼
def install_poco_selector_autopatch():
    """
    poco("pkg:id/x") 뿐 아니라
    obj.child("pkg:id/x"), obj.offspring("pkg:id/x"), (필요 시) obj.sibling("pkg:id/x")도
    env.package로 자동 치환되게 patch.
    - 원본 메서드 시그니처를 건드리지 않도록 *args, **kwargs 래퍼로 감싼다.
    """
    try:
        from poco.proxy import UIObjectProxy
    except Exception:
        return

    if getattr(UIObjectProxy, "_qa_autopatch_installed", False):
        return

    def _wrap_method(method_name: str):
        if not hasattr(UIObjectProxy, method_name):
            return

        orig = getattr(UIObjectProxy, method_name)

        # 중복 패치 방지: 원본 저장
        store = getattr(UIObjectProxy, "_qa_autopatch_originals", None)
        if store is None:
            store = {}
            UIObjectProxy._qa_autopatch_originals = store
        if method_name in store:
            return

        store[method_name] = orig

        def wrapped(self, *args, **kwargs):
            # 1) 첫 positional 인자가 str이면 selector로 보고 치환
            if args and isinstance(args[0], str):
                new0 = _translate_resource_id_selector(args[0], None)
                args = (new0,) + args[1:]
            else:
                # 2) kwargs에 selector가 들어오는 케이스 방어 (버전/호출 형태 차이)
                for k in ("query", "selector", "name"):
                    if k in kwargs and isinstance(kwargs[k], str):
                        kwargs[k] = _translate_resource_id_selector(kwargs[k], None)
                        break

            return orig(self, *args, **kwargs)

        setattr(UIObjectProxy, method_name, wrapped)

    # selector 문자열을 직접 받는 메서드들만 패치
    for m in ("child", "offspring", "sibling"):
        _wrap_method(m)

    UIObjectProxy._qa_autopatch_installed = True


# 요소 라벨 추출 (디버그용)
def get_label(el) -> str:
    """
    다양한 타입(Poco UIObjectProxy, 일반 객체, 문자열 등)에 대해
    사람이 읽기 좋은 라벨을 최대한 안정적으로 만들어 반환한다.

    - 텍스트만 가져오는 용도가 아니라, desc/resource-id/class 등도 고려
    - UIObjectProxy가 아직 resolve되지 않아도 selector 문자열 파싱으로 보완
    """

    if el is None:
        return "None"

    # 이미 문자열이면 그대로
    if isinstance(el, str):
        return el.strip() or el

    def _trim_res_id(res_id: str) -> str:
        # com.xxx:id/foo -> foo 로 축약 (너무 길면 가독성 저하)
        if not res_id:
            return res_id
        # 흔한 패턴들 처리
        # 예: "com.kyowon.literacy:id/textFrontWord" -> "textFrontWord"
        m = re.search(r":id/([^/]+)$", res_id)
        if m:
            return m.group(1)
        m = re.search(r"/([^/]+)$", res_id)
        if m:
            return m.group(1)
        return res_id

    def _safe_call(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    def _safe_attr(obj, key, default=None):
        """
        Poco UIObjectProxy의 attr('text') / attr('name') 같은 형태를 우선 시도.
        그 외에는 일반 getattr도 시도.
        """
        # Poco: el.attr("text")
        if hasattr(obj, "attr") and callable(getattr(obj, "attr")):
            try:
                v = obj.attr(key)
                return v if v not in (None, "") else default
            except Exception:
                pass

        # 일반 객체: getattr(obj, key)
        try:
            v = getattr(obj, key)
            return v if v not in (None, "") else default
        except Exception:
            return default

    # 1) text 우선, 없으면 name(+인덱스) 우선
    def _extract_index_suffix(obj) -> str:
        # 1) attr로 instance/index가 잡히는 경우
        for k in ("instance", "index"):
            v = _safe_attr(obj, k, None)
            if v is not None:
                s = str(v).strip()
                if s.isdigit():
                    return f"[{s}]"

        # 2) str(obj)에서 instance/index 또는 [n] 패턴 추출 (poco selector fallback)
        try:
            s = str(obj)
            m = re.search(r"(?:instance|index)=(\d+)", s)
            if m:
                return f"[{m.group(1)}]"
            m = re.search(r"\[(\d+)\]", s)
            if m:
                return f"[{m.group(1)}]"
        except Exception:
            pass

        return ""

    # Poco get_text()가 있는 경우
    if hasattr(el, "get_text") and callable(getattr(el, "get_text")):
        t = _safe_call(lambda: el.get_text(), None)
        if t:
            t = str(t).strip()
            if t:
                return t

    # attr: text
    t = _safe_attr(el, "text", None)
    if t:
        t = str(t).strip()
        if t:
            return t

    # ✅ text가 없으면 name 반환 + 인덱스 있으면 [n] 붙이기
    name = _safe_attr(el, "name", None)
    if name:
        name = str(name).strip()
        if name:
            suf = _extract_index_suffix(el)
            # 이미 name에 [n]이 붙어있으면 중복 방지
            if suf and not re.search(r"\[\d+\]$", name):
                return name + suf
            return name

    # 나머지는 기존 fallback(필요하면 desc 등)로 진행
    v = _safe_attr(el, "desc", None)
    if v:
        v = str(v).strip()
        if v:
            return v

    v = _safe_attr(el, "contentDescription", None) or _safe_attr(el, "content-desc", None) or _safe_attr(el, "content_desc", None)
    if v:
        v = str(v).strip()
        if v:
            return v

    # 2) resource-id 계열
    for k in ("resourceId", "resource-id", "resource_id", "id"):
        rid = _safe_attr(el, k, None)
        if rid:
            rid_s = _trim_res_id(str(rid).strip())
            if rid_s:
                return rid_s

    # 3) class/type 계열
    # Poco는 type/className이 잡히는 경우가 있고, 일반 객체는 __class__.__name__
    for k in ("className", "class", "type"):
        cv = _safe_attr(el, k, None)
        if cv:
            return str(cv).strip()

    # 4) selector 문자열 파싱 fallback
    # 예: UIObjectProxy of "text=훈련&com.kyowon.literacy:id/textFrontWord"
    try:
        s = str(el)

        # text/name/desc 우선 추출
        for key in ("text", "name", "desc"):
            m = re.search(rf'{key}=([^&"]+)', s)
            if m:
                v = m.group(1).strip()
                if v:
                    return v

        # com.xxx:id/foo 같은 패턴 추출
        m = re.search(r'([A-Za-z0-9_.]+:id/[^&"]+)', s)
        if m:
            return _trim_res_id(m.group(1).strip())

        # 마지막으로 따옴표 안 selector 통째로라도 반환(너무 길면 그대로 두되, 너희쪽에서 잘라 써도 됨)
        m = re.search(r'UIObjectProxy of "([^"]+)"', s)
        if m:
            v = m.group(1).strip()
            if v:
                return v

        return s
    except Exception:
        # 5) 최후의 수단
        try:
            return repr(el)
        except Exception:
            return "<?>"

# ======================================
# 🎯 클릭/입력 공통 헬퍼
#   - must_* : 실패 시 예외 발생
#   - try_*  : 실패 시 False 리턴 (예외 삼킴)
#   - safe_* : 하위호환용 이름 (기존 스크립트 안전)
# ======================================
# --- CLICK 공통 코어 ---
def _click_core(poco_obj, *, timeout: float = 5, env=None, fast: bool = False):
    env = use_env(env)
    attempt = 0
    last_err = None
    used_exc_handler = False  # 예외 처리기는 클릭 1번당 한 번만 태움
    poco_obj = _resolve_obj(poco_obj)

    while attempt < 3:
        attempt += 1
        try:
            if not fast:
                poco_obj.wait_for_appearance(timeout)
            poco_obj.click()
            return

        except Exception as e:
            last_err = e
            msg = str(e)

            # ✅ (A) disconnect 복구를 fatal보다 먼저 (1번째 시도에만)
            if attempt == 1 and _handle_socket_broken(e, env=env, where="[CLICK_CORE]"):
                continue

            # ✅ (B) fatal 감지 → poco 비활성화 후 상위로 오류 던짐
            if _is_poco_uia_fatal(msg):
                # (수정) 클릭 레벨에서 하드리셋으로 들어가면 루프가 더 커질 수 있음.
                # 여기서는 poco를 잠시 비활성화하고, 상위(플로우/런너)에서 종료/재시작을 결정.
                if env is not None:
                    env._poco_disabled_until = time.time() + 120.0  # 2분간 poco 재시도 금지
                raise

            # (C) 앱별 예외 처리기 (env.handle_exceptions) 1회만
            handler = getattr(env, "handle_exceptions", None) if env is not None else None
            if (not used_exc_handler) and callable(handler):
                used_exc_handler = True
                try:
                    ret = handler(e, env)
                    count = int(ret or 0)
                except Exception as he:
                    step(f"[CLICK_CORE] handle_exceptions 에러: {he}", True)
                    count = 0

                if count > 0 and attempt < 3:
                    step(f"[CLICK_CORE] 예외 처리기로 {count}개 rule 처리 → 재시도")
                    continue

            # 여기까지 왔으면:
            #   - socket 복구 실패 or 조건 불일치
            #   - 예외 처리기 없음 or rule 0개 처리
            #   - 더 이상 재시도 불가
            raise last_err


def must_click(poco_obj, desc: str = None, *,
               timeout: float = 5, env: Optional['QAEnv'] = None, fast: bool = False) -> bool:
    """
    필수 클릭(기본: 실패해도 계속 진행):
      - 실패 시: FAIL 로그 + Airtest Failed(assertion) 기록 + 예외 발생
    """
    env = use_env(env)

    try:
        _click_core(poco_obj, timeout=timeout, env=env, fast=fast)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[MUST_CLICK] {get_label(poco_obj)}: PASS ✅")
        return True

    except Exception as e:
        et = _exc_text(e)
        msg = f"{desc}: FAIL ❌ ({et})" if desc else f"[MUST_CLICK] {get_label(poco_obj)}: FAIL ❌ ({et})"
        soft_fail(msg)
        raise

def try_click(poco_obj, desc: str = None, *,
              timeout: float = 5, env: Optional['QAEnv'] = None, fast: bool = False) -> bool:
    """
    시도형 클릭:
      - 실패해도 예외를 던지지 않고 False 리턴.
      - 반복 루프/보조 기능 등에서 사용.
    """
    env = use_env(env)
    try:
        _click_core(poco_obj, timeout=timeout, env=env, fast=fast)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[TRY_CLICK] {get_label(poco_obj)}: PASS ✅")
        return True
    except Exception as e:
        et = _exc_text(e)
        if desc:
            step(f"{desc}: WARN ⚠️ ({et})", True)
        else:
            step(f"[TRY_CLICK] {get_label(poco_obj)}: WARN ⚠️ ({et})", True)
        return False

# 🔁 하위호환: 기존 safe_click 은 "필수 클릭"으로 간주
def safe_click(poco_obj, desc: str = None, *,
               timeout: float = 5, env: Optional['QAEnv'] = None, fast: bool = False) -> bool:
    return must_click(poco_obj, desc=desc, timeout=timeout, env=env, fast=fast)


# --- TYPE 공통 코어 ---
def _type_core(poco_obj, value: str, *, enter: bool = True,
               timeout: float = 5, env: Optional['QAEnv'] = None):
    """
    기존 safe_type 로직을 그대로 옮긴 코어 함수.
    실패 시 예외를 그대로 발생시킨다.
    """
    env = use_env(env)
    poco_obj = _resolve_obj(poco_obj)

    def _sleep(t=0.06):
        time.sleep(t)

    def _get_txt(o):
        try:
            t = o.get_text()
            return "" if t is None else str(t)
        except Exception:
            return ""

    def _apoco():
        a = getattr(env, "apoco", None) or AndroidUiautomationPoco(
            use_airtest_input=True,
            screenshot_each_action=False
        )

        if env is not None and getattr(env, "apoco", None) is None:
            env.apoco = a
        return a

    def _clear_with_poco_obj(obj) -> bool:
        try:
            obj.set_text("")
            _sleep(0.05)
            # 일부 패스워드 필드는 get_text가 빈문자/None을 반환 → 검증 느슨하게
            return True
        except Exception:
            return False

    def _clear_with_apoco_focused() -> bool:
        try:
            a = _apoco()
            ed = a(type="android.widget.EditText", focused=True)
            if ed.exists():
                ed.set_text("")
                _sleep(0.05)
                return True
            return False
        except Exception:
            return False

    def _force_delete_keys():
        try:
            # 커서 끝 → Backspace 다수
            keyevent(123)       # MOVE_END
            for _ in range(80):
                keyevent(67)    # DEL(backspace)
            _sleep(0.03)
            # 커서 홈 → ForwardDelete 다수
            keyevent(122)       # MOVE_HOME
            for _ in range(80):
                keyevent(112)   # FORWARD_DEL
            _sleep(0.03)
        except Exception:
            pass

    try:
        # 프로세스 + IME까지 보정(핵심)
        ok = ensure_yosemite_alive(env=env)
        if ok:
            ensure_yosemite_ime(env=env, force_set=False)
    except Exception:
        pass

    # 0) 포커스 확보
    poco_obj.wait_for_appearance(timeout)
    poco_obj.click()
    _sleep(0.08)

    # 1) 모드에 따른 1순위 시도
    ui_mode = getattr(env, "ui_mode", None)
    cleared = False
    if ui_mode == "native":
        # 네이티브: 현재 poco(네이티브)로 바로 지우기
        cleared = _clear_with_poco_obj(poco_obj)
        if not cleared:
            cleared = _clear_with_apoco_focused()
    else:
        # 유니티(또는 알 수 없음): apoco로 focused EditText 지우기 우선
        cleared = _clear_with_apoco_focused()
        if not cleared:
            cleared = _clear_with_poco_obj(poco_obj)

    # 2) 둘 다 실패하면 키이벤트 강제 삭제 폴백
    if not cleared:
        _force_delete_keys()

    # 3) 최종 입력
    _sleep(0.03)
    try:
        text(value, enter=enter)
        _sleep(0.03)
    except Exception as e:
        et = _exc_text(e)
        msg = f"[TYPE_CORE] {get_label(poco_obj)}: FAIL ❌ - ({et})"
        soft_fail(msg)
        raise


def must_type(poco_obj, value: str, desc: str = None, *, enter: bool = True,
              timeout: float = 5, env: Optional['QAEnv'] = None) -> bool:
    """
    필수 입력(기본: 실패해도 계속 진행):
      - 실패 시: FAIL 로그 + Airtest Failed(assertion) 기록 + 예외 발생
    """
    env = use_env(env)

    try:
        _type_core(poco_obj, value=value, enter=enter, timeout=timeout, env=env)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[MUST_TYPE] {get_label(poco_obj)}: PASS ✅")
        return True

    except Exception as e:
        et = _exc_text(e)
        msg = f"{desc}: FAIL ❌ - ({et})" if desc else f"[MUST_TYPE] {get_label(poco_obj)}: FAIL ❌ - ({et})"
        soft_fail(msg)
        raise


def try_type(poco_obj, value: str, desc: str = None, *, enter: bool = True,
             timeout: float = 5, env: Optional['QAEnv'] = None) -> bool:
    """
    시도형 입력:
      - 실패해도 예외를 던지지 않고 False 리턴.
    """
    env = use_env(env)

    try:
        _type_core(poco_obj, value=value, enter=enter, timeout=timeout, env=env)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[TRY_TYPE] {get_label(poco_obj)}: PASS ✅")
        return True
    except Exception as e:
        et = _exc_text(e)
        if desc:
            step(f"{desc}: WARN ⚠️ - ({et})", True)
        else:
            step(f"[TRY_TYPE] {get_label(poco_obj)}: WARN ⚠️ - ({et})", True)
        return False

# 🔁 하위호환: 기존 safe_type 은 "필수 입력"으로 간주
def safe_type(poco_obj, value: str, desc: str = None, *, enter: bool = True,
              timeout: float = 10, env: Optional['QAEnv'] = None) -> bool:
    return must_type(poco_obj, value=value, desc=desc, enter=enter, timeout=timeout, env=env)


# --- CHECK 공통 코어 ---
def _check_core(poco_obj, *, timeout: float = 5, env=None) -> bool:
    env = use_env(env)
    attempt = 0
    last_err = None
    used_exc_handler = False
    poco_obj = _resolve_obj(poco_obj)

    while attempt < 3:
        attempt += 1
        try:
            poco_obj.wait_for_appearance(timeout=timeout)
            return True

        except Exception as e:
            last_err = e
            msg = str(e)

            # ✅ (A) disconnect 복구를 fatal보다 먼저 (1번째 시도에만)
            if attempt == 1 and _handle_socket_broken(e, env=env, where="[CHECK_CORE]"):
                continue

            # ✅ (B) fatal 감지 → poco 비활성화 후 상위로 오류 던짐
            if _is_poco_uia_fatal(msg):
                # (수정) 클릭 레벨에서 하드리셋으로 들어가면 루프가 더 커질 수 있음.
                # 여기서는 poco를 잠시 비활성화하고, 상위(플로우/런너)에서 종료/재시작을 결정.
                if env is not None:
                    env._poco_disabled_until = time.time() + 120.0  # 2분간 poco 재시도 금지
                raise

            # (C) 앱 예외 처리기
            handler = getattr(env, "handle_exceptions", None) if env is not None else None
            if (not used_exc_handler) and callable(handler):
                used_exc_handler = True
                try:
                    ret = handler(e, env)
                    count = int(ret or 0)
                except Exception as he:
                    step(f"[CHECK_CORE] handle_exceptions 에러: {he}", True)
                    count = 0

                if count > 0 and attempt < 3:
                    step(f"[CHECK_CORE] 예외 처리기로 {count}개 rule 처리 → 재시도")
                    continue
            
            # handler로 해결 못했더라도 timeout이면 재시도
            if isinstance(e, PocoTargetTimeout) and attempt < 2:
                step(f"[CHECK_CORE] timeout({timeout}s) → 재시도 {attempt}/2")
                continue

            # 여기까지 오면 더 이상 할 수 있는 게 없음 → 예외 밖으로
            raise last_err


def must_check(poco_obj, desc: str = None, *,
               timeout: float = 5, env: Optional['QAEnv'] = None, debug: bool = False) -> bool:
    """
    필수 체크(기본: 실패해도 계속 진행):
      - timeout 내 요소 등장해야 함
      - 실패 시: FAIL 로그 + Airtest Failed(assertion) 기록 + 예외 발생
    """
    env = use_env(env)

    try:
        _check_core(poco_obj, timeout=timeout, env=env)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[MUST_CHECK] {get_label(poco_obj)}: PASS ✅")
        return True
    except PocoTargetTimeout as e:
        msg = f"{desc}: FAIL ❌ (timeout {timeout}s)" if desc else f"[MUST_CHECK] {get_label(poco_obj)}: FAIL ❌ (timeout {timeout}s)"
        soft_fail(msg)
        # must_* 계열은 진짜 실패로 보고 예외를 던진다
        raise
    except Exception as e:
        et = _exc_text(e)
        msg = f"{desc}: FAIL ❌ (예외 발생: {et})" if desc else f"[MUST_CHECK] {get_label(poco_obj)}: FAIL ❌ (예외 발생: {et})"
        soft_fail(msg)
        raise


def try_check(poco_obj, desc: str = None, *,
              timeout: float = 5, env: Optional['QAEnv'] = None) -> bool:
    """
    시도형 체크:
      - 요소가 없어도 플로우를 죽이지 않고 False만 리턴.
      - 실패 시 WARN 로그로만 남긴다.
    """
    env = use_env(env)

    try:
        _check_core(poco_obj, timeout=timeout, env=env)
        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[TRY_CHECK] {get_label(poco_obj)}: PASS ✅")
        return True
    except PocoTargetTimeout as e:
        # timeout은 WARN으로만 보고 넘김
        if desc:
            step(f"{desc}: WARN ⚠️ (timeout {timeout}s)", True)
        else:
            step(f"[TRY_CHECK] {get_label(poco_obj)}: WARN ⚠️ (timeout {timeout}s)", True)
        return False
    except Exception as e:
        et = _exc_text(e)
        if desc:
            step(f"{desc}: WARN ⚠️ (예외 발생: {et})", True)
        else:
            step(f"[TRY_CHECK] {get_label(poco_obj)}: WARN ⚠️ (예외 발생: {et})", True)
        return False

# 🔁 하위호환: obj_check 는 기존 의미(예외 없는 체크)를 유지
def obj_check(poco_obj, desc: str = None, *,
              timeout: float = 5, env: Optional['QAEnv'] = None) -> bool:
    return try_check(poco_obj, desc=desc, timeout=timeout, env=env)

# =======================================================
# 👆 객체 및 이미지 기반 드래그 유틸
# =======================================================
def _xy_from_poco_center(poco_obj, timeout: float = 5.0, debug: bool = False) -> tuple[int, int]:
    """
    poco_obj의 중앙좌표를 px로 반환(좌표계 안정화 버전).
    우선순위:
      0) _get_region_from_poco()로 bbox 산출 후 bbox 중앙 사용 (pos/size + rot fallback 포함)  ✅ 가장 안정적
      1) get_position() fallback
      2) get_bounds() fallback (포맷 혼재 방어)
    """
    poco_obj.wait_for_appearance(timeout=timeout)
    W, H = _get_resolution()

    # region 기반 (가장 안정적: pos/size + 회전 후보 탐색 로직 포함)
    try:
        bbox = _get_region_from_poco(poco_obj, screen_w=W, screen_h=H, debug=debug)
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    except Exception:
        pass

    return (0, 0)

def _xy_from_template_center(tpl: Template, timeout: float = 5.0, debug: bool = False) -> tuple[int, int]:
    """
    Template 매칭 좌표를 px로 반환.
    wait()는 매칭 실패 시 예외가 나므로, 필요 시 try/except로 감싸서 사용.
    """
    pos = wait(tpl, timeout=timeout)  # (x,y) px
    if debug:
        step(f"[TEMPLATE] {get_label(tpl)}: {pos}")
    return (int(pos[0]), int(pos[1]))

# 객체 위치 해석
def _resolve_position(v, timeout: float = 5.0, debug: bool = False) -> tuple[int, int]:
        if v is None:
            raise ValueError("start/end는 필수입니다.")
        # (x,y) 직접 좌표
        if isinstance(v, (tuple, list)) and len(v) == 2:
            return (int(v[0]), int(v[1]))
        # Template
        if isinstance(v, Template):
            return _xy_from_template_center(v, timeout=timeout, debug=debug)
        # Poco object로 간주
        return _xy_from_poco_center(v, timeout=timeout, debug=debug)

# 시작/종료 좌표 드래그
def drag_any_to_any(
    *,
    start=None,          # poco_obj | (x,y) | Template
    end=None,            # poco_obj | (x,y) | Template
    duration: float = 0.5,
    timeout: float = 5.0,
    debug: bool = False,
) -> bool:
    """
    start/end에 poco 객체, (x,y) 좌표, Template을 섞어서 넣어도
    최종적으로 (px,px)로 통일해 swipe 수행.
    """
    x1, y1 = _resolve_position(start, timeout=timeout, debug=debug)
    x2, y2 = _resolve_position(end, timeout=timeout, debug=debug)

    if debug:
        step(f"[DRAG][any] ({x1},{y1}) -> ({x2},{y2}) dur={duration}")

    swipe((x1, y1), (x2, y2), duration=duration)
    time.sleep(0.2)
    return True

# --- MUST_DRAG ---
def must_drag(start_src, end_dst,   # poco_obj | (x,y) | Template
              desc: str = None, 
              *,
              timeout: float = 5,
              duration: float = 0.8,
              steps: int = 100,
              src_offset: tuple[int, int] = (0, 0), # 시작 소스 오프셋: (x,y)
              dst_offset: tuple[int, int] = (0, 0), # 종료 대상 오프셋: (x,y)
              env: Optional['QAEnv'] = None,
              debug: bool = False) -> bool:
    """
    필수 드래그(Drag&Drop):
      - start_src(시작 소스) 중심 → end_dst(타겟 소스) 중심으로 드래그
      - 실패 시: soft_fail + 예외 raise

    tips:
      - 드래그가 "끊기거나 한 칸만" 동작하면 steps/duration을 키우는 게 효과적
      - 드롭 타겟이 중앙보다 약간 위/아래를 요구하면 dst_offset으로 보정
    """
    env = use_env(env)

    try:
        sx, sy = _resolve_position(start_src, timeout=timeout, debug=debug)
        ex, ey = _resolve_position(end_dst, timeout=timeout, debug=debug)

        sx += int(src_offset[0]); sy += int(src_offset[1])
        ex += int(dst_offset[0]); ey += int(dst_offset[1])

        if debug:
            log(f"[MUST_DRAG] {start_src}({sx},{sy}) → {end_dst}({ex},{ey}) dur={duration} steps={steps}")

        # Airtest swipe의 steps 지원 여부가 환경에 따라 다를 수 있어 fallback 처리
        try:
            swipe((int(sx), int(sy)), (int(ex), int(ey)), duration=float(duration), steps=int(steps))
        except TypeError:
            swipe((int(sx), int(sy)), (int(ex), int(ey)), duration=float(duration))

        time.sleep(0.2)

        if desc:
            step(f"{desc}: PASS ✅")
        else:
            step(f"[MUST_DRAG] {get_label(start_src)}: PASS ✅")
        return True

    except PocoTargetTimeout:
        msg = f"{desc}: FAIL ❌ (timeout {timeout}s)" if desc else f"[MUST_DRAG] {get_label(start_src)}: FAIL ❌ (timeout {timeout}s)"
        soft_fail(msg)
        raise
    except Exception as e:
        msg = f"{desc}: FAIL ❌ ({e})" if desc else f"[MUST_DRAG] {get_label(start_src)}: FAIL ❌ ({e})"
        soft_fail(msg)
        raise

# 드래그 후 ROI 체크 함수
def try_drag_with_roi(start_src, end_dst,
                      desc: str = None,
                      *,
                      timeout: float = 5,
                      duration: float = 0.8,
                      steps: int = 80,
                      src_offset: tuple[int, int] = (0, 0),
                      dst_offset: tuple[int, int] = (0, 0),
                      post_sleep: float = 4,          # ✅ 애니메이션 대기
                      roi_point: str = "mid",           # ✅ ROI는 선의 중앙 기준이 보통 가장 안정적: "mid" | "dst" | "src"
                      roi_r: int = 150,                 # ✅ 선 영역 커버 (필요시 150~220)
                      mean_abs_thr: float = 2.0,        # ✅ 민감도 (필요시 1.5~4.0)
                      env: Optional['QAEnv'] = None,
                      debug: bool = False) -> bool:
    """
    드래그를 시도하고, 드래그 결과가 화면 ROI 변화로 '유효'했는지(True/False) 반환.
    - 선긋기처럼 "맞으면 선 유지/이펙트 유지" 케이스에서 사용.
    - 실패(오답)일 때 다시하기 버튼이 안 뜨는 상황에서도,
      각 시도 후 ROI가 원복되면 False로 보고 다음 후보를 시도할 수 있음.
    """
    env = use_env(env)

    try:
        sx, sy = _resolve_position(start_src, timeout=timeout, debug=debug)
        ex, ey = _resolve_position(end_dst, timeout=timeout, debug=debug)

        sx += int(src_offset[0]); sy += int(src_offset[1])
        ex += int(dst_offset[0]); ey += int(dst_offset[1])

        if roi_point == "src":
            cx, cy = int(sx), int(sy)
        elif roi_point == "dst":
            cx, cy = int(ex), int(ey)
        else:
            cx, cy = int((sx + ex) / 2), int((sy + ey) / 2)   # ✅ 기본: 선의 중앙

        before = G.DEVICE.snapshot()
        if before is None:
            if debug:
                log("[TRY_DRAG_ROI] before snapshot is None")
            return False

        if debug:
            log(f"[TRY_DRAG_ROI] {start_src}({sx},{sy}) → {end_dst}({ex},{ey}) "
                f"dur={duration} steps={steps} roi=({cx},{cy}, r={roi_r}) thr={mean_abs_thr}")

        # swipe steps 지원 여부 fallback
        try:
            swipe((int(sx), int(sy)), (int(ex), int(ey)), duration=float(duration), steps=int(steps))
        except TypeError:
            swipe((int(sx), int(sy)), (int(ex), int(ey)), duration=float(duration))

        time.sleep(float(post_sleep))  # ✅ 애니메이션 충분히 기다린 뒤 비교

        after = G.DEVICE.snapshot()
        if after is None:
            if debug:
                log("[TRY_DRAG_ROI] after snapshot is None")
            return False

        changed = _roi_changed(before, after, cx, cy, r=int(roi_r), mean_abs_thr=float(mean_abs_thr))

        if debug:
            log(f"[TRY_DRAG_ROI] changed={changed}")

        if desc:
            step(f"{desc}: {'PASS ✅' if changed else 'MISS ⚠️(roi)'}")
        return bool(changed)

    except Exception as e:
        if debug:
            step(f"[TRY_DRAG_ROI] exception: {e}", True)
        return False


# --- STEP BLOCK: 단계 블록 처리 공통 함수 ---
def step_block(func, desc="", debug: bool=False, env: Optional['QAEnv'] = None):
    env = use_env(env)
    if debug:
        step(f"🔻[BLOCK] {desc}: 시작 ▶️")
    try:
        func()              # 내부 세트 실행
        if debug:
            step(f"🔺[BLOCK] {desc}: PASS")
        else:
            step(f"{desc}: 성공")
        return True
    except Exception as e:
        if debug:
            step(f"🔺[BLOCK] {desc}: FAIL ({e})")
        else:
            step(f"{desc}: 실패 ({e})")
        raise

# --- SUB FLOW: 메인 플로우 내부의 서브 플로우 실행기 ---
def run_subflow(func: Callable[[], Any],
                desc: str = "",
                restart_sub: Optional[Callable[[], Any]] = None,
                debug: bool = False,
                env: Optional['QAEnv'] = None) -> bool:
    """
    메인 플로우 내 개별 서브 플로우 실행용 헬퍼.

    - func(env)를 호출한다.
    - 서브 플로우 내부에서 예외가 나도:
        - 여기서 FAIL 로그 + 스냅샷만 남기고
        - 예외는 밖으로 올리지 않는다 (return False).
    - 그래서 같은 메인 플로우 내 다음 서브 플로우는 계속 실행된다.
    """
    env = use_env(env)

    slice_path: Optional[str] = None
    pdf_path:   Optional[str] = None
    evcsv = None
    recent_path: Optional[str] = None  # 👈 추가
    iter_no = getattr(env, "_ctx_iter", None)
    flow_name = getattr(env, "_ctx_flow", None)

    if debug:
        step(f"🔽[SUB] Ct.{iter_no} - {flow_name} > {desc}", env=env)
    else:
        step(f"[SUB] Ct.{iter_no} - {flow_name} > {desc}", env=env)
    try:
        func()

        if debug:
            step(f"🔼[SUB] 성공: Ct.{iter_no} - {flow_name} > {desc}")
        return True
    except Exception as e:
        err_text = str(e)

        # 메인 플로우까지 죽이지 않고, 이 서브 플로우만 실패 처리
        if debug:
            # step(f"🔼[SUB] {desc}: 실패 ❌ ({e})", True)
            step(f"🔼[ERR] SubFlow 실패: Ct.{iter_no} - {flow_name} > {desc} - {err_text}", shot=True, env=env)
        else:
            # step(f"[SUB] {desc}: 실패 ❌ ({e})", True)
            step(f"[ERR] SubFlow 실패: Ct.{iter_no} - {flow_name} > {desc} - {err_text}", shot=True, env=env)
        try:
            if env._rm_proc is not None:
                if not slice_path:
                    slice_path = save_log(timeout=45)
                if not pdf_path:
                    pdf_path   = gen_report(timeout=60)
                # recent_path 추가 확보
                recent_path = find_latest_logcat_recent(env)  # 👈 추가
                evcsv = os.path.join(env.out_dir, "events.csv")
        except Exception as ee:
            step(f"[WARN] 산출물 확보 중 오류: {ee}", env=env)
            note(f"[RISK] 실패 증거 산출물 확보 중 오류(일부 첨부 누락 가능): {desc} ({ee})", env=env)

        # ② 실패 메일
        try:
            atts = [p for p in [recent_path, slice_path, pdf_path, evcsv] if p and os.path.exists(p)]

            send_mail_smtp(
                subject=f"❌ A-Test SubFlow 실패: {desc} ({env.package}_{env.serial or 'device'})",
                body=(f"SubFlow 실패: {desc}\n"
                    f"패키지: {env.package}\n결과 폴더: {env.out_dir}\n에러: {err_text}\n"
                    f"첨부: log recent / log slice / resource report / events.csv"),
                attachments=atts,
            )
            step(f"[SUB] 실패 메일 전송 완료: {desc}", env=env)
        except Exception as me:
            step(f"[WARN] 실패 메일 전송 실패: {me}", env=env)
        if restart_sub is not None:
            restart_sub()
        else:
            restart_app(env=env)
            env.on_ready()
        return False

def run_subflows(
                 *flows: Tuple[Callable[[], Any], str],
                 restart_sub: Optional[Callable[[], Any]] = None,
                 group_desc: Optional[str] = None,
                 debug: bool = False,
                 env: Optional['QAEnv'] = None
                 ) -> bool:
    """
    여러 서브 플로우를 순차 실행하고, 개별 결과 + 전체 결과까지 출력하는 헬퍼.

    사용 예:
        ok = run_subflows(
            (day1_reading_explore, "📋 [Basic Test] 1일차 > 독서 탐험"),
            (day1_ebook_viewer,    "📋 [Basic Test] 1일차 > e-Book 뷰어"),
            (day1_fluency1,        "📋 [Basic Test] 1일차 > 술술 읽기 훈련1"),
            restart_sub=restart_ebook,
            group_desc="그룹 이름",
        )

    - 각 튜플: (func, desc) 또는 (func, desc, restart_sub)
        * 3튜플은 이전 버전과의 호환을 위해 허용하며, 전달 시 우선 적용.
    - restart_sub 는 없으면 None 넣어도 되고, 서브 플로우 실패 시 호출할 콜백 함수.
      (개별 튜플에 콜백이 있으면 그 값을 우선 사용)
    - group_desc 는 전체 그룹 요약 로그에 사용할 설명 문자열.
    - 내부에서는 기존 run_subflow(...) 를 그대로 재사용한다.
    - 반환값:
        * True  : 모든 서브 플로우 PASS
        * False : 하나라도 FAIL
    - 로그:
        * 각 서브 플로우별 PASS/FAIL 로그는 run_subflow에서 출력
        * 마지막에 group_desc 기준으로 "ALL PASS" 또는 "일부 FAIL" 요약 출력
    """
    env = use_env(env)

    results: List[Tuple[str, bool]] = []

    # 그룹 요약용 라벨
    label = group_desc if group_desc else "서브 플로우 그룹"

    if debug:
        step(f"[SUB] {label}: 시작")

    for item in flows:
        # item 은 (func, desc) 또는 (func, desc, restart_sub) 를 허용 (구버전 호환)
        if len(item) == 2:
            func, desc = item
            item_restart = restart_sub
        elif len(item) == 3:
            func, desc, item_restart = item
        else:
            raise ValueError("run_subflows: 각 flow는 (func, desc) 또는 (func, desc, restart_sub) 형식이어야 합니다.")

        ok = run_subflow(func, desc=desc, restart_sub=item_restart, debug=debug, env=env)
        results.append((desc, ok))

    if not results:
        # 실행한 서브 플로우가 없으면 그냥 True
        return True

    all_ok = all(ok for _, ok in results)

    if all_ok:
        step(f"[SUB] {label}: 전체 성공")
        return True
    else:
        failed = [desc for desc, ok in results if not ok]
        failed_str = ", ".join(failed)
        step(f"[SUB] {label}: 일부 실패 ({failed_str})", True)
        return False
        # 🔥 메인 플로우까지 FAIL로 올리고 싶은 경우:
        # raise RuntimeError(f"{label}: 일부 서브 플로우 FAIL ({failed_str})")


# --- 클릭 루프: 대상이 사라질 때까지 클릭 후 폴백 클릭 ---
def click_until_disappear(target_poco, fallback_poco=None, desc="[CLICK_UNTIL] 루프", interval=0.5, max_loop=30, debug=False):
    """
    target_poco(예: 다음 버튼)가 존재하는 동안 계속 클릭하고,
    사라지면 fallback_poco(예: b버튼)를 1회 클릭하는 공통 루프 함수.
    ※ fallback_poco=None 이면 fallback 실행 없이 PASS 처리하고 종료.
    """
    loop = 0
    step(f"[CLICK_UNTIL] 루프 시작")

    while target_poco.exists():
        target_poco.click()
        loop += 1
        if debug:
            step(f"[CLICK_UNTIL] {loop}회 진행 ✅")
        time.sleep(interval)

        # ✨ 여기서 진짜로 없어지는지 한 번만 제대로 기다린다
        try:
            target_poco.wait_for_disappearance(timeout=2)
            # 여기까지 오면 진짜 사라진 거니까 fallback
            step(f"[CLICK_UNTIL] {loop}회 클릭 후 대상이 실제로 사라짐")

            if fallback_poco is None:
                step(f"{desc}: PASS ✅ (fallback 없음)",)
                break

            if fallback_poco.exists():
                fallback_poco.click()
                step(f"{desc}: PASS ✅")
            else:
                soft_fail(f"{desc}: FAIL ❌ (fallback 미존재)")
            break
        except PocoTargetTimeout:
            # 2초 동안 안 사라졌으니까 “아직 있다고 본다” → 루프 계속
            pass

        if loop >= max_loop:
            step(f"[click] 최대 {max_loop}회 진행 후 강제 종료 ⚠️")
            if fallback_poco.exists():
                fallback_poco.click()
                step(f"{desc}: PASS ✅ (max_loop 이후)")
            break

    step(f"[click] 루프 종료")

# 리소스 모니터 GUI 스크립트 경로 찾기
def _find_resource_monitor_gui(script_dir: str) -> Optional[str]:
    # 1) 고정 파일명 우선
    cand = os.path.join(script_dir, "resource_monitor_gui.py")
    if os.path.exists(cand):
        return cand
    # 2) 타임스탬프 버전 중 최신
    files = glob.glob(os.path.join(script_dir, "resource_monitor_gui_*.py"))
    if files:
        # 파일명 끝의 타임스탬프 기준 역정렬
        files.sort(reverse=True)
        return files[0]
    return None

# 외부 Python 실행 파일 선택 (환경변수 우선, py-launcher 활용, 현재 fallback)
def _pick_ext_python():
    # 1) 환경변수 우선
    p = os.environ.get("QA_PYTHON")
    if p and os.path.exists(p): 
        return p
    # 2) Windows py-launcher로 3.10+ 우선 탐색
    for v in ("3.11", "3.10", "3.12", "3.9", "3.8"):
        try:
            exe = subprocess.check_output(
                ["py", f"-{v}", "-c", "import sys;print(sys.executable)"],
                encoding="utf-8", errors="ignore"
            ).strip()
            if exe and os.path.exists(exe):
                return exe
        except Exception:
            pass
    # 3) fallback
    return shutil.which("python") or sys.executable  # 최후: 현재라도

# 리소스 모니터 시작: save.flag/report.flag + 산출물 감시(닫힘 확인 포함)
def start_resource_monitor(env: Optional['QAEnv'] = None):
    env = use_env(env)

    gui = _find_resource_monitor_gui(env.script_dir)
    if not gui:
        step(f"[ERR] resource_monitor_gui*.py 없음: {env.script_dir}", env=env)
        raise FileNotFoundError("resource_monitor_gui*.py")

    py = _pick_ext_python()

    # 기존 env에 RESULT_DIR/ADB_SERIAL 등을 얹되,
    # ⬇ AirtestIDE용 TCL/TK 환경변수는 서브프로세스에서 제거
    env_map = adb_env(env).copy()
    for k in ("TCL_LIBRARY", "TK_LIBRARY"):
        if k in env_map:
            env_map.pop(k)

    # GUI/도구들이 동일 기준(SCRIPT_DIR)으로 result를 잡게끔
    env_map["QA_SCRIPT"] = env.script_dir

    # PATH에서 AirtestIDE\tcl,\tk 조각 제거
    def _clean_path(path):
        parts = [p for p in (path or "").split(";")
                 if not p.lower().endswith("\\airtestide\\tcl")
                 and not p.lower().endswith("\\airtestide\\tk")]
        return ";".join(parts)
    env_map["PATH"] = _clean_path(os.environ.get("PATH",""))

    args = [
        # ⬇ cmd 창 유지
        # "cmd", "/k", "call",
        py, "-u", gui,
        (env.package or ""), (env.serial or ""), "--auto",
        # ✅ 결과 폴더 기준 통일: Run 모드든 단독 모드든 env.out_dir 기준으로 플래그/산출물 일치
        "--out-dir", env.out_dir
    ]

    # (선택) ENV로도 내려주면, GUI가 ENV를 읽는 구조여도 호환됨
    env_map["RESULT_DIR"] = env.out_dir

    # 리소스 모니터는 자체 GUI 창과 로그 뷰를 가지므로 별도 콘솔이 필요 없다
    # (콘솔을 다시 보려면 CREATE_NEW_CONSOLE로 되돌리면 된다)
    creation = 0x08000000  # CREATE_NO_WINDOW
    env._rm_proc = subprocess.Popen(
        args,
        creationflags=creation,
        cwd=env.script_dir,
        env=env_map
    )
    with open(os.path.join(env.out_dir, "resource_monitor.pid"), "w", encoding="utf-8") as f:
        f.write(str(env._rm_proc.pid))

    step("🖥️ GUI 리소스 모니터링 시작", env=env)
    time.sleep(2.0)
    return env._rm_proc.pid

# Windows에서 파일이 닫힐 때까지 대기
def _wait_file_closed_windows(path: str, max_wait: int) -> bool:
    try:
        GENERIC_READ=0x80000000; SHARE_NONE=0; OPEN_EXISTING=3; NORMAL=0x80; INVALID=ctypes.c_void_p(-1).value
        CreateFileW=ctypes.windll.kernel32.CreateFileW; CloseHandle=ctypes.windll.kernel32.CloseHandle
        CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        CreateFileW.restype=wintypes.HANDLE
        deadline=time.time()+max_wait
        while time.time()<deadline:
            h=CreateFileW(path, GENERIC_READ, SHARE_NONE, None, OPEN_EXISTING, NORMAL, None)
            if h!=INVALID and h is not None: CloseHandle(h); return True
            time.sleep(0.5)
        return False
    except: return False

# save.flag 생성 및 로그캣 슬라이스 감시
def save_log(timeout:int=60, env: Optional['QAEnv'] = None) -> Optional[str]:
    env = use_env(env)

    flag = os.path.join(env.out_dir, "save.flag")
    with open(flag,"w",encoding="utf-8") as f: f.write(str(time.time()))
    step(f"[OK] save.flag: {flag}", env=env)
    t0=time.time(); deadline=t0+timeout; target=None
    while time.time()<deadline and not target:
        for n in os.listdir(env.out_dir):
            if n.startswith("logcat_slice_") and n.endswith(".txt"):
                p=os.path.join(env.out_dir,n)
                if os.path.getmtime(p)>=t0: target=p; break
        time.sleep(0.5)
    if not target: step("[ERR] timeout: slice 미감지", env=env); return None
    _wait_file_closed_windows(target, 15); time.sleep(5)
    step(f"[OK] slice 준비 완료: {target}", env=env); return target

# report.flag 생성 및 리포트 생성 체크
def gen_report(timeout:int=60, env: Optional['QAEnv'] = None) -> Optional[str]:
    env = use_env(env)

    flag = os.path.join(env.out_dir, "report.flag")
    with open(flag,"w",encoding="utf-8") as f: f.write(str(time.time()))
    step(f"[OK] report.flag: {flag}", env=env)
    t0=time.time(); deadline=t0+timeout; pdf=None
    while time.time()<deadline and not pdf:
        for n in os.listdir(env.out_dir):
            if n.startswith("resource_report_") and n.endswith(".pdf"):
                p=os.path.join(env.out_dir,n)
                if os.path.getmtime(p)>=t0: pdf=p; break
        time.sleep(0.5)
    if not pdf: step("[ERR] timeout: report 미감지", env=env); return None
    _wait_file_closed_windows(pdf, 25); time.sleep(10)
    step(f"[OK] resource 리포트 생성 완료: {pdf}", env=env); return pdf

# rolling 로그 정리
def cleanup_rolling_logs(out_dir: str, *, env: Optional['QAEnv'] = None,
                         keep_latest: bool = False, max_wait: int = 15) -> int:
    """
    결과 폴더의 rolling_*.log 삭제 (산출물 용량 절감용)
    - keep_latest=True면 가장 최신 1개는 남김
    - Windows 잠금 대비: 삭제 전 파일 닫힘 대기
    """
    env = use_env(env)

    if not out_dir or (not os.path.isdir(out_dir)):
        return 0

    try:
        targets = [
            os.path.join(out_dir, n)
            for n in os.listdir(out_dir)
            if n.startswith("rolling_") and n.endswith(".log")
        ]
    except Exception:
        return 0

    if not targets:
        return 0

    # 최신순 정렬(keep_latest 옵션용)
    try:
        targets.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except Exception:
        pass

    if keep_latest and len(targets) > 0:
        targets = targets[1:]

    removed = 0
    for p in targets:
        try:
            _wait_file_closed_windows(p, max_wait)
        except Exception:
            pass

        try:
            os.remove(p)
            removed += 1
        except FileNotFoundError:
            pass
        except PermissionError:
            # 잠금이 길게 남는 케이스 폴백: rename 후 재시도
            try:
                tmp = p + ".del"
                os.replace(p, tmp)
                _wait_file_closed_windows(tmp, max_wait)
                os.remove(tmp)
                removed += 1
            except Exception:
                pass
        except Exception:
            pass

    if removed:
        step(f"🧹 rolling 로그 정리: {removed}개 삭제", env=env)
    return removed

# 리소스 모니터링 종료
def stop_resource_monitor(env: Optional['QAEnv'] = None):
    """
    ⬅️ 유지/보강: stop.flag 생성 → GUI/event_tap 정상 종료 유도
    - GUI 창이 떠 있으면 process tree 종료(taskkill /T /F) 폴백
    """
    env = use_env(env)

    # 1) 정상 종료 유도: stop.flag
    try:
        open(os.path.join(env.out_dir, "stop.flag"), "w", encoding="utf-8").write("stop")
    except Exception:
        pass
    time.sleep(0.6)

    # 2) PID 확인
    pid = None
    if env._rm_proc and (env._rm_proc.poll() is None):
        pid = env._rm_proc.pid
    else:
        pf = os.path.join(env.out_dir, "resource_monitor.pid")
        if os.path.exists(pf):
            try:
                pid = int(open(pf, encoding="utf-8").read().strip())
            except Exception:
                pid = None

    # 3) 폴백 강제 종료(창 닫힘/하위 프로세스 포함)
    if pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    env._rm_proc = None
    step("⛔ GUI 리소스 모니터링 종료", env=env)

# 요소 가시성/활성화 체크(스크롤 용도)
def is_visible(el) -> bool:
    """
    요소의 화면 내 가시성 판정
    - exists()가 False면 무조건 False
    - get_position / get_size 가 이상하면:
      → center(x,y)가 0~1 안에만 있으면 True로 간주 (구 Unity/Native 보호)
    - 교차 비율 임계값도 5% → 1%로 완화
    """
    if not el.exists():
        return False

    try:
        x, y = el.get_position()   # center (0~1)
        w, h = el.get_size()       # size   (0~1)
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False

        # 기본값 보정
        w = float(w or 0.0)
        h = float(h or 0.0)

        # 사이즈 정보가 거의 없으면: center가 화면 안이면 보이는 걸로 처리
        if w <= 0.0 or h <= 0.0:
            return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

        x1, y1 = x - w / 2.0, y - h / 2.0
        x2, y2 = x + w / 2.0, y + h / 2.0

        # 화면(0~1)과 겹치는 비율 체크 (임계값 1%)
        overlap_x = min(x2, 1.0) - max(x1, 0.0)
        overlap_y = min(y2, 1.0) - max(y1, 0.0)
        ox = overlap_x > 0.01
        oy = overlap_y > 0.01
        if not (ox and oy):
            return False
    except Exception:
        # 위치/사이즈 조회에서 에러 날 경우 보수적으로 False
        return False

    # Unity visible 플래그는 참고용 (False면 숨김)
    try:
        vis = el.attr("visible")
        if isinstance(vis, bool) and not vis:
            return False
    except Exception:
        pass

    return True


def is_enabled(el) -> bool:
    """
    요소의 활성화 상태 체크
    - Android Native: enabled 속성 반환
    - Unity: enabled가 없을 수 있음 → 기본 True 처리
    """
    try:
        v = el.attr("enabled")
        if isinstance(v, bool):
            return v
    except Exception:
        pass
    return True   # 속성이 없으면 True로 간주

# 환경변수에서 메일 설정 읽기
def mail_env(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and str(v).strip()!="") else default

def _split_emails(s: str):
    # 콤마/세미콜론 모두 허용
    return [x.strip() for x in re.split(r"[;,]", s or "") if x.strip()]

# ------------------------------
# Google Drive Upload Helpers
# ------------------------------
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def _env_bool(name: str, default: bool=False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _zip_any(path: str) -> str:
    """
    path가 폴더면 zip으로 묶고, 파일이면 그대로 반환.
    반환: 업로드할 파일 경로
    """
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return path

    base = os.path.basename(path.rstrip("\\/"))
    parent = os.path.dirname(path.rstrip("\\/"))
    zip_path = os.path.join(parent, f"{base}.zip")

    # 기존 zip 있으면 덮어쓰기
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass

    import zipfile
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, path)
                z.write(fp, arcname=os.path.join(base, rel))
    return zip_path

def _get_drive_service():
    """
    QA_GDRIVE_CREDENTIALS / QA_GDRIVE_TOKEN 기반으로 Drive service 생성.
    최초 1회는 브라우저 OAuth 승인 필요(InstalledAppFlow).
    """
    env = use_env()
    if not env.gdrive_enable:
        return None

    cred_path = os.environ.get("QA_GDRIVE_CREDENTIALS", "").strip()
    token_path = os.environ.get("QA_GDRIVE_TOKEN", "").strip()

    if not cred_path or not os.path.exists(cred_path):
        raise RuntimeError(f"[GDRIVE] QA_GDRIVE_CREDENTIALS 누락 또는 파일 없음: {cred_path}")
    if not token_path:
        # 토큰 경로 없으면 credentials와 같은 폴더에 token.json 기본 생성
        token_path = os.path.join(os.path.dirname(os.path.abspath(cred_path)), "token.json")

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, _DRIVE_SCOPES)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(cred_path, _DRIVE_SCOPES)
        # 로컬 PC 설치형: 콘솔 플로우
        creds = flow.run_local_server(port=0)
    # 토큰 저장
    try:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    except Exception:
        pass

    return build("drive", "v3", credentials=creds)

def _drive_set_permission_anyone(service, file_id: str):
    """
    링크 공개(정책상 필요시)
    """
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id"
        ).execute()
    except Exception:
        pass

def drive_upload(path: str, *, folder_id: Optional[str]=None, make_anyone: bool=False) -> str:
    """
    파일/폴더 업로드 후 webViewLink 반환
    """
    service = _get_drive_service()
    if service is None:
        # ✅ Drive 비활성화면 예외로 막지 말고, 알림만 남기고 스킵
        try:
            step("[GDRIVE] 비활성화(GDRIVE_ENABLE=False) → 업로드 스킵")
        except Exception:
            pass
        return None

    upload_path = _zip_any(path)  # 폴더면 zip
    fname = os.path.basename(upload_path)

    meta = {"name": fname}
    if folder_id:
        meta["parents"] = [folder_id]

    media = MediaFileUpload(upload_path, resumable=True)
    created = service.files().create(
        body=meta,
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    file_id = created.get("id", "")
    link = created.get("webViewLink", "")

    if make_anyone and file_id:
        _drive_set_permission_anyone(service, file_id)
        # 권한 바꾼 뒤에도 webViewLink는 동일하지만 안전하게 재조회
        try:
            g = service.files().get(fileId=file_id, fields="webViewLink").execute()
            link = g.get("webViewLink", link)
        except Exception:
            pass

    if not link:
        raise RuntimeError("[GDRIVE] 업로드는 됐는데 webViewLink를 받지 못함")

    return link

# SMTP로 메일 발송
def send_mail_smtp(subject: str, body: str, attachments: list=None, *,
                   body_html: Optional[str] = None,
                   to: Optional[Union[str, List[str]]] = None,
                   cc: Optional[Union[str, List[str]]] = None,
                   bcc: Optional[Union[str, List[str]]] = None):
    """
    수신자 우선순위: to 인자 -> QA_MAIL_TO 환경변수
    환경변수:
      QA_MAIL_USER : SMTP 로그인 아이디(발신 주소)
      QA_MAIL_PASS : SMTP 비밀번호(또는 앱비밀번호)
      QA_MAIL_TO   : 수신자 콤마/세미콜론구분 (예: a@b.com,c@d.com or a@b.com;c@d.com)
      QA_MAIL_SMTP : 호스트:포트 (기본 smtp.gmail.com:465, SSL)
    """
    env = use_env()

    user = mail_env("QA_MAIL_USER")
    pwd  = mail_env("QA_MAIL_PASS")
    hostport = mail_env("QA_MAIL_SMTP","smtp.gmail.com:465")

    # 수신자 결정(오버라이드 가능)
    if isinstance(to, str):   tos = _split_emails(to)
    elif isinstance(to, list): tos = to
    else:                      tos = _split_emails(mail_env("QA_MAIL_TO",""))

    if isinstance(cc, str):    ccs = _split_emails(cc)
    elif isinstance(cc, list): ccs = cc
    else:                      ccs = _split_emails(mail_env("QA_MAIL_CC",""))

    if isinstance(bcc, str):    bccs = _split_emails(bcc)
    elif isinstance(bcc, list): bccs = bcc
    else:                       bccs = _split_emails(mail_env("QA_MAIL_BCC",""))

    if not (user and pwd and tos):
        raise RuntimeError("메일 환경변수(QA_MAIL_USER/QA_MAIL_PASS/QA_MAIL_TO) 미설정")

    host, port = hostport.split(":")
    port = int(port)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(tos)
    if ccs: msg["Cc"] = ", ".join(ccs)
    msg.set_content(body)  # plain text (fallback)

    # ------------------------------
    # attachments 정규화: 폴더는 항상 ZIP으로 변환해서 첨부/업로드 대상으로 사용
    # ------------------------------
    norm_attachments = []
    for p in (attachments or []):
        if not p:
            continue
        if not os.path.exists(p):
            continue
        try:
            if os.path.isdir(p):
                norm_attachments.append(_zip_any(p))  # ✅ 폴더면 zip 생성
            else:
                norm_attachments.append(p)            # 파일이면 그대로
        except Exception:
            # zip 실패하면 원본을 넣어두되, 뒤에서 attach_error로 떨어지게 둠
            norm_attachments.append(p)

    attachments = norm_attachments

    # ------------------------------
    # (옵션2) 첨부 용량 초과 시 Google Drive 업로드 후 링크로 대체
    # ------------------------------
    max_mb = env.mail_max_attach
    max_bytes = max_mb * 1024 * 1024

    gdrive_enabled = env.gdrive_enable
    folder_id = env.gdrive_folder_id
    share_anyone = env.gdrive_share_anyone

    # 첨부 전체 용량 계산(존재하는 파일만)
    att_paths = []
    total_size = 0
    for p in (attachments or []):
        if not p:
            continue
        if os.path.exists(p):
            att_paths.append(p)
            if os.path.isfile(p):
                try:
                    total_size += os.path.getsize(p)
                except Exception:
                    pass
            else:
                # 폴더는 zip 후 크기 계산(대략; 업로드 단계에서 zip 생성)
                # 여기서는 초과판단만 필요하므로 0으로 두고, 폴더가 있으면 보수적으로 초과로 간주할 수도 있음
                # -> 폴더가 있으면 zip 생성 후 정확히 계산하도록 처리
                try:
                    z = _zip_any(p)
                    total_size += os.path.getsize(z)
                except Exception:
                    # zip 실패 시, 일단 초과로 몰아 Drive로 보냄
                    total_size = max_bytes + 1

    drive_links = []
    if gdrive_enabled and att_paths and total_size > max_bytes:
        # 첨부를 Drive로 올리고 링크만 남김
        for p in att_paths:
            try:
                link = drive_upload(p, folder_id=folder_id, make_anyone=share_anyone)
                drive_links.append((os.path.basename(p), link))
            except Exception as e:
                drive_links.append((os.path.basename(p), f"[UPLOAD_FAIL] {e}"))

        # 본문에 링크 섹션 삽입
        if drive_links:
            lines = ["", f"[Drive 링크] (첨부 용량 {max_mb}MB 초과로 링크로 대체됨)"]
            for name0, link0 in drive_links:
                lines.append(f"- {name0}: {link0}")
            body = body + "\n" + "\n".join(lines)

            # HTML 본문이면 HTML에도 링크 반영
            if body_html:
                html_lines = [f"<hr><h3>Drive 링크 (첨부 용량 {max_mb}MB 초과로 링크로 대체됨)</h3><ul>"]
                for name0, link0 in drive_links:
                    if str(link0).startswith("http"):
                        html_lines.append(f'<li>{name0}: <a href="{link0}">{link0}</a></li>')
                    else:
                        html_lines.append(f"<li>{name0}: {link0}</li>")
                html_lines.append("</ul>")
                body_html = body_html + "\n" + "\n".join(html_lines)

        # 실제 첨부는 제거(메일 크기 줄임)
        attachments = []

        msg.set_content(body)

    # ✅ HTML 본문 지원: 메일 내용 = summary.html
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    for p in (attachments or []):
        try:
            if not p or not os.path.exists(p): continue
            ctype, encoding = mimetypes.guess_type(p)
            if ctype is None: ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/",1)
            with open(p, "rb") as f:
                msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                                   filename=os.path.basename(p))
        except Exception as e:
            # 첨부 실패는 본문에만 기록하고 진행
            msg.add_attachment(str(e).encode("utf-8"),
                               maintype="text", subtype="plain",
                               filename=f"attach_error_{os.path.basename(p)}.txt")

    # SSL 고정 (465). 587(TLS) 쓰려면 SMTP.starttls()로 변환하면 됨.
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(user, pwd)
        s.send_message(msg, to_addrs=tos + ccs + bccs)

# 최근 logcat_recent_*.txt 파일 경로 찾기
def find_latest_logcat_recent(env: Optional['QAEnv'] = None) -> Optional[str]:
    """
    RESULT_DIR(env.out_dir)에서 가장 최신의 logcat_recent_*.txt 하나를 반환.
    (pkg/pid 미필터 전체 로그 파일 네이밍 전제)
    """
    env = use_env(env)
    
    # YYMMDD_hhmm 형식에 맞는 정규표현식 패턴
    # 예: logcat_recent_250910_1730.txt
    pattern = re.compile(r"^logcat_recent_\d{6}_\d{4}\.txt$")

    try:
        candidates = []
        for n in os.listdir(env.out_dir):
            # 예: logcat_recent_250910-1730.txt
            if pattern.match(n):
                p = os.path.join(env.out_dir, n)
                try:
                    mtime = os.path.getmtime(p)
                except Exception:
                    mtime = 0
                candidates.append((mtime, p))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]
    except Exception:
        return None

# 공통 플로우 실행 래퍼
def run_flow(
    flow_fn: Callable, *,
    name: str, iter_no: int,
    env: Optional['QAEnv'] = None,
    on_ready: Optional[Callable[[], None]] = None,
    send_mail_on_success: bool = False,
    stop_on_fail: bool = False,
    # ✅ 추가: 수신자 오버라이드
    mail_to: Optional[Union[str, List[str]]] = None,
    mail_cc: Optional[Union[str, List[str]]] = None,
    mail_bcc: Optional[Union[str, List[str]]] = None,
    debug: bool = False,
) -> Tuple[bool, object, object, Dict[str, Optional[str]], Optional[str]]:
    """
    단일 플로우 1회 실행.
    return: (ok, poco, artifacts, err_text)
      - ok: 성공 True / 실패 False
      - poco: (실패 재시작 시) 갱신된 UnityPoco
      - artifacts: {"slice": <path or None>, "pdf": <path or None>}
      - err_text: 실패 시 에러 문자열
    실패 시: 즉시 스냅샷 + save_log/gen_report + 실패 메일 → 앱 재시작 → on_ready 대기 → poco 갱신
    """
    env = env or QAEnv()

    slice_path: Optional[str] = None
    pdf_path:   Optional[str] = None
    evcsv = None
    recent_path: Optional[str] = None  # 👈 추가

    # env 기본값 → 인자로 override 가능
    on_ready = on_ready or env.on_ready

    try:
        step(f"[RUN] Ct.{iter_no} - {name}", env=env)
        flow_fn()

        if debug:
            step(f"[RUN] 성공: Ct.{iter_no} - {name}", env=env)

        # 성공 시: (선택) 메일 + 산출물
        if send_mail_on_success:
            try:
                if env._rm_proc is not None:
                    slice_path = save_log(timeout=45)
                    pdf_path   = gen_report(timeout=60)
                    recent_path = find_latest_logcat_recent(env)  # 👈 추가

                send_mail_smtp(
                    subject=f"✅ A-Test Flow 성공: {name} (#{iter_no}) - {env.package}_{env.serial or 'device'}",
                    body=(f"{name} (#{iter_no}) 성공\n"
                          f"패키지: {env.package}\n결과 폴더: {env.out_dir}\n"
                          f"첨부: log recent / log slice / resource report"),  # 👈 수정
                    attachments=[p for p in [recent_path, slice_path, pdf_path] if p],
                    # ✅ 전달
                    to=mail_to, cc=mail_cc, bcc=mail_bcc
                )

                step(f"[RUN] 성공 메일/산출물 처리 완료: Ct.{iter_no} - {name}", env=env)
            except Exception as me:
                step(f"[WARN] 성공 메일/산출물 처리 실패: {me}", env=env)
                note(f"[RECOVERY] 성공은 했지만 산출물/메일 처리 실패: {name} #{iter_no} ({me})", env=env)

        return True, env.apoco, env.poco, {"recent": recent_path, "slice": slice_path, "pdf": pdf_path}, None

    except Exception as e:
        err_text = str(e)

        if not stop_on_fail:
            # ① 즉시 증거 확보
            step(f"[ERR] Flow 실패: Ct.{iter_no} - {name} - {err_text}", shot=True, env=env)
            try:
                if env._rm_proc is not None:
                    if not slice_path:
                        slice_path = save_log(timeout=45)
                    if not pdf_path:
                        pdf_path   = gen_report(timeout=60)
                    # recent_path 추가 확보
                    recent_path = find_latest_logcat_recent(env)  # 👈 추가
                    evcsv = os.path.join(env.out_dir, "events.csv")
            except Exception as ee:
                step(f"[WARN] 산출물 확보 중 오류: {ee}", env=env)
                note(f"[RISK] 실패 증거 산출물 확보 중 오류(일부 첨부 누락 가능): {name} #{iter_no} ({ee})", env=env)

            # ② 실패 메일
            try:
                atts = [p for p in [recent_path, slice_path, pdf_path, evcsv] if p and os.path.exists(p)]

                send_mail_smtp(
                    subject=f"❌ A-Test Flow 실패: {name} (#{iter_no}) - {env.package}_{env.serial or 'device'}",
                    body=(f"Flow 실패: {name} (#{iter_no})\n"
                        f"패키지: {env.package}\n결과 폴더: {env.out_dir}\n에러: {err_text}\n"
                        f"첨부: log recent / log slice / resource report / events.csv"),
                    attachments=atts,
                    # ✅ 전달
                    to=mail_to, cc=mail_cc, bcc=mail_bcc
                )
                step(f"[RUN] 실패 메일 전송 완료: {name} (#{iter_no})", env=env)
            except Exception as me:
                step(f"[WARN] 실패 메일 전송 실패: {me}", env=env)

            # ③ 앱 재시작 / 혹은 Poco 하드 리셋 → on_ready 대기
            try:
                # 🔸 환경계 에러 패턴이면 하드 리셋 우선
                fatal_keywords = (
                    "socket connection broken",
                    "RemoteDisconnected",
                    "Process crashed",
                    "uiautomation",
                    "instrumentation test server process is no longer alive",
                )
                if any(k in err_text for k in fatal_keywords):
                    step("[RUN] 환경 문제로 판단 → Poco 하드 리셋 시도", env=env)
                    note(f"[RECOVERY] 환경 문제로 판단되어 Poco 하드 리셋 수행: {name} #{iter_no}", env=env)
                    try:
                        poco_hard_reset(env, reason=f"run_flow 실패: {err_text}")
                    except PocoFatalError as fe:
                        step(f"[RUN] FATAL Poco 하드 리셋 실패: {fe}", env=env, shot=True)
                        note(f"[RISK] Poco 하드 리셋 실패(불안정 지속 가능): {name} #{iter_no}", env=env)
                else:
                    # 일반적인 FAIL이면 기존처럼 앱만 재시작
                    restart_app(env=env)
                    try:
                        if callable(on_ready):
                            on_ready()
                    except Exception as we:
                        step(f"[WARN] 재시작 후 대기(on_ready) 실패: {we}", env=env)
                        note(f"[RISK] 재시작 후 on_ready 실패(다음 플로우 영향 가능): {we}", env=env)

            except Exception as re:
                step(f"[WARN] 재시작/하드리셋 처리 중 예외: {re}", env=env)

        return False, env.apoco, env.poco, {"recent": recent_path, "slice": slice_path, "pdf": pdf_path}, err_text


def run_flows(
    flows: List[Tuple[str, Callable]], *,
    repeat: int,
    env: Optional['QAEnv'] = None,
    on_ready: Optional[Callable[[], None]] = None,             # 앱별 준비 콜백
    on_close: Optional[Callable[[], None]] = None,             # 앱별 종료 콜백
    send_success_mail_each: bool = False,
    stop_on_fail: bool = False,   # ✅ 추가
    # ✅ 추가: 기본 수신자 오버라이드(전체 루프 공통)
    mail_to: Optional[Union[str, List[str]]] = None,
    mail_cc: Optional[Union[str, List[str]]] = None,
    mail_bcc: Optional[Union[str, List[str]]] = None,
) -> Dict[str, object]:
    """
    여러 플로우를 repeat 횟수만큼 순차 실행.
    - 실패 시: run_flow()에서 즉시 메일 발송, 루프는 계속
    - 종료 시: 최종 요약 메일(실패 합계/목록) 1회 발송
    return summary: {
      "total_fail": int,
      "fail_logs": List[Tuple[int, str, str]],  # (iter_no, flow_name, err_text)
      "final_slice": str or None,
      "final_pdf": str or None,
      "final_recent": str or None  # 👈 추가
    }
    """
    env = use_env(env)

    # env 기본값 → 인자로 override 가능
    on_close = on_close or env.on_close

    stop_all = False  # ✅ 추가

    for i in range(1, repeat+1):
        step(f"[=]===== 반복 {i} 시작 =====", env=env)
        for name, fn in flows:
            # ✅ 현재 컨텍스트(서브플로우 로그가 이 값을 참조)
            env._ctx_iter = i
            env._ctx_flow = name

            ok, a, u, arts, err = run_flow(
                fn, name=name, iter_no=i,
                env=env,
                on_ready=on_ready,
                send_mail_on_success=send_success_mail_each,
                stop_on_fail=stop_on_fail,
                # ✅ 전달
                mail_to=mail_to, mail_cc=mail_cc, mail_bcc=mail_bcc
            )
            if not ok and stop_on_fail:  # ✅ 추가: 즉시 전체 루프 중단
                step(f"[=]===== 반복 {i} 중단 =====", env=env)
                step(f"[WARN] stop_on_fail=True → 실패 감지로 플로우 중단: iter={i}, flow={name}", env=env)
                stop_all = True
                break

            # Poco 갱신
            env.apoco = a
            env.poco  = u
        
        if stop_all:  # ✅ outer loop 탈출
            break

    step(f"[=]===== 모든 반복 종료 =====", env=env)
    # --- 전체 결과 요약 출력 ---
    if env.total_fail == 0:
        step(
            f"✅ A-Test 최종 성공 ({repeat}회 무오류) - {env.package}_{env.serial or 'device'}",
            env
        )
    else:
        step(
            f"⚠️ A-Test 최종 완료(실패 {env.total_fail}건) - {env.package}_{env.serial or 'device'}",
            env
        )

    if on_close is not None:
        try:
            on_close()
        except Exception:
            pass

    # 최종 산출물 + 요약 메일
    final_slice = None
    final_pdf   = None
    final_recent = None
    evcsv       = None
    if env._rm_proc is not None:
        final_slice = save_log(timeout=60)
        final_pdf   = gen_report(timeout=60)
        final_recent = find_latest_logcat_recent(env)   # 👈 추가
        evcsv       = os.path.join(env.out_dir, "events.csv")
    html_rep    = None

    # Airtest 리포트 생성 (✅ 메일 첨부 기본 제외 / ✅ Drive 링크 기본)
    airtest_index_html = None
    airtest_drive_link = None

    try:
        script_path = env.airtest_script
        log_dir     = env.airtest_log_dir

        if script_path and log_dir:

            ts = time.strftime("%y%m%d_%H%M")
            portable_dir, index_html = build_portable_airtest_report(
                script_path=script_path,
                log_dir=log_dir,
                out_dir=env.run_dir,   # ✅ Run 폴더 안에 포터블 번들 생성
                ts=ts
            )
            airtest_index_html = index_html

            step(f"[OK] Portable Airtest 리포트 생성 완료: {index_html}", env=env)

            # ✅ 포터블 번들에 필요한 로그/스크린샷을 모두 복사했으면 원본 airtest_log 폴더는 제거
            try:
                # portable_dir 안에 airtest_log가 존재하면(복사 완료 신호) 원본 log_dir 삭제
                bundled_log = os.path.join(portable_dir, "airtest_log")
                if os.path.isdir(bundled_log) and os.path.isdir(log_dir):
                    shutil.rmtree(log_dir, ignore_errors=True)
                    step(f"[OK] 원본 airtest_log 폴더 삭제 완료: {log_dir}", env=env)
            except Exception as e:
                step(f"[WARN] 원본 airtest_log 폴더 삭제 실패: {e}", env=env)

            if env.gdrive_enable:
                # ✅ 포터블 번들을 zip으로 묶어서 Drive 업로드 (메일 첨부는 하지 않음)
                try:
                    zip_path = _zip_any(portable_dir)

                    # credentials/token 경로가 환경변수에 없으면 qa_common/_secrets 기본 경로로 가정
                    # common.py 위치: ...\Tools\qa_common\common.py 라는 전제
                    common_dir = Path(__file__).resolve().parent  # ...\Tools\qa_common
                    secrets_dir = common_dir / "_secrets"

                    os.environ.setdefault("QA_GDRIVE_CREDENTIALS", str(secrets_dir / "gdrive_credentials.json"))
                    os.environ.setdefault("QA_GDRIVE_TOKEN",       str(secrets_dir / "gdrive_token.json"))

                    folder_id = env.gdrive_folder_id
                    share_anyone = env.gdrive_share_anyone

                    airtest_drive_link = drive_upload(zip_path, folder_id=folder_id, make_anyone=share_anyone)

                    if airtest_drive_link:
                        step(f"[OK] Airtest 포터블 리포트 Drive 업로드 완료: {airtest_drive_link}", env=env)

                    else:
                        step("[GDRIVE] 업로드 스킵/실패 → 링크 없음", env=env)

                    # ✅ 업로드 종료 후 zip은 즉시 정리(메일은 링크만 사용)
                    try:
                        if os.path.isfile(zip_path):
                            os.remove(zip_path)
                            step(f"[OK] Airtest 포터블 ZIP 삭제 완료(업로드 후): {zip_path}", env=env)
                    except Exception as e:
                        step(f"[WARN] Airtest 포터블 ZIP 삭제 실패: {e}", env=env)

                except Exception as e:
                    step(f"[WARN] Airtest 포터블 리포트 Drive 업로드 실패: {e}", env=env)

            # env에 저장(메일 본문/summary에서 사용)
            try:
                env.airtest_report_link = airtest_drive_link
            except Exception:
                pass

            # ✅ 메일 첨부 대상(html_rep)에는 넣지 않음
            html_rep = None

    except Exception:
        pass

    # ✅ Run 표준 종료 처리 (meta.json + summary.html)
    try:
        # total_fail 기반 1차 판정 + step 카운트 기반 2차 보정
        if env.total_fail > 0:
            final_res = "FAIL"
        else:
            final_res = _pick_overall_result(getattr(env, "run_counts", {}) or {})

        # ✅ Failures를 summary/meta에 반영 (step 누적분 + fail_logs 병합)
        try:
            preserved = list(getattr(env, "run_fail_logs", []) or [])
            env.run_fail_logs = preserved

            for item in (env.fail_logs or []):
                env.run_fail_logs.append({
                    "iter": str(item.get("iter", "")),
                    "name": str(item.get("name", "")),
                    "error": str(item.get("error", "")),
                    # kind/flow는 확장 정보로 남겨도 무방(템플릿이 무시하면 그만)
                    "kind": str(item.get("kind", "")),
                    "flow": str(item.get("flow", "")),
                })
        except Exception:
            # 여기서도 완전 초기화하지 말고, 기존 값 보존
            try:
                env.run_fail_logs = list(getattr(env, "run_fail_logs", []) or [])
            except Exception:
                env.run_fail_logs = []

        # ✅ artifacts는 finalize 전에 먼저 채운다 (meta/summary에 반영되도록)
        # - 메일 첨부는 제외하더라도, 로컬 index.html 경로는 summary에서 링크로 활용 가능
        if airtest_index_html and os.path.exists(airtest_index_html):
            env.run_artifacts["airtest_report"] = os.path.relpath(airtest_index_html, env.run_dir).replace("\\", "/")

        # - Drive 링크도 summary/meta에서 볼 수 있게 남김
        if getattr(env, "airtest_report_link", None):
            env.run_artifacts["airtest_drive_link"] = str(env.airtest_report_link)
        if final_recent:
            env.run_artifacts["logcat_recent"] = os.path.relpath(final_recent, env.run_dir).replace("\\", "/")
        if final_slice:
            env.run_artifacts["logcat_slice"] = os.path.relpath(final_slice, env.run_dir).replace("\\", "/")
        if final_pdf:
            env.run_artifacts["resource_report"] = os.path.relpath(final_pdf, env.run_dir).replace("\\", "/")
        if evcsv and os.path.exists(evcsv):
            env.run_artifacts["events_csv"] = os.path.relpath(evcsv, env.run_dir).replace("\\", "/")

        # ✅ finalize는 1번만
        finalize_run(env, result=final_res)

        # ✅ 최종 요약 메일: 메일 본문 = summary.html(동일 HTML)
        try:
            # 제목은 결과 기반으로
            subject = (f"✅ A-Test 최종 성공 ({repeat}회 무오류) - {env.package}_{env.serial or 'device'}"
                        if final_res == "PASS" else
                        f"⚠️ A-Test 최종 완료({final_res}, 실패 {env.total_fail}건) - {env.package}_{env.serial or 'device'}")

            # body_html은 summary와 동일한 HTML (파일/문자열 동기화)
            try:
                # finalize_run이 방금 summary.html을 저장했으니 그걸 읽어도 됨
                with open(env.run_summary_path, "r", encoding="utf-8") as f:
                    body_html = f.read()
            except Exception:
                # 폴백: 메모리에서 재생성
                body_html = _summary_html_text(env)

            body_plain = (
                "QA Run Summary (HTML)\n"
                f"Run ID: {env.run_id}\n"
                f"Result: {env.run_result}\n"
                f"Run Dir: {env.run_dir}\n"
                "HTML 본문을 확인하세요."
            )

            # ✅ Airtest 포터블 리포트는 Drive 링크로만 제공
            if getattr(env, "airtest_report_link", None):
                body_plain += f"\n\n[Airtest 포터블 리포트(Drive)]\n- {env.airtest_report_link}\n"
                if body_html:
                    link = env.airtest_report_link
                    body_html += f'\n<hr><h3>Airtest 포터블 리포트(Drive)</h3><p><a href="{link}">{link}</a></p>\n'
            else:
                # 업로드 실패했을 때 안내(선택)
                if airtest_index_html:
                    body_plain += "\n\n[Airtest 포터블 리포트]\n- Drive 업로드 실패 (로그 확인 필요)\n"

            # ✅ 첨부: summary.html + 주요 산출물(기존과 동일)
            attach = []
            for p in [env.run_summary_path, env.run_log_path, final_recent, final_slice, final_pdf, evcsv]:
                if p and os.path.exists(p):
                    attach.append(p)

            send_mail_smtp(
                subject=subject,
                body=body_plain,
                body_html=body_html,
                attachments=attach,
                to=mail_to, cc=mail_cc, bcc=mail_bcc
            )

            step(f"📧 최종 요약(HTML) 메일 발송 완료: {subject}")
        except Exception as me:
            step(f"[WARN] 최종 요약(HTML) 메일 전송 실패: {me}", env=env)

        # ✅ 브라우저는 summary만 오픈 (Airtest는 summary 링크로 진입)
        try:
            sp = getattr(env, "run_summary_path", None)
            if sp and os.path.exists(sp):
                webbrowser.open_new(os.path.abspath(sp))
        except Exception:
            pass
        
    except Exception:
        pass

    if env.run_counts.get("WARN", 0) > 0 and env.total_fail == 0:
        note(f"[SCOPE] FAIL은 없지만 WARN {env.run_counts.get('WARN')}건 발생 → 상세는 Warnings 섹션 참조", env=env)

    return {
        "total_fail": env.total_fail,
        "fail_logs": env.fail_logs,
        "html_report": html_rep,
        "final_recent": final_recent,  # 👈 추가
        "final_slice": final_slice,
        "final_pdf": final_pdf,
        "events_csv": evcsv        
    }

# ==========================================================
# 🧭 SCROLL / DRAG / SLIDE (from scratch, 5 modes)
#    1) POCO container
#    2) Global (Airtest)
#    3) ADB
#    4) Image-anchor (first detect, then keep using coords)
#    5) Coordinate-based
#  - step_ratio & duration로 이동량/속도 조절
#  - methods_order로 시도 순서/선택 가능
#  - find_and_click(): 발견 후 클릭 포함
# ==========================================================
_RES_CACHE = None
_RES_CACHE_T = 0.0
_RES_TTL = 5.0  # 초. 해상도/회전 빈변경 가정 시 5초 단위 갱신

# ---------- 공통 유틸 ----------
def _get_resolution() -> Tuple[int, int]:
    global _RES_CACHE, _RES_CACHE_T
    now = time.time()
    if _RES_CACHE and (now - _RES_CACHE_T) < _RES_TTL:
        return _RES_CACHE
    try:
        w, h = current_device().get_current_resolution()
        _RES_CACHE = (int(w), int(h))
        _RES_CACHE_T = now
        return _RES_CACHE
    except Exception:
        _RES_CACHE = (1080, 1920)
        _RES_CACHE_T = now
        return _RES_CACHE

def _clamp(v, lo, hi): 
    return max(lo, min(hi, v))

def _rel_drag_points(direction: str, step_ratio: float) -> Tuple[list, list]:
    """
    Poco 상대좌표(0~1). 수직: x=0.5 고정, y 이동 / 수평: y=0.5 고정, x 이동
    direction: "down" | "up" | "left" | "right"
    """
    d = _clamp(step_ratio/2.0, 0.05, 0.9)

    if direction in ("down", "up"):
        base_y = 0.5
        if direction == "down":  # 손가락 ↓↑ (내용 ↑)
            y1, y2 = base_y + d, base_y - d
        else:                    # 손가락 ↑↓ (내용 ↓)
            y1, y2 = base_y - d, base_y + d
        p1 = [0.5, _clamp(y1, 0.07, 0.93)]
        p2 = [0.5, _clamp(y2, 0.07, 0.93)]
        return p1, p2

    # left/right
    base_x = 0.5
    if direction == "left":      # left: 손가락 ←→ (내용 →)
        x1, x2 = base_x - d, base_x + d
    else:                         # right: 손가락 →← (내용 ←)
        x1, x2 = base_x + d, base_x - d
    p1 = [_clamp(x1, 0.07, 0.93), 0.5]
    p2 = [_clamp(x2, 0.07, 0.93), 0.5]
    return p1, p2

def _abs_drag_points(direction: str, step_ratio: float, W: int, H: int) -> Tuple[Tuple[int,int], Tuple[int,int]]:
    """
    전역/ADB/좌표 드래그 절대좌표.
    수직: 중앙 x, y 이동 / 수평: 중앙 y, x 이동
    """
    (p1, p2) = _rel_drag_points(direction, step_ratio)
    return (int(W*p1[0]), int(H*p1[1])), (int(W*p2[0]), int(H*p2[1]))

# ---------- 1) POCO 컨테이너 (수평 지원, 교체) ----------
def scroll_poco_container(*, scroll_view, direction="down", step_ratio=0.65, duration=0.5, debug=False) -> bool:
    if not (scroll_view and scroll_view.exists()):
        return False
    if debug: step(f"[SCROLL][poco-container] {direction} {step_ratio} dur={duration}")
    if direction == "up":
        dir_vec = [0, step_ratio]        # 스크롤 위로(손가락 ↓)
    elif direction == "down":
        dir_vec = [0, -step_ratio]       # 스크롤 아래로 (손가락 ↑)
    elif direction == "right":
        dir_vec = [-step_ratio, 0]       # 스크롤 오른쪽으로 (손가락 ←)
    elif direction == "left":
        dir_vec = [ step_ratio, 0]       # 스크롤 왼쪽으로 (손가락 →)
    else:
        return False
    scroll_view.swipe(dir_vec, duration=duration)
    time.sleep(0.2)
    return True

# ---------- 2) 전역 슬라이드 (수평 지원, 교체) ----------
def scroll_global(*, direction="down", step_ratio=0.65, duration=0.5, debug=False) -> bool:
    W, H = _get_resolution()
    (x1, y1), (x2, y2) = _abs_drag_points(direction, step_ratio, W, H)
    if debug: step(f"[SCROLL][global] {direction} ({x1},{y1}) -> ({x2},{y2}) dur={duration}")
    swipe((x1, y1), (x2, y2), duration=duration)
    time.sleep(0.2)
    return True

# ---------- 3) ADB 스와이프 (수평 지원, 교체) ----------
def scroll_adb(*, direction="down", step_ratio=0.65, duration=0.5, debug=False) -> bool:
    W, H = _get_resolution()
    (x1, y1), (x2, y2) = _abs_drag_points(direction, step_ratio, W, H)
    dur_ms = int(max(1, duration * 1000))
    cmd = f"input swipe {x1} {y1} {x2} {y2} {dur_ms}"
    if debug: step(f"[SCROLL][adb] {direction} {cmd}")
    shell(cmd)
    time.sleep(0.2)
    return True

# ---------- 4) 이미지 앵커 기반 드래그 (최초만 이미지 → 이후 좌표) ----------
#  - 최초 1회: Template(img) 매칭으로 anchor 좌표(px) 획득/저장
#  - 이후: 저장된 좌표를 '계속' 사용하여 드래그 (이미지가 화면에서 사라져도 동작)
_ANCHOR_CACHE: Dict[str, Tuple[int,int]] = {}

# 이미지 탐색 쓰로틀(동일 key 재시도 최소 간격)
_IMAGE_ANCHOR_THROTTLE_SEC = 1.8
_IMAGE_ANCHOR_LAST_TRY: Dict[str, float] = {}
_IMAGE_ANCHOR_LAST_HIT: Dict[str, Union[str, Tuple[int,int]]] = {}  # "MISS" 또는 (x,y)

def set_anchor_cache(key: str, pos: Tuple[int,int]) -> None:
    _ANCHOR_CACHE[key] = pos

def get_anchor_cache(key: str) -> Optional[Tuple[int,int]]:
    return _ANCHOR_CACHE.get(key)

def clear_anchor_cache(key: Optional[str] = None) -> None:
    if key is None:
        _ANCHOR_CACHE.clear()
    else:
        _ANCHOR_CACHE.pop(key, None)

# ---------- 4) 이미지 앵커 드래그 (좌/우 지원, 교체) ----------
def drag_with_image_anchor(
    *,
    anchor_key: str,
    anchor_img: Optional[str],
    direction="down", step_ratio=0.65, duration=0.5,
    debug=False
) -> bool:

    W, H = _get_resolution()
    anchor_xy = get_anchor_cache(anchor_key)

    if anchor_xy is None:
        if not anchor_img:
            if debug: step(f"[SCROLL][image-anchor] no cache & no image for key='{anchor_key}'")
            return False

        now = time.time()
        last_try = _IMAGE_ANCHOR_LAST_TRY.get(anchor_key, 0.0)
        # 직전 탐색 실패였다면 쿨다운 동안 재시도 금지
        if _IMAGE_ANCHOR_LAST_HIT.get(anchor_key, "MISS") == "MISS":
            if (now - last_try) < _IMAGE_ANCHOR_THROTTLE_SEC:
                if debug: step(f"[SCROLL][image-anchor] throttle MISS {anchor_key}")
                return False

        _IMAGE_ANCHOR_LAST_TRY[anchor_key] = now
        try:
            tmpl = Template(anchor_img, threshold=0.75)
        except Exception as e:
            if debug: step(f"[SCROLL][image-anchor] template error: {e}")
            _IMAGE_ANCHOR_LAST_HIT[anchor_key] = "MISS"
            return False

        match = exists(tmpl)
        if not match:
            if debug: step(f"[SCROLL][image-anchor] no match (key='{anchor_key}')")
            _IMAGE_ANCHOR_LAST_HIT[anchor_key] = "MISS"
            return False

        ax, ay = int(match[0]), int(match[1])
        set_anchor_cache(anchor_key, (ax, ay))
        _IMAGE_ANCHOR_LAST_HIT[anchor_key] = (ax, ay)
        anchor_xy = (ax, ay)
        if debug: step(f"[SCROLL][image-anchor] cached anchor '{anchor_key}' at {anchor_xy}")

    x1, y1 = anchor_xy
    # 방향에 따라 x 또는 y 이동량 산출
    if direction in ("down", "up"):
        dpx = 0
        dpy = int((_clamp(step_ratio, 0.1, 1.0) * (H * 0.9)) * (-1 if direction == "down" else 1))
        x2, y2 = x1 + dpx, _clamp(y1 + dpy, 10, H - 10)
    else:
        dpx = int((_clamp(step_ratio, 0.1, 1.0) * (W * 0.9)) * (-1 if direction == "right" else 1))
        dpy = 0
        x2, y2 = _clamp(x1 + dpx, 10, W - 10), y1 + dpy

    if debug: step(f"[SCROLL][image-anchor] {direction} {anchor_key}: ({x1},{y1}) -> ({x2},{y2}) dur={duration}")
    swipe((x1, y1), (x2, y2), duration=duration)
    time.sleep(0.2)
    return True

# ---------- 5) 좌표 기반 드래그 ----------
def drag_by_coords(*, start_xy: Tuple[int,int], end_xy: Tuple[int,int], duration=0.5, debug=False) -> bool:
    (x1, y1) = start_xy; (x2, y2) = end_xy
    if debug: step(f"[DRAG][coords] ({x1},{y1}) -> ({x2},{y2}) dur={duration}")
    swipe((int(x1), int(y1)), (int(x2), int(y2)), duration=duration)
    time.sleep(0.2)
    return True

# ---------- 메인: 한 번 스크롤(선택된 방식 순차 시도) ----------
def scroll_once(
    *,
    # 대상 컨테이너(있으면 전달)
    scroll_view=None,
    # 공통 파라미터
    direction="down", step_ratio=0.65, duration=0.5,
    # 방식 선택/순서: ["poco","global","adb","image","coord"] 중에서 조합
    methods_order: List[str] = ("poco","global","adb","image","coord"),
    # 이미지 앵커 옵션
    anchor_key: str = "default", anchor_img: Optional[str] = None,
    # 좌표 드래그 옵션
    coord_start: Optional[Tuple[int,int]] = None, coord_end: Optional[Tuple[int,int]] = None,
    debug=False
) -> bool:

    for m in methods_order:
        try:
            if m == "poco" and scroll_view is not None:
                if scroll_poco_container(scroll_view=scroll_view, direction=direction,
                                         step_ratio=step_ratio, duration=duration, debug=debug):
                    return True
            elif m == "global":
                if scroll_global(direction=direction, step_ratio=step_ratio, duration=duration, debug=debug):
                    return True
            elif m == "adb":
                if scroll_adb(direction=direction, step_ratio=step_ratio, duration=duration, debug=debug):
                    return True
            elif m == "image":
                if drag_with_image_anchor(anchor_key=anchor_key, anchor_img=anchor_img,
                                          direction=direction, step_ratio=step_ratio, duration=duration, debug=debug):
                    return True
            elif m == "coord" and coord_start and coord_end:
                if drag_by_coords(start_xy=coord_start, end_xy=coord_end, duration=duration, debug=debug):
                    return True
        except Exception as e:
            step(f"[SCROLL][{m}] err: {e}")
    step("[SCROLL] all methods tried in one cycle")
    return False

# ---------- 요소가 보일 때까지 스크롤 ----------
def scroll_until_visible(
    *, target_element,
    scroll_view=None,
    max_cycles=12,
    direction="down", step_ratio=0.65, duration=0.5,
    methods_order: List[str] = ("poco","global","adb","image","coord"),
    anchor_key: str = "default", anchor_img: Optional[str] = None,
    coord_start: Optional[Tuple[int,int]] = None, coord_end: Optional[Tuple[int,int]] = None,
    snap_fail=True,
    debug=False
) -> bool:

    if debug: step(f"[SCROLL] until visible: dir={direction}, cycles={max_cycles}, methods={methods_order}")
    for i in range(1, max_cycles + 1):
        if is_visible(target_element):
            step(f"[SCROLL] ✅ visible at cycle {i}")
            return True
        if debug: step(f"[SCROLL] cycle {i}")
        ok = scroll_once(
            scroll_view=scroll_view, direction=direction, step_ratio=step_ratio, duration=duration,
            methods_order=methods_order, anchor_key=anchor_key, anchor_img=anchor_img,
            coord_start=coord_start, coord_end=coord_end, debug=debug
        )
        if not ok:
            # 가로막는 키보드/오버레이 대비: 간헐적 BACK
            if i in (3, 6, 9):
                try: shell("input keyevent 4")  # BACK
                except: pass
            time.sleep(0.4)
    if snap_fail:
        try:
            step(f"[SCROLL] ❌ target not visible: {get_label(target_element)}", True)
        except: 
            pass
    step("[SCROLL] ❌ not found")
    return False

# ---------- 요소 근처 탭 (요소 밖) ----------
def click_near_element(
    el,
    *,
    position: str = "top",        # "top" / "bottom" / "left" / "right" / "center"
    offset_ratio: float = 0.1,    # 화면 높이/폭 대비 이동 비율
    margin_ratio: float = 0.02,   # 화면 경계와의 최소 여백 비율
) -> bool:
    """
    대상 요소 기준 주변 영역을 탭한다.

    position:
      - "top"    : 요소 위쪽 바깥
      - "bottom" : 요소 아래쪽 바깥
      - "left"   : 요소 왼쪽 바깥
      - "right"  : 요소 오른쪽 바깥
      - "center" : 요소 중심 (요소 안)

    offset_ratio:
      - "바깥" 방향으로 얼마나 떨어질지 (화면 비율 기준, 기본 4%)

    margin_ratio:
      - 화면 가장자리로 너무 붙지 않도록 최소 여백 (기본 2%)
    """
    try:
        # 1) 요소의 중심/크기 정보 (0~1)
        x, y = el.get_position()
        w, h = el.get_size()

        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            step("[CLICK] click_near: invalid position")
            return False

        w = float(w or 0.0)
        h = float(h or 0.0)

        # 2) 요소의 bounding box (0~1)
        x1, y1 = x - w / 2.0, y - h / 2.0  # left, top
        x2, y2 = x + w / 2.0, y + h / 2.0  # right, bottom

        # 3) 기본 탭 위치를 "요소 중심"으로 세팅
        tap_x_ratio = x
        tap_y_ratio = y

        # 4) position에 따라 탭 위치 조정
        pos = position.lower()

        if pos == "top":
            # 요소의 top보다 위쪽으로 offset_ratio 만큼 이동
            target_y = (y1 - offset_ratio)
            tap_y_ratio = target_y
            tap_x_ratio = x

        elif pos == "bottom":
            # 요소의 bottom보다 아래쪽으로 offset_ratio 만큼 이동
            target_y = (y2 + offset_ratio)
            tap_y_ratio = target_y
            tap_x_ratio = x

        elif pos == "left":
            # 요소의 left보다 왼쪽으로 offset_ratio 만큼 이동
            target_x = (x1 - offset_ratio)
            tap_x_ratio = target_x
            tap_y_ratio = y

        elif pos == "right":
            # 요소의 right보다 오른쪽으로 offset_ratio 만큼 이동
            target_x = (x2 + offset_ratio)
            tap_x_ratio = target_x
            tap_y_ratio = y

        elif pos == "center":
            # 그냥 요소 중앙 클릭용 (요소 안)
            tap_x_ratio = x
            tap_y_ratio = y

        else:
            # 알 수 없는 값이면 그냥 요소 중심을 탭하고 경고만 남김
            step(f"[CLICK] click_near: unknown position={position}, fallback center")
            tap_x_ratio = x
            tap_y_ratio = y

        # 5) 화면 경계 안으로 클램프 (margin_ratio 적용)
        min_r = margin_ratio
        max_r = 1.0 - margin_ratio

        tap_x_ratio = min(max(tap_x_ratio, min_r), max_r)
        tap_y_ratio = min(max(tap_y_ratio, min_r), max_r)

        # 6) 비율 → 절대 해상도 좌표 변환
        W, H = _get_resolution()  # 기존 스크롤 유틸에서 사용하던 해상도 헬퍼

        tap_x = max(1, min(int(W * tap_x_ratio), W - 1))
        tap_y = max(1, min(int(H * tap_y_ratio), H - 1))

        # 7) 실제 탭 수행 (요소 밖 절대 좌표)
        shell(f"input tap {tap_x} {tap_y}")
        step(f"[CLICK] near ({position}) @{tap_x},{tap_y}")
        return True

    except Exception as e:
        step(f"[CLICK] click_near err: {e}")
        return False


# ---------- 발견 후 클릭 (try 버전) ----------
def try_find_click(
    *, target_element,
    scroll_view=None, max_cycles=20,
    direction="down", step_ratio=0.65, duration=0.5,
    methods_order: List[str] = ("poco", "global", "adb", "image", "coord"),
    anchor_key: str = "default", anchor_img: Optional[str] = None,
    coord_start: Optional[Tuple[int, int]] = None, coord_end: Optional[Tuple[int, int]] = None,
    wait_after_click=0.5,
    click_position: str = "element",  # "element" / "top" / "bottom" / "left" / "right"
    offset_ratio: float = 0.1,        # 화면 높이/폭 대비 이동 비율(0.1=10%)
    desc: str = "",
    debug=False
) -> bool:
    """
    시도형 스크롤+클릭:
      - 실패 시 False만 리턴하고 예외는 발생시키지 않는다.
      - 기존 find_and_click 의 동작과 동일.
    """
    ok = scroll_until_visible(
        target_element=target_element, scroll_view=scroll_view,
        max_cycles=max_cycles, direction=direction, step_ratio=step_ratio, duration=duration,
        methods_order=methods_order, anchor_key=anchor_key, anchor_img=anchor_img,
        coord_start=coord_start, coord_end=coord_end, debug=debug
    )
    if not ok:
        return False
    # 오프스크린 가드
    if not is_visible(target_element):
        step("[CLICK] abort: offscreen")
        return False
    try:
        if click_position == "element":
            # 기존처럼 요소 중앙 클릭
            target_element.click([0.5, 0.5])
        else:
            # 요소 밖 특정 방향 클릭
            click_near_element(
                target_element,
                position=click_position,   # "top" / "bottom" / "left" / "right"
                offset_ratio=offset_ratio,
            )
        if desc:
            step(f"{desc}: PASS ✅ (CLICK ok: {get_label(target_element)})")
        else:
            step(f"[CLICK] ok: {get_label(target_element)}")
        time.sleep(wait_after_click)
        return True
    except Exception as e:
        step(f"[CLICK] err: {e}")
        return False


# ---------- 발견 후 클릭 (must 버전) ----------
def must_find_click(
    *, target_element,
    scroll_view=None, max_cycles=12,
    direction="down", step_ratio=0.65, duration=0.5,
    methods_order: List[str] = ("poco", "global", "adb", "image", "coord"),
    anchor_key: str = "default", anchor_img: Optional[str] = None,
    coord_start: Optional[Tuple[int, int]] = None, coord_end: Optional[Tuple[int, int]] = None,
    wait_after_click=0.5,
    click_position: str = "element",  # "element" / "top" / "bottom" / "left" / "right"
    offset_ratio: float = 0.1,        # 화면 높이/폭 대비 이동 비율(0.04=4%)
    desc: str = "",
    debug=False
) -> bool:
    """
    필수 스크롤+클릭:
      - 실패 시 RuntimeError 예외 발생.
    """

    ok = try_find_click(
        target_element=target_element,
        scroll_view=scroll_view, max_cycles=max_cycles,
        direction=direction, step_ratio=step_ratio, duration=duration,
        methods_order=methods_order, anchor_key=anchor_key, anchor_img=anchor_img,
        coord_start=coord_start, coord_end=coord_end,
        wait_after_click=wait_after_click,
        click_position=click_position,           # ⬅ 추가
        offset_ratio=offset_ratio,             # ⬅ 추가
        desc=desc,
        debug=debug
    )
    if not ok:
        name = get_label(target_element)
        msg = f"[CLICK] find_and_click: FAIL ❌ ({name})"
        soft_fail(msg)
        raise
    return True

# 🔁 하위호환: 기존 이름 유지 (기존 의미는 'try' 로 간주)
def find_and_click(
    *, target_element,
    scroll_view=None, max_cycles=12,
    direction="down", step_ratio=0.65, duration=0.5,
    methods_order: List[str] = ("poco", "global", "adb", "image", "coord"),
    anchor_key: str = "default", anchor_img: Optional[str] = None,
    coord_start: Optional[Tuple[int, int]] = None, coord_end: Optional[Tuple[int, int]] = None,
    wait_after_click=0.5,
    click_position: str = "element",  # "element" / "top" / "bottom" / "left" / "right"
    offset_ratio: float = 0.1,        # 화면 높이/폭 대비 이동 비율(0.04=4%)
    desc: str = "",
    debug=False
) -> bool:
    """
    하위호환용 래퍼:
      - 기존 스크립트의 find_and_click 호출은 모두 try_find_click 과 동일하게 동작.
    """

    return try_find_click(
        target_element=target_element,
        scroll_view=scroll_view, max_cycles=max_cycles,
        direction=direction, step_ratio=step_ratio, duration=duration,
        methods_order=methods_order, anchor_key=anchor_key, anchor_img=anchor_img,
        coord_start=coord_start, coord_end=coord_end,
        wait_after_click=wait_after_click,
        click_position=click_position,           # ⬅ 추가
        offset_ratio=offset_ratio,             # ⬅ 추가
        desc=desc,
        debug=debug
    )

# ==========================================================
# 🧩 예외상황 처리기 (조건 + 액션 빌더 + 핵심 처리기)   
#  - 조건: exists / visible / exists_any / visible_any
#  - 액션: click / back / tap_ratio / send_text / sleep
#  - 핵심: handle_expected_exceptions()
#   rules: [{ "name": str, "condition": callable, "action": callable }, ...]
# ==========================================================)
# --- 조건 빌더(간단) ---
def cond_exists(sel) -> Callable[[], bool]:
    """선택자가 exists면 True"""
    return lambda: sel.exists()

def cond_visible(sel) -> Callable[[], bool]:
    """선택자가 화면에 보이면 True"""
    return lambda: sel.exists() and is_visible(sel)

def cond_exists_any(pocos: List) -> Callable[[], bool]:
    return lambda: any((el.exists() for el in pocos))

def cond_visible_any(pocos: List) -> Callable[[], bool]:
    return lambda: any((el.exists() and is_visible(el) for el in pocos))

# --- 액션 빌더(필요 최소) ---
def act_click(sel, *, env=None, wait: float=0.3) -> Callable[[], None]:
    def _do():
        try:
            sel.wait_for_appearance(timeout=5)
            sel.click([0.5, 0.5])
            step(f"[EXC-ACT] click: {get_label(sel)}")
            time.sleep(wait)
        except Exception as e:
            soft_fail(f"[EXC-ACT] click FAIL: {e}")
    return _do

def act_back(*, env=None, wait: float=0.2) -> Callable[[], None]:
    def _do():
        try:
            keyevent("BACK")
            step("[EXC-ACT] BACK")
            time.sleep(wait)
        except Exception as e:
            soft_fail(f"[EXC-ACT] BACK FAIL: {e}")
    return _do

def act_tap_ratio(xr: float, yr: float, *, env=None, wait: float=0.2) -> Callable[[], None]:
    """화면 비율 좌표 탭 (0~1)"""
    def _do():
        try:
            W,H = _get_resolution()  # 캐시 기반: dumpsys 빈도 급감
            x = max(1, min(int(W*xr), W-1)); y = max(1, min(int(H*yr), H-1))
            shell(f"input tap {x} {y}")
            step(f"[EXC-ACT] tap @{x},{y}")
            time.sleep(wait)
        except Exception as e:
            soft_fail(f"[EXC-ACT] tap FAIL: {e}")
    return _do

def act_send_text(text: str, *, env=None, wait: float=0.1) -> Callable[[], None]:
    def _do():
        try:
            shell(f'input text "{text}"')
            step(f"[EXC-ACT] send_text: {text}")
            time.sleep(wait)
        except Exception as e:
            soft_fail(f"[EXC-ACT] send_text FAIL: {e}")
    return _do

def act_sleep(sec: float) -> Callable[[], None]:
    return lambda: time.sleep(sec)

def multi_act(*acts):
    def _do():
        for fn in acts:
            try:
                fn()
            except Exception as e:
                step(f"[EXC-ACT] multi_act ERR: {e}")
                pass
    return _do

# --- 핵심: 예외상황 처리기 ---
def handle_expected_exceptions(
    *, env: Optional['QAEnv']=None,
    rules: List[Dict],
    handle_all: bool = False,   # True면 매칭되는 규칙을 전부 처리, False면 첫 규칙만 처리
    stop_after: int = 3,        # 최대 처리 횟수(무한루프 방지)
) -> int:
    """
    rules: [{ "name": str, "condition": callable, "action": callable }, ...]
    return: 실행된 rule 개수
    """
    env = use_env(env)

    executed = 0
    loop = 0
    last_name = None
    while loop < stop_after:
        loop += 1
        matched_any = False
        for r in rules:
            try:
                cond = r.get("condition")
                act  = r.get("action")
                name = r.get("name", "rule")
                if callable(cond) and cond():
                    if name == last_name:
                        continue  # 같은 rule 연속 처리 방지 (옵션)
                    last_name = name
                    step(f"[EXC] match: {name}")
                    matched_any = True
                    if callable(act):
                        act()
                        time.sleep(0.3)  # 화면 정리 시간
                    executed += 1
                    if not handle_all:
                        return executed
            except Exception as e:
                step(f"[EXC] rule ERR: {r.get('name','rule')}: {e}", True)
        if not matched_any:
            break
    return executed

# ==========================================================
# 🗄️ Account Pool: JSON + file lock (Windows 전용)
#  - configure_account_pool(): 전역 파일/락 경로 설정
#  - _load_pool() / _save_pool(): JSON 입출력
#  - _sweep_stale_leases(): 유휴/죽은 프로세스 정리
# ==========================================================
# --- [ADD/FIX] Account Pool: JSON + file lock (Py3.7+ 하위호환 타입힌트) ---
# --- Account Pool (qa_common/_accounts) ------------------------

def _now() -> float:
    return time.time()

def _pid_alive_windows(pid: int) -> bool:
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        k32.SetLastError(0)
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False

def _lease_rec_to_user(rec) -> str:
    # leased 레코드가 str(구버전) 또는 dict(신버전) 모두 수용
    return rec if isinstance(rec, str) else rec.get("user")

def _sweep_stale_leases(pool: dict, max_age_sec: int = 24*3600) -> int:
    """
    같은 호스트의 lease 중, 프로세스가 죽었거나 너무 오래된 항목을 해제.
    반환: 해제 개수
    """
    leased = pool.get("leased", {})
    if not leased:
        return 0
    host = socket.gethostname()
    to_free = []
    now = _now()
    for worker_id, rec in list(leased.items()):
        if isinstance(rec, str):
            # 구버전 포맷: 사용자만 문자열로 저장됨 → host/pid 정보 없어 age로만 판단
            # 너무 오래된 경우만 정리 (보수적으로 24h 초과 시)
            # → 메타 없음이라 바로 해제하기 부담되면 pass 하세요.
            continue
        user = rec.get("user")
        w_host = rec.get("host")
        pid = rec.get("pid")
        ts = rec.get("ts", 0)
        if w_host == host:
            dead = (not isinstance(pid, int)) or (not _pid_alive_windows(pid))
            too_old = (now - float(ts) > max_age_sec)
            if dead or too_old:
                to_free.append(worker_id)
    for w in to_free:
        leased.pop(w, None)
    return len(to_free)

# 현재 프로세스에서 사용할 계정풀 파일/락 경로(전역)
_ACCOUNT_POOL_JSON: Optional[str] = None
_ACCOUNT_POOL_LOCK: Optional[str] = None

def _qa_common_accounts_root() -> str:
    """qa_common/_accounts 폴더 절대 경로 보장"""
    qa_common_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(qa_common_dir, "_accounts")
    pathlib.Path(root).mkdir(parents=True, exist_ok=True)
    return root

def configure_account_pool(pool_name: Optional[str] = None,
                           pool_file: Optional[str] = None) -> Tuple[str, str]:
    """
    계정풀 파일 위치를 설정(앱/스크립트별 개별 JSON).
    모든 상대 경로는 qa_common/_accounts 기준으로 해석.
    우선순위:
      1) pool_file (절대/상대)  ← 상대면 qa_common/_accounts/<pool_file>
      2) 환경변수 QA_ACC_POOL_FILE (절대 경로 권장)
      3) pool_name (확장자 생략 가능) ← qa_common/_accounts/<pool_name>.json
      4) 환경변수 QA_ACC_POOL_NAME
      5) 기본값: qa_common/_accounts/account_pool.json
    """
    global _ACCOUNT_POOL_JSON, _ACCOUNT_POOL_LOCK

    env_pool_file = os.environ.get("QA_ACC_POOL_FILE")
    use_file = pool_file or env_pool_file

    base = _qa_common_accounts_root()

    if use_file:
        json_path = use_file if os.path.isabs(use_file) else os.path.join(base, use_file)
        json_path = os.path.abspath(json_path)
        lock_path = json_path + ".lock"
    else:
        env_pool_name = os.environ.get("QA_ACC_POOL_NAME")
        name = pool_name or env_pool_name or "account_pool"
        if not name.lower().endswith(".json"):
            name += ".json"
        json_path = os.path.join(base, name)
        lock_path = os.path.join(base, name + ".lock")

    _ACCOUNT_POOL_JSON = json_path
    _ACCOUNT_POOL_LOCK = lock_path
    return json_path, lock_path

def _ensure_paths() -> Tuple[str, str]:
    """설정되지 않았으면 기본값(account_pool.json)을 잡아준다."""
    global _ACCOUNT_POOL_JSON, _ACCOUNT_POOL_LOCK
    if not (_ACCOUNT_POOL_JSON and _ACCOUNT_POOL_LOCK):
        configure_account_pool()  # 기본값으로 세팅
    return _ACCOUNT_POOL_JSON, _ACCOUNT_POOL_LOCK  # type: ignore

def _lock_file(lock_path: str):
    fh = open(lock_path, "a+b")
    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    return fh

def _unlock_file(fh):
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        fh.close()

def _load_pool(json_path: str) -> dict:
    if not os.path.exists(json_path):
        return {"accounts": [], "secrets": {}, "leased": {}}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        d.setdefault("accounts", []); d.setdefault("secrets", {}); d.setdefault("leased", {})
        return d
    except Exception:
        return {"accounts": [], "secrets": {}, "leased": {}}

def _save_pool(json_path: str, data: dict):
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)

def set_account_pool(accounts: List[str]) -> Tuple[str, str]:
    """
    계정 목록을 등록/갱신. accounts: ["id1:pw1","id2:pw2", ...]
    반환: (json_path, lock_path) — 디버그/로그용
    """
    json_path, lock_path = _ensure_paths()
    lk = _lock_file(lock_path)
    try:
        pool = _load_pool(json_path)
        for a in accounts:
            if not a or ":" not in a:
                continue
            uid, pw = a.split(":", 1)
            if uid not in pool["accounts"]:
                pool["accounts"].append(uid)
            pool["secrets"][uid] = pw
        _save_pool(json_path, pool)
        return json_path, lock_path
    finally:
        _unlock_file(lk)

def acquire_account(worker_id: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
    """
    계정 임대. 반환: (worker_id, user, pass)
    동일 worker_id가 다시 호출되면 같은 계정을 재할당(루프 동안 고정).
    """
    json_path, lock_path = _ensure_paths()
    worker_id = worker_id or str(uuid.uuid4())
    lk = _lock_file(lock_path)
    try:
        pool = _load_pool(json_path)
        leased = pool.setdefault("leased", {})

        # ✅ 구버전/이전 실행 잔여 lease 자동 정리
        cleaned = _sweep_stale_leases(pool)
        if cleaned:
            _save_pool(json_path, pool)

        # 이미 같은 워커가 있다면 그대로 재사용
        if worker_id in leased:
            rec = leased[worker_id]
            uid = _lease_rec_to_user(rec)
            return worker_id, uid, pool["secrets"].get(uid)

        # 가용 계정 탐색
        inuse = set(_lease_rec_to_user(v) for v in leased.values())
        for uid in pool.get("accounts", []):
            if uid not in inuse:
                # ✅ 임대 메타데이터 저장(호스트/프로세스/시각)
                leased[worker_id] = {
                    "user": uid,
                    "host": socket.gethostname(),
                    "pid": os.getpid(),
                    "ts": _now()
                }
                _save_pool(json_path, pool)
                return worker_id, uid, pool["secrets"].get(uid)

        raise RuntimeError("사용 가능한 계정이 없습니다.")
    finally:
        _unlock_file(lk)

def release_account(worker_id: str) -> None:
    """임대한 계정 반납(테스트 종료 시 호출 권장)"""
    json_path, lock_path = _ensure_paths()
    lk = _lock_file(lock_path)
    try:
        pool = _load_pool(json_path)
        if worker_id in pool.get("leased", {}):
            pool["leased"].pop(worker_id, None)
            _save_pool(json_path, pool)
    finally:
        _unlock_file(lk)


# ==========================================================
# 🎵 BGM 재생 여부 판정 (UID 기반 / PID 제거 최종본)
#  - Ground truth: dumpsys audio -> PlaybackActivityMonitor -> players (현재 상태)
#  - 판정: 우리 package의 userId(UID) 기준
#         state=started 이면서 type이 SoundPool이 아닌 플레이어가 존재하면 True
#  - media_session은 ON/OFF에서 비어있을 수 있어(세션 0) 근거로 사용하지 않음
#  - audio_flinger 기반(standby/last_write/track 잔존)은 오탐/미탐 많아 제거
# ==========================================================
# 캐시(UID는 앱 재설치 전까지 안정적이므로 캐시해도 됨)
_UID_CACHE: Dict[str, int] = {}

# PlaybackActivityMonitor 파싱용 정규식
_RE_PAM_BEGIN = re.compile(r"^\s*PlaybackActivityMonitor\b", re.I)
_RE_PAM_PLAYERS = re.compile(r"^\s*players:\s*$", re.I)
_RE_PAM_END = re.compile(
    r"^\s*(ducked players|faded out players|muted player|banned uids|Audio event log|SoundPool playback activity)\b",
    re.I
)

# AudioPlaybackConfiguration 라인에서 type / u/pid / state 추출 (usage는 옵션)
# 예:
# AudioPlaybackConfiguration piid:2343 deviceId:367 type:android.media.MediaPlayer u/pid:10535/7401 state:started ...
_RE_PAM_PLAYER_CORE = re.compile(
    r"AudioPlaybackConfiguration\b.*?\btype:(?P<type>\S+)\s+u/pid:(?P<uid>\d+)/(?P<pid>\d+)\s+state:(?P<state>\w+)",
    re.I
)

def _get_package_uid_from_dumpsys(env: 'QAEnv', package: str) -> Optional[int]:
    """
    패키지 UID(userId/appId)를 최대한 안정적으로 얻는다.
    폴백 체인:
      1) cmd package list packages -U <pkg>  -> uid:10535
      2) dumpsys package <pkg> -> userId=10535 / appId=10535 / uid=10535
      3) pm list packages -U <pkg> -> uid:10535 (기기별 지원 편차)
    """
    if not package:
        return None
    if package in _UID_CACHE:
        return _UID_CACHE[package]

    # 1) cmd package list packages -U <pkg>
    try:
        out = _adb_exec(env, "shell", "cmd", "package", "list", "packages", "-U", package) or ""
        # 예: package:com.kyowon.literacy uid:10535
        m = re.search(r"\buid:(\d+)\b", out)
        if m:
            uid = int(m.group(1))
            _UID_CACHE[package] = uid
            return uid
    except Exception:
        pass

    # 2) dumpsys package <pkg>
    try:
        out = _adb_exec(env, "shell", "dumpsys", "package", package) or ""
        # userId=10535
        m = re.search(r"\buserId=(\d+)\b", out)
        if m:
            uid = int(m.group(1))
            _UID_CACHE[package] = uid
            return uid

        # 일부 단말: appId=10535 / uid=10535 형태
        m = re.search(r"\b(appId|uid)=(\d+)\b", out)
        if m:
            uid = int(m.group(2))
            _UID_CACHE[package] = uid
            return uid
    except Exception:
        pass

    # 3) pm list packages -U <pkg> (지원 시)
    try:
        out = _adb_exec(env, "shell", "pm", "list", "packages", "-U", package) or ""
        # 예: package:com.kyowon.literacy uid:10535
        m = re.search(r"\buid:(\d+)\b", out)
        if m:
            uid = int(m.group(1))
            _UID_CACHE[package] = uid
            return uid
    except Exception:
        pass

    return None

def _dumpsys_audio(env: 'QAEnv') -> str:
    """adb shell dumpsys audio"""
    try:
        return _adb_exec(env, "shell", "dumpsys", "audio") or ""
    except Exception:
        return ""

def _parse_pam_players_current(dump: str) -> List[Dict]:
    """
    dumpsys audio > PlaybackActivityMonitor > players: (현재 상태)만 파싱
    - 이벤트 로그(Audio event log 등) 구간은 절대 섞이지 않게 END 조건에서 중단
    """
    players: List[Dict] = []
    if not dump:
        return players

    in_pam = False
    in_players = False

    for line in dump.splitlines():
        if not in_pam:
            if _RE_PAM_BEGIN.search(line):
                in_pam = True
            continue

        if in_pam and not in_players:
            if _RE_PAM_PLAYERS.search(line):
                in_players = True
            continue

        if in_players:
            # players 섹션 종료(여기서 끊는 게 오탐 방지 핵심)
            if _RE_PAM_END.search(line):
                break

            s = line.strip()
            if not s.startswith("AudioPlaybackConfiguration"):
                continue

            m = _RE_PAM_PLAYER_CORE.search(s)
            if not m:
                continue

            ptype = m.group("type") or ""
            uid = int(m.group("uid"))
            state = (m.group("state") or "").lower()

            players.append({
                "uid": uid,
                "state": state,
                "type": ptype,
                # raw는 디버그 때 보고 싶을 수 있으나,
                # step()가 adb shell log를 호출하는 구조상 "-5.5" 같은 토큰이 옵션으로 오인될 수 있어
                # 기본 저장은 하되, 출력은 제한한다.
                "raw": s,
            })

    return players

def is_bgm_playing(debug: bool = False, env: Optional['QAEnv'] = None) -> bool:
    """
    ✅ 최종 BGM 판정(UID 기반, PID 제거)
    - True 조건:
        PlaybackActivityMonitor > players 에서
        * uid == package userId
        * state == started
        * type 이 SoundPool 이 아님
    """
    env = use_env(env)
    if env is None:
        raise RuntimeError(
            "QAEnv가 설정되지 않았습니다. set_current_env(env)를 먼저 호출하거나, "
            "is_bgm_playing(env=env)로 전달해 주세요."
        )

    package = getattr(env, "package", "") or ""
    uid = _get_package_uid_from_dumpsys(env, package)

    if uid is None:
        step(f"[BGM] uid not found for package={package} -> PLAYING=False (no-uid)", env=env)
        return False

    dump = _dumpsys_audio(env)
    players = _parse_pam_players_current(dump)

    # 판정: started + SoundPool 제외
    playing_hits = []
    for p in players:
        if p.get("uid") != uid:
            continue
        if p.get("state") != "started":
            continue
        ptype = (p.get("type") or "").lower()
        if "soundpool" in ptype:
            continue
        playing_hits.append(p)

    playing = (len(playing_hits) > 0)

    if debug:
        # raw 전체를 step으로 찍으면 adb shell log 경고가 날 수 있어 요약만 찍는다.
        log(f"[BGM][DBG] package={package} uid={uid} players={len(players)} started_hits={len(playing_hits)}")
        # 상위 3개만 요약
        for p in playing_hits[:3]:
            log(f"[BGM][DBG] HIT type={p.get('type')} state={p.get('state')} uid={p.get('uid')}")

    step(f"[BGM] PLAYING = {playing} (pam-uid)", env=env)
    return playing


# ==========================================================
# 📱 앱 프로세스 상태 확인 유틸
#  - get_app_pid(package, env) -> pid|None
#  - is_app_running(package, env) -> bool
#  - get_foreground_package(env) -> package|""
#  - is_app_in_foreground(package, env) -> bool
# ==========================================================
def get_app_pid(package: Optional[str] = None, env=None, debug: bool = False) -> Optional[int]:
    """
    앱 PID 반환. 없으면 None.
    - 기존 _pidof(env, package) 재사용
    - env/package 둘 다 없으면 env.package 사용
    """
    env = use_env(env)
    pkg = package or getattr(env, "package", None)
    if not pkg:
        raise ValueError("package is required (arg package or env.package)")

    pid = _pidof(env, pkg)  # ✅ 기존 공용 로직 재사용
    if debug:
        log(f"[APP] pid={pid} package={pkg}")
    return pid

def is_app_running(package: Optional[str] = None, env=None, debug: bool = False) -> bool:
    """
    앱 프로세스 실행 여부(백그라운드 포함)
    """
    env = use_env(env)
    pkg = package or getattr(env, "package", None)
    if not pkg:
        raise ValueError("package is required (arg package or env.package)")

    pid = get_app_pid(pkg, env=env, debug=False)
    ok = (pid is not None)

    if debug:
        log(f"[APP] running={ok} package={pkg} pid={pid}")
    return ok

def get_foreground_package(env=None, debug: bool = False) -> str:
    """
    현재 포그라운드 패키지명 반환. 실패 시 "".
    - 기존 detect_top_component(env, expect_pkg=None) 재사용
    """
    env = use_env(env)
    pkg, _cls = detect_top_component(env, expect_pkg=None)
    pkg = pkg or ""
    if debug:
        log(f"[APP] foreground={pkg}")
    return pkg

def is_app_in_foreground(package: Optional[str] = None, env=None, debug: bool = False) -> bool:
    """
    지정 패키지가 포그라운드인지 여부
    """
    env = use_env(env)
    pkg = package or getattr(env, "package", None)
    if not pkg:
        raise ValueError("package is required (arg package or env.package)")

    fg = get_foreground_package(env=env, debug=False)
    ok = (fg == pkg)

    if debug:
        log(f"[APP] in_foreground={ok} expected={pkg} actual={fg}")
    return ok


# ==========================================================
# 범위 내 이미지 탐색 후 터치 유틸리티
#  - tap_images: 특정 영역 내에서 템플릿 이미지 여러 개 탐색 후 터치
# ==========================================================
def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def _normalize_region(region: Tuple[int, int, int, int], screen_w: int, screen_h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = region

    # 1) int 변환
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

    # 2) 좌표 정렬(뒤집힘 방지: 핵심)
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    # 3) clamp
    x1 = _clamp_int(x1, 0, screen_w - 1)
    y1 = _clamp_int(y1, 0, screen_h - 1)
    x2 = _clamp_int(x2, 1, screen_w)
    y2 = _clamp_int(y2, 1, screen_h)

    # 4) 최소 크기 보장
    if x2 <= x1:
        x2 = min(screen_w, x1 + 1)
    if y2 <= y1:
        y2 = min(screen_h, y1 + 1)

    return x1, y1, x2, y2

def _get_region_from_poco(layer_poco, screen_w: int = None, screen_h: int = None, debug: bool = False):
    """
    ✅ Poco 레이어 범위(region) 산출 안정화 (통합판/수정)

    포인트:
      - get_position/get_size (정규화)에서 ref(center/size)를 잡고
      - bounds 후보(bbox/rect + xy_swap 포함)를 만들되
      - ref와의 center/size mismatch를 강하게 페널티로 주어,
        bounds_rect / xy_swap 오해석이 면적만으로 이기는 현상을 차단한다.

    반환: (x1,y1,x2,y2) 픽셀 bbox
    """
    if layer_poco is None or not screen_w or not screen_h:
        return None

    W, H = int(screen_w), int(screen_h)
    full = float(W) * float(H)

    def _is_norm_vals(vals) -> bool:
        try:
            m = max([abs(float(v)) for v in vals])
            return m <= 1.5  # 0~1 근처 + 약간의 오차 허용
        except Exception:
            return False

    def _clip_area(x1, y1, x2, y2) -> float:
        xx1 = max(0, min(W, x1))
        yy1 = max(0, min(H, y1))
        xx2 = max(0, min(W, x2))
        yy2 = max(0, min(H, y2))
        return float(max(0, xx2 - xx1) * max(0, yy2 - yy1))

    def _mk_bbox_from_center_size(cx, cy, sw, sh):
        return (cx - sw / 2.0, cy - sh / 2.0, cx + sw / 2.0, cy + sh / 2.0)

    def _rot_norm_point(cx, cy, rot):
        if rot == 0:
            return cx, cy
        if rot == 90:
            return (1.0 - cy), cx
        if rot == 180:
            return (1.0 - cx), (1.0 - cy)
        if rot == 270:
            return cy, (1.0 - cx)
        return cx, cy

    def _rot_norm_size(sw, sh, rot):
        if rot in (90, 270):
            return sh, sw
        return sw, sh

    def _clamp_penalty(raw_bbox_px, norm_bbox_px) -> int:
        rx1, ry1, rx2, ry2 = raw_bbox_px
        nx1, ny1, nx2, ny2 = norm_bbox_px
        return int(abs(rx1 - nx1) + abs(ry1 - ny1) + abs(rx2 - nx2) + abs(ry2 - ny2))

    # ref: pos/size에서 얻은 "기대 중심/크기"(normalized) → bounds 후보 검증에 사용
    ref_center_size = None  # (rcx, rcy, rsw, rsh) normalized

    def _score_bbox(raw_bbox_px, tag: str):
        rx1, ry1, rx2, ry2 = raw_bbox_px
        norm = _normalize_region(
            (int(round(rx1)), int(round(ry1)), int(round(rx2)), int(round(ry2))),
            W, H
        )
        area = _clip_area(*norm)

        # 너무 작은 건 제거
        if area < 16:
            return None
        # 거의 풀스크린은 루트뷰 오해 가능성 → 제거
        if area > full * 0.92:
            return None

        pen = _clamp_penalty(
            (int(round(rx1)), int(round(ry1)), int(round(rx2)), int(round(ry2))),
            norm
        )

        # 기본 점수
        score = float(area) - float(pen) * 50.0

        # 너무 작으면 약간 감점
        if area < full * 0.005:
            score *= 0.7

        # ✅ 핵심: ref 대비 center/size mismatch 페널티(오해석 후보 죽이기)
        if ref_center_size is not None:
            rcx, rcy, rsw, rsh = ref_center_size

            cx = ((norm[0] + norm[2]) / 2.0) / float(W)
            cy = ((norm[1] + norm[3]) / 2.0) / float(H)
            sw = (norm[2] - norm[0]) / float(W)
            sh = (norm[3] - norm[1]) / float(H)

            center_diff = abs(cx - rcx) + abs(cy - rcy)
            size_diff   = abs(sw - rsw) + abs(sh - rsh)

            # 면적 스케일(full)에 맞춘 강한 페널티
            # (bounds_rect_xy_swap 같은 오해석이 area로 이기는걸 막는 목적)
            score -= (center_diff * full * 1.2)
            score -= (size_diff   * full * 1.0)

        return (score, area, pen, tag, norm)

    candidates = []

    # ------------------------------------------------------
    # 1) get_position + get_size 후보 생성 + ref 확보
    # ------------------------------------------------------
    try:
        pos = layer_poco.get_position()
        size = layer_poco.get_size()
        if pos and size and len(pos) == 2 and len(size) == 2:
            cx, cy = float(pos[0]), float(pos[1])
            sw, sh = float(size[0]), float(size[1])

            if _is_norm_vals([cx, cy, sw, sh]):
                # ref는 "원본 pos/size" 기준으로 잡는다(가장 일반적으로 맞음)
                ref_center_size = (cx, cy, sw, sh)

                base_variants = [
                    (cx, cy, sw, sh, "pos/size"),
                    (cy, cx, sw, sh, "pos/size_xy_swap"),
                    (cx, cy, sh, sw, "pos/size_wh_swap"),
                    (cy, cx, sh, sw, "pos/size_xywh_swap"),
                ]

                for (pcx, pcy, psw, psh, base_tag) in base_variants:
                    for rot in (0, 90, 180, 270):
                        rcx, rcy = _rot_norm_point(pcx, pcy, rot)
                        rsw, rsh = _rot_norm_size(psw, psh, rot)
                        x1n, y1n, x2n, y2n = _mk_bbox_from_center_size(rcx, rcy, rsw, rsh)
                        raw = (x1n * W, y1n * H, x2n * W, y2n * H)
                        item = _score_bbox(raw, f"{base_tag}_rot{rot}")
                        if item:
                            candidates.append(item)
            else:
                # pos/size가 px로 온 경우
                raw = (cx - sw / 2.0, cy - sh / 2.0, cx + sw / 2.0, cy + sh / 2.0)
                item = _score_bbox(raw, "pos/size_px")
                if item:
                    candidates.append(item)
    except Exception:
        pass

    # ------------------------------------------------------
    # 2) get_bounds 후보 생성: bbox/rect + xy_swap
    #    ※ ref_center_size가 있으면 mismatch 페널티로 오해석 후보가 자동 탈락
    # ------------------------------------------------------
    try:
        bd = layer_poco.get_bounds()
        if bd and len(bd) == 4:
            x1, y1, x3, y3 = [float(v) for v in bd]  # 이름 헷갈리지 않게 정리

            if _is_norm_vals([x1, y1, x3, y3]):
                # normalized일 때:
                # - bbox 후보: (x1,y1,x2,y2) = (x1,y1,x3,y3)
                # - rect 후보: (x,y,w,h) = (x1,y1,x3,y3)  → (x1, y1, x1+x3, y1+y3)
                raw_bbox = (x1 * W, y1 * H, x3 * W, y3 * H)
                raw_rect = (x1 * W, y1 * H, (x1 + x3) * W, (y1 + y3) * H)

                # xy swap 후보 (normalized 값은 0~1이므로 swap도 같은 스케일로 생성)
                raw_bbox_s = (y1 * W, x1 * H, y3 * W, x3 * H)
                raw_rect_s = (y1 * W, x1 * H, (y1 + y3) * W, (x1 + x3) * H)

            else:
                # px일 때:
                # - bbox 후보: (x1,y1,x2,y2) = (x1,y1,x3,y3)  (x3>x1 && y3>y1이면 대개 bbox)
                # - rect 후보: (x,y,w,h)로 온 케이스도 있어 방어: (x1, y1, x1+x3, y1+y3)
                raw_bbox = (x1, y1, x3, y3)
                raw_rect = (x1, y1, x1 + x3, y1 + y3)

                # xy swap 후보
                raw_bbox_s = (y1, x1, y3, x3)
                raw_rect_s = (y1, x1, y1 + y3, x1 + x3)

            for raw, tag in [
                (raw_bbox,  "bounds_bbox"),
                (raw_rect,  "bounds_rect"),
                (raw_bbox_s,"bounds_bbox_xy_swap"),
                (raw_rect_s,"bounds_rect_xy_swap"),
            ]:
                item = _score_bbox(raw, tag)
                if item:
                    candidates.append(item)

    except Exception:
        pass

    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0], reverse=True)
    best_score, best_area, best_pen, best_tag, best_bbox = candidates[0]

    if debug:
        log(f"[get_region] chosen={best_tag} score={best_score:.1f} area={best_area:.0f} clamp_pen={best_pen} bbox={best_bbox}")

    return best_bbox


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def _dedupe_points(points: List[Tuple[float, float, float]], radius: int = 18) -> List[Tuple[float, float, float]]:
    """한 화면 내 근접 좌표 중복 제거(스크롤 페이지 간 dedupe는 의도적으로 하지 않음)."""
    out: List[Tuple[float, float, float]] = []
    r = float(radius)
    for x, y, conf in sorted(points, key=lambda t: (-t[2], t[1], t[0])):  # conf desc 우선
        dup = False
        for ox, oy, _ in out:
            if abs(x - ox) <= r and abs(y - oy) <= r:
                dup = True
                break
        if not dup:
            out.append((float(x), float(y), float(conf)))
    out.sort(key=lambda t: (t[1], t[0]))  # 탭 순서: 좌상단 → 우하단
    return out


def _map_xy_to_device_resolution(x: float, y: float, shot_w: int, shot_h: int) -> Tuple[int, int, int, int]:
    """
    스크린샷 해상도(shot_w/shot_h)와 디바이스 입력 해상도(device().get_current_resolution())가 다르면
    좌표를 비율로 스케일링해서 ADB input tap이 실제 눌러야 할 위치로 맞춘다.
    """
    xi, yi = int(round(x)), int(round(y))
    try:
        dw, dh = device().get_current_resolution()
        dw, dh = int(dw), int(dh)
        if dw > 0 and dh > 0 and (dw != shot_w or dh != shot_h):
            xi = int(round(x * dw / shot_w))
            yi = int(round(y * dh / shot_h))
        # clamp
        xi = max(1, min(xi, dw - 1))
        yi = max(1, min(yi, dh - 1))
        return xi, yi, dw, dh
    except Exception:
        # fallback: 스샷 해상도 기준으로 clamp
        xi = max(1, min(xi, shot_w - 1))
        yi = max(1, min(yi, shot_h - 1))
        return xi, yi, shot_w, shot_
        
class TapNoEffectError(RuntimeError):
    """탭 명령은 수행됐으나 화면상 변화(반응)가 감지되지 않을 때"""


def _roi_changed(before_img, after_img, x: int, y: int, *, r: int = 60, mean_abs_thr: float = 2.0) -> bool:
    """
    탭 주변 ROI 픽셀 변화 여부로 '무반응'을 판정.
    - r: ROI 반경(대략 50~80 권장)
    - mean_abs_thr: 평균 절대차 임계값(화면/압축 노이즈에 따라 1.5~4.0 권장)
    """
    if before_img is None or after_img is None:
        return True  # 검증 불가면 무반응으로 단정하지 않음(보수)

    try:
        bh, bw = before_img.shape[:2]
        ah, aw = after_img.shape[:2]
        if (bh != ah) or (bw != aw):
            return True  # 해상도 다르면 비교 불가 -> 무반응 단정 X

        x1 = max(0, x - r); y1 = max(0, y - r)
        x2 = min(bw, x + r); y2 = min(bh, y + r)

        if (x2 - x1) < 10 or (y2 - y1) < 10:
            return True

        b = before_img[y1:y2, x1:x2]
        a = after_img[y1:y2, x1:x2]

        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        mean_abs = float(diff.mean())

        return mean_abs >= float(mean_abs_thr)
    except Exception:
        return True


def _tap_xy(
    x: float, y: float,
    shot_w: int, shot_h: int,
    method: str = "adb",
    debug: bool = False,
    *,
    env=None,
    effect_check: bool = True,          # ✅ 무반응 체크 on/off
    effect_wait_sec: float = 0.40,      # ✅ 탭 후 반응 대기(0.25~0.45) - 높을 수록 민감
    effect_roi_r: int = 90,             # ✅ ROI 반경(60~110) - 높을 수록 민감
    effect_mean_abs_thr: float = 0.35,  # ✅ ROI 변화 임계(0.25 ~ 2.0) - 낮을 수록 민감
    verify_fn=None,                     # ✅ (선택) 앱별 검증 콜백: (env)->bool
) -> bool:
    """
    - 탭 수행
    - (선택) 무반응이면 TapNoEffectError 발생
    - 예외 발생 시:
        (B) socket broken 1회 복구 시도
        (C) env.handle_exceptions는 1회만 호출
      이후 1회 재시도
    """
    env = use_env(env)
    used_exc_handler = False
    handler = getattr(env, "handle_exceptions", None) if env is not None else None

    def _do_tap_once():
        m = (method or "adb").lower()

        # 탭 전 이미지(무반응 판정용)
        before = None
        if effect_check:
            try:
                before = G.DEVICE.snapshot()
            except Exception:
                before = None

        if m == "airtest":
            if debug:
                log(f"[tap_xy] tap_method=airtest touch @{x:.1f},{y:.1f}")
            touch((x, y))
        else:
            # adb(또는 auto/unknown은 adb로)
            tx, ty, dw, dh = _map_xy_to_device_resolution(x, y, shot_w, shot_h)
            if debug:
                log(f"[tap_xy] tap_method=adb input tap @{tx},{ty} (from {x:.1f},{y:.1f}, shot={shot_w}x{shot_h} -> dev={dw}x{dh})")

            out = shell(f"input tap {tx} {ty}")
            if isinstance(out, str):
                msg = out.strip()
                if msg and any(k in msg for k in ("Must be root", "Permission denied", "not found", "inaccessible")):
                    raise RuntimeError(msg)

        # 탭 후 반응 대기
        if effect_check and effect_wait_sec:
            time.sleep(float(effect_wait_sec))

        # (선택) 앱별 검증(가장 신뢰)
        if callable(verify_fn):
            ok = bool(verify_fn())
            if not ok:
                raise TapNoEffectError("tap no-effect (verify_fn false)")
            step(f"[TAP_XY] tap: PASS ✅ - {x},{y}")
            return True

        # (기본) ROI 변화 검증
        if effect_check:
            after = None
            try:
                after = G.DEVICE.snapshot()
            except Exception:
                after = None

            # ROI 비교 좌표는 '디바이스 스샷 좌표계' 기준
            cx = int(round(x))
            cy = int(round(y))
            if not _roi_changed(before, after, cx, cy, r=effect_roi_r, mean_abs_thr=effect_mean_abs_thr):
                raise TapNoEffectError("tap no-effect (roi unchanged)")
        step(f"[TAP_XY] tap: PASS ✅ - {x},{y}")
        return True

    # ✅ 2회만 시도(초기 + 1회 재시도)
    last_err = None
    for attempt in (1, 2):
        try:
            return _do_tap_once()

        except Exception as e:
            last_err = e

            # (B) socket broken이면 1회차에서만 복구 후 재시도
            if attempt == 1 and _handle_socket_broken(e, env=env, where="[TAP_XY]"):
                continue

            # ✅ TapNoEffectError(roi unchanged / verify_fn false 포함)면:
            # 예외처리기 1회 수행 후 "무조건" 1회 재시도
            is_tap_noeffect = isinstance(e, TapNoEffectError)
            noeffect_reason = str(e)

            if attempt == 1:
                # (C) 예외 처리기 1회만
                if (not used_exc_handler) and callable(handler):
                    used_exc_handler = True
                    try:
                        ret = handler(e, env)
                        count = int(ret or 0)
                    except Exception as he:
                        step(f"[TAP_XY] handle_exceptions 에러: {he}", True)
                        count = 0

                    # 기존: count > 0일 때만 재시도
                    if count > 0:
                        step(f"[TAP_XY] 예외 처리기로 {count}개 rule 처리 → tap 재시도")
                        continue

                # 🔥 변경 핵심:
                # handler가 0을 반환해도 TapNoEffectError면 1회는 재탭
                if is_tap_noeffect:
                    step(f"[TAP_XY] {noeffect_reason} → 예외 처리 1회 후 tap 재시도")
                    continue

            break

    # 여기까지 왔으면 최종 실패
    soft_fail(f"[TAP_XY] tap: FAIL ❌ {last_err!r}")
    raise last_err


def _maybe_wait_settle(sec: float):
    if sec and sec > 0:
        time.sleep(sec)

def _frame_sig_np(img, sample: int = 64) -> Optional[str]:
    """스크롤 전/후 화면 변화(이동) 감지를 위한 간단 시그니처."""
    try:
        if img is None:
            return None
        if not hasattr(img, "shape"):
            return None
        h, w = img.shape[:2]
        if h <= 0 or w <= 0:
            return None

        # grayscale-ish downsample
        g = img
        if getattr(img, "ndim", 0) == 3:
            g = img.mean(axis=2)

        ys = np.linspace(0, h - 1, num=sample, dtype=int)
        xs = np.linspace(0, w - 1, num=sample, dtype=int)
        small = g[np.ix_(ys, xs)].astype(np.uint8, copy=False)
        return hashlib.md5(small.tobytes()).hexdigest()
    except Exception:
        return None

def _find_all_template_safe(crop, tpl_img, *, threshold: float, rgb: bool, max_matches: int = 200):
    """
    airtest.aircv.find_all_template의 버전별 파라미터 차이를 흡수하면서
    가능한 한 많은 매칭 결과를 가져온다.
    """
    kwargs = {"threshold": threshold, "rgb": rgb}
    try:
        sig = inspect.signature(find_all_template)
        params = sig.parameters

        # 버전에 따라 max_count / maxcnt / max_results 등으로 존재할 수 있음
        for k in ("max_count", "maxcnt", "max_results", "max_result", "count"):
            if k in params:
                kwargs[k] = int(max_matches)
                break
    except Exception:
        pass

    return find_all_template(crop, tpl_img, **kwargs) or []


def _color_gate_pass(
    crop,
    tpl_img,
    cx: float,
    cy: float,
    *,
    mean_abs_max: float = 18.0,     # 평균 색상 차이 상한(낮을수록 엄격)
    pixel_diff_max: int = 35,       # 픽셀 단위 허용 오차(채널 기준, 낮을수록 엄격)
    ratio_min: float = 0.85,        # “허용 오차 이내 픽셀 비율” 하한(높을수록 엄격)
) -> bool:
    """
    템플릿 매칭 결과가 '형태는 유사하지만 색상이 다른' 오탐을 줄이기 위한 후처리 필터.
    crop(검색영역) 내에서 (cx,cy) 중심으로 템플릿 크기만큼 패치를 떠서 템플릿과 색상 유사도를 검사한다.
    """
    if crop is None or tpl_img is None:
        return True

    ch, cw = crop.shape[:2]
    th, tw = tpl_img.shape[:2]
    if tw <= 0 or th <= 0 or cw <= 0 or ch <= 0:
        return True

    # 중심좌표 -> 템플릿 bbox (crop 좌표계)
    x0 = int(round(float(cx) - tw / 2.0))
    y0 = int(round(float(cy) - th / 2.0))
    x1 = max(0, x0)
    y1 = max(0, y0)
    x2 = min(cw, x0 + tw)
    y2 = min(ch, y0 + th)

    # 겹치는 영역이 너무 작으면 판단 무의미 → 필터링하지 않음(=통과)
    if (x2 - x1) < max(4, int(tw * 0.3)) or (y2 - y1) < max(4, int(th * 0.3)):
        return True

    patch = crop[y1:y2, x1:x2]
    tpl_part = tpl_img[(y1 - y0):(y2 - y0), (x1 - x0):(x2 - x0)]

    if patch.shape[:2] != tpl_part.shape[:2]:
        return True

    # dtype 안전 변환 후 diff 계산
    a = patch.astype(np.int16)
    b = tpl_part.astype(np.int16)

    diff = np.abs(a - b)

    # 채널이 있으면 픽셀별 최대 채널 diff로 “픽셀 단위” 판정
    if diff.ndim == 3:
        per_pixel = diff.max(axis=2)
        mean_abs = float(diff.mean())  # 채널 포함 평균
    else:
        per_pixel = diff
        mean_abs = float(diff.mean())

    ratio = float((per_pixel <= int(pixel_diff_max)).mean())

    return (mean_abs <= float(mean_abs_max)) and (ratio >= float(ratio_min))

def tap_images(
    img_path: str,
    *,
    layer_poco=None,
    region: Optional[Tuple[int, int, int, int]] = None,
    threshold: float = 0.82,           # 템플릿 매칭 기준 올릴수록 엄격
    # 면밀 탐색 옵션
    threshold_floor: float = 0.35,     # 1차 실패/누락 시 여기까지 낮춰 재탐색
    threshold_step: float = 0.03,      # threshold를 내리는 간격
    max_matches: int = 100,            # find_all 결과 상한(가능하면 크게)
    region_margin_px: int = 12,        # region 가장자리 누락 방지용 마진
    settle_before_sec: float = 0.35,   # 첫 탐색 전 화면 안정화 대기
    settle_after_tap_sec: float = 0.15, # 탭 후 안정화 대기(기존 interval과 별개)

    rgb: bool = False,                  # 템플릿 매칭 시 RGB 모드 사용 여부(기본 BGR)
    # 🔎 색상 오탐 방지(형태 유사 + 색상 다른 케이스 필터)
    color_gate: bool = True,
    color_mean_abs_max: float = 18.0,   # 평균 색상 차이 상한(낮을수록 엄격) (12 ~ 24)(default: 18)
    color_pixel_diff_max: int = 35,     # 픽셀 단위 허용 오차(채널 기준, 낮을수록 엄격) (25 ~ 45)(default: 35)
    color_ratio_min: float = 0.85,      # “허용 오차 이내 픽셀 비율” 하한(높을수록 엄격) (0.78 ~ 0.92)(default: 0.85)

    # ✅ 요청하신 2-pass
    scroll_enable: bool = True,
    scroll_to_end: bool = True,
    scroll_ratio: float = 0.65,
    scroll_duration: float = 0.35,
    scroll_settle_sec: float = 0.25,
    scroll_max_swipes: int = 20,
    scroll_no_move_limit: int = 2,

    max_taps: int = 100,
    interval: float = 0.25,
    dedup_radius_px: int = 40,
    timeout_sec: float = 120.0,
    tap_method: str = "adb",   # ✅ 기본 adb 탭
    env=None,  # ✅ click_core 처럼 예외 처리기(env.handle_exceptions) 연동

    # (호환) 기본 인자 - 본 모드에선 사용하지 않음
    target_taps: Optional[int] = None,  # ✅ 목표 탭 수(없으면 첫 탐색 결과로 고정)
    enforce_target: bool = True,        # ✅ 목표 미달이면 조기 종료 금지
    stall_max_loops: int = 3,          # ✅ 목표 미달 상태에서 매칭 불가/소진 시 재시도 한도

    debug: bool = False,
) -> int:
    """
    ✅ 단순/안전 2-pass:
      1) 첫 화면 snapshot 1회 → 매칭 포인트 전부 탭
      2) 스크롤 가능하면 끝까지 스크롤
      3) 마지막 화면 snapshot 1회 → 매칭 포인트 전부 탭

    주의: “중간 페이지”에만 존재하는 포인트까지 전부 처리해야 한다면
          추후 '스크롤하면서 각 페이지마다 탭' 모드로 확장하는 것을 권장.
    """
    t0 = time.time()
    taps = 0
    env = use_env(env)

    # 템플릿 로드
    try:
        tpl_img = imread(img_path)
        if tpl_img is None:
            soft_fail(f"[TAP_IMAGES] template load: FAIL ❌ {img_path}")
            return 0
    except Exception as e:
        soft_fail(f"[TAP_IMAGES] imread err: FAIL ❌ {e!r}")
        return 0

    def _scan_points_once():
        if settle_before_sec:
            _maybe_wait_settle(settle_before_sec)

        screen = G.DEVICE.snapshot()
        if screen is None:
            return [], None, None, None

        h, w = screen.shape[:2]

        # region 결정
        region_this = region
        if region_this is None and layer_poco is not None:
            try:
                region_this = _get_region_from_poco(layer_poco, w, h)
            except Exception as e:
                soft_fail(f"[TAP_IMAGES] _get_region_from_poco err: FAIL ❌ {e!r}")
                region_this = None

        # region 정규화 + margin
        if region_this is None:
            x1, y1, x2, y2 = 0, 0, w, h
        else:
            x1, y1, x2, y2 = _normalize_region(region_this, w, h)
            m = int(region_margin_px or 0)
            x1 = max(0, x1 - m); y1 = max(0, y1 - m)
            x2 = min(w, x2 + m); y2 = min(h, y2 + m)

        crop = screen[y1:y2, x1:x2]
        if crop is None:
            return [], w, h, (x1, y1, x2, y2)

        ch, cw = crop.shape[:2]

        # 템플릿이 crop보다 큰 경우: 이번 pass는 0포인트
        th0, tw0 = tpl_img.shape[:2]
        if (cw < tw0 or ch < th0):
            if debug:
                log(f"[tap_images] skip: template({tw0}x{th0}) > crop({cw}x{ch}). region=({x1},{y1},{x2},{y2})")
            return [], w, h, (x1, y1, x2, y2)

        # threshold hi -> lo로 면밀 탐색
        th = float(threshold)
        lo = float(threshold_floor)
        thr_step = float(threshold_step) if threshold_step else 0.0
        t_list = [th] if thr_step <= 0 else []
        if thr_step > 0:
            cur = th
            while cur >= lo - 1e-9:
                t_list.append(round(cur, 4))
                cur -= thr_step

        pts = []
        seen = set()
        for tcur in t_list:
            found = _find_all_template_safe(
                crop,
                tpl_img,
                threshold=float(tcur),
                rgb=bool(rgb),
                max_matches=int(max_matches),
            ) or []

            for mobj in found:
                cx, cy = mobj.get("result", (None, None))
                if cx is None or cy is None:
                    continue

                if color_gate:
                    if not _color_gate_pass(
                        crop, tpl_img, float(cx), float(cy),
                        mean_abs_max=float(color_mean_abs_max),
                        pixel_diff_max=int(color_pixel_diff_max),
                        ratio_min=float(color_ratio_min),
                    ):
                        continue

                gx, gy = float(cx + x1), float(cy + y1)
                key = (int(round(gx)), int(round(gy)))
                if key in seen:
                    continue
                seen.add(key)
                conf = float(mobj.get("confidence", 0.0) or 0.0)
                pts.append((gx, gy, conf))

            if len(pts) >= max(20, int(max_matches * 0.6)):
                break

        pts.sort(key=lambda t: (t[1], t[0]))
        pts = _dedupe_points([(x, y, c) for x, y, c in pts], radius=int(dedup_radius_px))

        if debug:
            log(f"[tap_images] scan: points={len(pts)} in region=({x1},{y1},{x2},{y2})")

        return pts, w, h, (x1, y1, x2, y2)

    def _tap_points(points, w, h):
        nonlocal taps
        if not points:
            return

        for (gx, gy, conf) in points:
            if taps >= int(max_taps):
                soft_fail(f"[TAP_IMAGES] stop(FAIL): reached max_taps={max_taps}")
                return
            if (time.time() - t0) >= float(timeout_sec):
                soft_fail(f"[TAP_IMAGES] stop(FAIL): timeout {timeout_sec}s")
                return

            if debug:
                log(f"[tap_images] tap#{taps+1} at ({gx:.1f},{gy:.1f}) conf={conf}")

            _tap_xy(
                gx, gy,
                shot_w=int(w), shot_h=int(h),
                method=tap_method,
                debug=debug,
                env=env,
                effect_check=True,
            )
            taps += 1
            _maybe_wait_settle(settle_after_tap_sec)
            time.sleep(max(0.02, float(interval)))

    # 1) 첫 화면: 캡쳐 1회 + 전부 탭
    pts1, w1, h1, _ = _scan_points_once()
    if w1 is None:
        return 0
    _tap_points(pts1, w1, h1)

    # 2) 끝까지 스크롤(가능하면)
    scrolled = False
    if scroll_enable and scroll_to_end:
        no_move = 0
        for i in range(int(scroll_max_swipes)):
            if (time.time() - t0) >= float(timeout_sec):
                break

            before = G.DEVICE.snapshot()
            sig1 = _frame_sig_np(before)

            cx = int(w1 * 0.5)
            y_start = int(h1 * (0.5 + float(scroll_ratio) / 2))
            y_end   = int(h1 * (0.5 - float(scroll_ratio) / 2))
            swipe((cx, y_start), (cx, y_end), duration=float(scroll_duration))
            _maybe_wait_settle(scroll_settle_sec)

            after = G.DEVICE.snapshot()
            sig2 = _frame_sig_np(after)

            if sig1 is not None and sig2 is not None and sig1 == sig2:
                no_move += 1
                if debug:
                    log(f"[tap_images] scroll: no-move #{no_move} (i={i+1})")
                if no_move >= int(scroll_no_move_limit):
                    break
            else:
                no_move = 0
                scrolled = True

        if debug:
            log(f"[tap_images] scroll_to_end done. scrolled={scrolled}")

    # 3) 스크롤 했으면 마지막 화면: 캡쳐 1회 + 전부 탭
    if scrolled:
        pts2, w2, h2, _ = _scan_points_once()
        if w2 is not None:
            _tap_points(pts2, w2, h2)

    if taps <= 0:
        soft_fail("[TAP_IMAGES] no match: FAIL ❌ - 0 taps")
    else:
        step(f"[OK] tap_images: PASS ✅ - {taps} taps")
    return int(taps)
# 범위 내 이미지 탐색 후 터치 유틸리티 END =======================================

# ====================================================================
# 이미지 면밀 탐색 헬퍼
# ====================================================================
def _to_px_point(p, sw: int, sh: int):
    """
    poco get_position()이 (0~1) 정규화로 오거나, px로 오거나 둘 다 대응.
    """
    if not p or len(p) < 2:
        return None
    x, y = float(p[0]), float(p[1])

    # normalized
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return int(round(x * sw)), int(round(y * sh))

    # already px
    return int(round(x)), int(round(y))


def _crop_by_center(screen, cx: int, cy: int, half_w: int, half_h: int):
    sh, sw = screen.shape[:2]
    x1 = max(0, cx - half_w)
    y1 = max(0, cy - half_h)
    x2 = min(sw, cx + half_w)
    y2 = min(sh, cy + half_h)
    return screen[y1:y2, x1:x2], (x1, y1, x2, y2)

def _phash_64(gray: np.ndarray) -> int:
    g = gray
    if g is None:
        return 0

    # ✅ 알파/컬러/그레이 모두 수용 → 그레이로 통일
    if g.ndim == 3:
        if g.shape[2] == 4:
            g = cv2.cvtColor(g, cv2.COLOR_RGBA2GRAY)
        else:
            g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)
    elif g.ndim != 2:
        # 이상 케이스 방어
        g = np.array(g, dtype=np.uint8)
        if g.ndim == 3 and g.shape[2] == 4:
            g = cv2.cvtColor(g, cv2.COLOR_RGBA2GRAY)
        elif g.ndim == 3:
            g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)

    g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA)
    g = np.float32(g)
    dct = cv2.dct(g)
    block = dct[:8, :8].copy()
    block[0, 0] = 0.0
    med = np.median(block)
    bits = (block > med).astype(np.uint8).flatten()
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return int(val)

def _to_px_bounds(bounds, sw: int, sh: int):
    """
    Poco get_bounds() 호환:
    - (x1,y1,x2,y2) normalized  ✅ (대부분)
    - (x,y,w,h) normalized      (드묾)
    - (x1,y1,x2,y2) px
    - (x,y,w,h) px
    """
    # dict 형태면 (x,y,w,h)로 취급
    if isinstance(bounds, dict):
        x = float(bounds.get("x", 0))
        y = float(bounds.get("y", 0))
        w = float(bounds.get("width", 0))
        h = float(bounds.get("height", 0))

        # normalized?
        if 0 <= x <= 1.5 and 0 <= y <= 1.5 and 0 < w <= 1.5 and 0 < h <= 1.5:
            x1 = int(round(x * sw))
            y1 = int(round(y * sh))
            x2 = int(round((x + w) * sw))
            y2 = int(round((y + h) * sh))
        else:
            x1 = int(round(x))
            y1 = int(round(y))
            x2 = int(round(x + w))
            y2 = int(round(y + h))

        x1 = max(0, min(sw - 1, x1))
        y1 = max(0, min(sh - 1, y1))
        x2 = max(1, min(sw, x2))
        y2 = max(1, min(sh, y2))
        return x1, y1, x2, y2

    # tuple/list 형태
    a, b, c, d = bounds
    a = float(a); b = float(b); c = float(c); d = float(d)

    # 1) normalized 후보
    if 0 <= a <= 1.5 and 0 <= b <= 1.5 and 0 <= c <= 1.5 and 0 <= d <= 1.5:
        # (x1,y1,x2,y2) normalized 이면 보통 c>a, d>b
        if c >= a and d >= b:
            x1 = int(round(a * sw))
            y1 = int(round(b * sh))
            x2 = int(round(c * sw))
            y2 = int(round(d * sh))
        else:
            # (x,y,w,h) normalized fallback
            x1 = int(round(a * sw))
            y1 = int(round(b * sh))
            x2 = int(round((a + c) * sw))
            y2 = int(round((b + d) * sh))
    else:
        # 2) px 후보
        # (x1,y1,x2,y2) px 이면 보통 c>a, d>b
        if c >= a and d >= b:
            x1 = int(round(a))
            y1 = int(round(b))
            x2 = int(round(c))
            y2 = int(round(d))
        else:
            # (x,y,w,h) px fallback
            x1 = int(round(a))
            y1 = int(round(b))
            x2 = int(round(a + c))
            y2 = int(round(b + d))

    x1 = max(0, min(sw - 1, x1))
    y1 = max(0, min(sh - 1, y1))
    x2 = max(1, min(sw, x2))
    y2 = max(1, min(sh, y2))
    return x1, y1, x2, y2

def _center_crop_to_aspect(img: np.ndarray, aspect: float) -> np.ndarray:
    h, w = img.shape[:2]
    if h <= 1 or w <= 1:
        return img
    cur = w / float(h)
    if abs(cur - aspect) < 1e-6:
        return img
    if cur > aspect:
        new_w = int(round(h * aspect))
        x1 = max(0, (w - new_w) // 2)
        x2 = min(w, x1 + new_w)
        return img[:, x1:x2]
    else:
        new_h = int(round(w / aspect))
        y1 = max(0, (h - new_h) // 2)
        y2 = min(h, y1 + new_h)
        return img[y1:y2, :]

def _hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def _ncc_same_size(a_gray: np.ndarray, b_gray: np.ndarray) -> float:
    if a_gray.ndim != 2:
        a_gray = cv2.cvtColor(a_gray, cv2.COLOR_RGB2GRAY)
    if b_gray.ndim != 2:
        b_gray = cv2.cvtColor(b_gray, cv2.COLOR_RGB2GRAY)

    a = cv2.normalize(a_gray, None, 0, 255, cv2.NORM_MINMAX)
    b = cv2.normalize(b_gray, None, 0, 255, cv2.NORM_MINMAX)
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    return float(res[0, 0])  # -1~1

def _to_hsv(img: np.ndarray, *, rgb: bool) -> np.ndarray:
    img = np.asarray(img)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR if not rgb else cv2.COLOR_GRAY2RGB)
    if img.shape[2] == 4:
        img = img[:, :, :3]
    code = cv2.COLOR_RGB2HSV if rgb else cv2.COLOR_BGR2HSV
    return cv2.cvtColor(img, code)

def _to_gray(img: np.ndarray, *, rgb: bool) -> np.ndarray:
    img = np.asarray(img)
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        img = img[:, :, :3]
    code = cv2.COLOR_RGB2GRAY if rgb else cv2.COLOR_BGR2GRAY
    return cv2.cvtColor(img, code)

def _color_signature_score(c_img, t_img, *, rgb: bool, s_min: int, v_min: int, debug: bool = False,
                          hue_gate_deg: float = 18.0) -> float:
    """
    단색 배지(배경색 + 흰 글자)에서 안정적으로 '배경색'만 비교하도록 개선.
    - 흰 글자/저채도 픽셀을 강하게 배제
    - 채도 상위 퍼센타일만 사용해 배경색 hue를 추정
    """
    import numpy as np, cv2, math

    if c_img is None or t_img is None:
        return 0.0

    c = c_img
    t = t_img

    # HSV 변환
    if rgb:
        c_hsv = cv2.cvtColor(c, cv2.COLOR_RGB2HSV)
        t_hsv = cv2.cvtColor(t, cv2.COLOR_RGB2HSV)
    else:
        c_hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        t_hsv = cv2.cvtColor(t, cv2.COLOR_BGR2HSV)

    cH, cS, cV = cv2.split(c_hsv)
    tH, tS, tV = cv2.split(t_hsv)

    # 1) 기본 마스크: 채도/밝기 컷
    #    (기존보다 살짝 보수적으로: 흰 글자/연한 테두리 배제 목적)
    s_cut = max(int(s_min), 80)
    v_cut = max(int(v_min), 60)
    c_mask0 = ((cS >= s_cut) & (cV >= v_cut)).astype(np.uint8) * 255
    t_mask0 = ((tS >= s_cut) & (tV >= v_cut)).astype(np.uint8) * 255

    # 2) "고채도 상위 픽셀만" 남기기 (배경색 중심)
    def top_sat_mask(S, base_mask, pct=70):
        vals = S[base_mask > 0]
        if vals.size < 40:
            return None
        thr = np.percentile(vals, pct)  # 채도 상위 pct%
        m = ((S >= thr) & (base_mask > 0)).astype(np.uint8) * 255
        if cv2.countNonZero(m) < 40:
            return None
        return m

    c_mask = top_sat_mask(cS, c_mask0, pct=70)
    if c_mask is None:
        c_mask = c_mask0

    t_mask = top_sat_mask(tS, t_mask0, pct=70)
    if t_mask is None:
        t_mask = t_mask0

    c_cnt = cv2.countNonZero(c_mask)
    t_cnt = cv2.countNonZero(t_mask)
    if c_cnt < 40 or t_cnt < 40:
        if debug:
            log(f"[exists_strict][color] mask too small crop={c_cnt} tpl={t_cnt}")
        return 0.0

    # 원형 평균 hue
    def mean_hue_rad(h, mask):
        vals = h[mask > 0].astype(np.float32)  # H: 0~179
        ang = vals * (2.0 * math.pi / 180.0)
        sx = float(np.mean(np.cos(ang)))
        sy = float(np.mean(np.sin(ang)))
        if abs(sx) < 1e-6 and abs(sy) < 1e-6:
            return None
        a = math.atan2(sy, sx)
        if a < 0:
            a += 2.0 * math.pi
        return a

    mc = mean_hue_rad(cH, c_mask)
    mt = mean_hue_rad(tH, t_mask)
    if mc is None or mt is None:
        return 0.0

    d = abs(mc - mt)
    d = min(d, 2.0 * math.pi - d)
    hue_diff_deg = d * (180.0 / math.pi)

    # hue gate
    if hue_diff_deg > float(hue_gate_deg):
        if debug:
            log(f"[exists_strict][color] hue_gate reject diff={hue_diff_deg:.1f}deg > {hue_gate_deg:.1f}")
        return 0.0

    hue_sim = max(0.0, 1.0 - (hue_diff_deg / float(hue_gate_deg)))

    # S/V 평균 유사도 (마스크 기반)
    cS_m = float(np.mean(cS[c_mask > 0]))
    tS_m = float(np.mean(tS[t_mask > 0]))
    cV_m = float(np.mean(cV[c_mask > 0]))
    tV_m = float(np.mean(tV[t_mask > 0]))

    sv_sim = max(0.0, 1.0 - (abs(cS_m - tS_m) / 255.0) - (abs(cV_m - tV_m) / 255.0))
    sv_sim = max(0.0, min(1.0, sv_sim))

    # ✅ 배경색 배지에서는 hue를 더 믿되, sv도 일정 반영
    color = (0.80 * hue_sim) + (0.20 * sv_sim)
    color = max(0.0, min(1.0, color))

    if debug:
        log(f"[exists_strict][color] hue_sim={hue_sim:.4f} diff={hue_diff_deg:.1f}deg sv_sim={sv_sim:.4f} color={color:.4f}")

    return color

def _find_badge_rect_candidate(region_bgr, *, rgb: bool, s_min: int, v_min: int):
    """
    region 안에서 '채도가 있는 둥근 사각형(단계 배지)' 후보를 1개 찾는다.
    반환: (x1,y1,x2,y2) or None  (region 로컬 좌표)
    """
    hsv = _to_hsv(region_bgr, rgb=rgb)
    H, S, V = cv2.split(hsv)

    mask = ((S >= s_min) & (V >= v_min)).astype(np.uint8) * 255

    # 노이즈 정리
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None

    h, w = region_bgr.shape[:2]
    best = None
    best_score = -1.0

    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 400:  # 너무 작은 것 제거
            continue

        ar = cw / float(max(1, ch))  # 배지는 가로가 더 김
        if not (1.8 <= ar <= 6.0):
            continue

        # 화면 상단부에 있는 후보를 약간 선호(배지 위치가 상단에 가까움)
        top_bonus = max(0.0, 1.0 - (y / float(max(1, h))))

        # 면적 + 비율 + 상단 보너스
        score = (area * 1.0) * (1.0 + 0.25 * top_bonus)
        if score > best_score:
            best_score = score
            best = (x, y, x+cw, y+ch)

    return best

def _verify_score(
    region_img: np.ndarray,
    tpl_img: np.ndarray,
    *,
    rgb: bool = False,             # ✅ 핵심: 기본 False(BGR)
    debug: bool = False,
    color_s_min: int = 60,
    color_v_min: int = 50,
    region_offset_xy=None,
    use_blob: bool = True,           # ✅ 추가
    use_color_sig: bool = True,      # ✅ 추가
) -> float:
    """
    후보 crop(블랍/원본/센터크롭)로 tpl과 비교해서 0~1 score 산출
    """
    crop = region_img
    tpl  = tpl_img

    th, tw = tpl.shape[:2]
    if crop is None or crop.size == 0 or th < 4 or tw < 4:
        return 0.0

    # 후보 생성 (기존 blob 탐지/expanded bbox 로직은 네 파일에 있는 걸 그대로 쓰되,
    # 여기서는 "이미 만들어진 후보 crop 리스트(cands)"만 사용한다고 가정)
    cands = []

    # ✅ blob 후보: '배지 사각형'만 뽑아서 비교 정확도 올림
    if use_blob:
        bbox = _find_badge_rect_candidate(crop, rgb=rgb, s_min=color_s_min, v_min=color_v_min)
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            pad = 6
            x1p = max(0, x1 - pad); y1p = max(0, y1 - pad)
            x2p = min(crop.shape[1], x2 + pad); y2p = min(crop.shape[0], y2 + pad)
            blob_crop = crop[y1p:y2p, x1p:x2p]

            # meta를 넣어주면 best 글로벌 좌표 디버그도 정확히 찍힘
            meta = (x1, y1, x2-x1, y2-y1, x1p, y1p, x2p, y2p)
            cands.append(("blob", blob_crop, meta))

            if debug:
                log(f"[exists_strict][blob] bbox=({x1},{y1},{x2-x1},{y2-y1}) expanded=({x1p},{y1p},{x2p},{y2p})")

    # 0) blob 기반 후보가 있으면 meta 포함해서 append
    #    (네 코드에 이미 blob bbox/expanded bbox 계산이 있으니 거기서 ("blob", crop_blob, meta)로 넣어)
    #    여기서는 안전 fallback만 제공
    cands.append(("raw", crop, None))
    c2 = _center_crop_to_aspect(crop, tw / float(th))
    if c2 is not None and c2.size > 0:
        cands.append(("center", c2, None))

    tpl_gray = _to_gray(tpl, rgb=rgb)
    tpl_hash = _phash_64(tpl_gray)

    best = 0.0
    best_tag = None
    best_meta = None

    for idx, (tag, c, meta) in enumerate(cands):
        c_rs = cv2.resize(c, (tw, th), interpolation=cv2.INTER_AREA)

        c_gray = _to_gray(c_rs, rgb=rgb)
        ncc = _ncc_same_size(c_gray, tpl_gray)            # -1~1
        ncc01 = max(0.0, min(1.0, (ncc + 1.0) / 2.0))     # 0~1

        c_hash = _phash_64(c_gray)
        ph = 1.0 - (_hamming64(c_hash, tpl_hash) / 64.0)  # 0~1

        if use_color_sig:
            color = _color_signature_score(
                c_rs, tpl,
                rgb=rgb,
                s_min=color_s_min,
                v_min=color_v_min,
                debug=debug
            )
            score = (0.40 * ncc01) + (0.25 * ph) + (0.35 * color)
        else:
            # ✅ 회색/저채도 아이콘 전용: 색 점수 제거(형태/구조 위주)
            color = 0.0
            score = (0.65 * ncc01) + (0.35 * ph)

        if debug:
            log(f"[exists_strict][verify] cand#{idx} tag={tag} ncc01={ncc01:.4f} ph={ph:.4f} color={color:.4f} score={score:.4f}")

        if score > best:
            best = score
            best_tag = tag
            best_meta = meta

    # ✅ best 후보의 좌표/박스도 확실히 출력 (meta를 네 blob 로직에서 넣어주면 여기서 찍힘)
    if debug and best_tag is not None and best_meta is not None and region_offset_xy is not None:
        try:
            # meta 포맷을 (bx,by,bw,bh,x1,y1,x2,y2) 로 유지한다는 전제
            bx, by, bw, bh, x1, y1, x2, y2 = best_meta
            cx = int(round((x1 + x2) * 0.5))
            cy = int(round((y1 + y2) * 0.5))
            ox, oy = region_offset_xy
            log(f"[exists_strict][best] tag={best_tag} bbox_global=({ox+x1},{oy+y1},{x2-x1},{y2-y1}) center=({ox+cx},{oy+cy})")
        except Exception:
            pass

    return float(best)

# 템플릿 존재 여부 검사
def exists_strict_template(
    poco_obj=None,
    template_path=None,
    *,
    threshold: float = 0.55,
    return_score: bool = False,
    debug: bool = False,
    rgb: bool = False,                 # ✅ 추가: 기본 False(BGR)
    color_s_min: int = 60,
    color_v_min: int = 50,
    bound_padding_ratio: float = 0.03,
    # 호출부에서 고정 region/screen 넣을 때
    screen_override=None,
    region_override=None,
    use_blob: bool = True,
    use_color_sig: bool = True,
    **_
):
    """
    - poco_obj bounds 기반 region을 잡고, 그 region 안에서 템플릿과의 유사도를 검증
    - rgb 기본 False(BGR). (Airtest snapshot/cv2.imread는 BGR이 일반적)
    """
    tpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if tpl is None:
        if debug:
            log(f"[exists_strict] template load failed: {template_path}")
        return (False, 0.0) if return_score else False

    screen = screen_override if screen_override is not None else G.DEVICE.snapshot()
    if screen is None:
        return (False, 0.0) if return_score else False

    sh, sw = screen.shape[:2]

    # region_override=(region, (ox,oy)) 지원
    region_offset_xy = None
    if region_override is not None:
        region, region_offset_xy = region_override
    else:
        # ✅ NEW: 기준 오브젝트가 없으면 전체 화면에서 찾기
        if poco_obj is None:
            region = screen
            region_offset_xy = (0, 0)
            if debug:
                log(f"[exists_strict][region] FULLSCREEN size=({sw}x{sh})")
        else:
            b = poco_obj.get_bounds()
            x1, y1, x2, y2 = _to_px_bounds(b, sw, sh)
            pad = float(bound_padding_ratio)
            bw = max(1, x2 - x1); bh = max(1, y2 - y1)
            rx1 = max(0, x1 - int(bw*pad))
            ry1 = max(0, y1 - int(bh*pad))
            rx2 = min(sw, x2 + int(bw*pad))
            ry2 = min(sh, y2 + int(bh*pad))
            region = screen[ry1:ry2, rx1:rx2]
            region_offset_xy = (rx1, ry1)
            if debug:
                log(f"[exists_strict][region] ({rx1},{ry1})-({rx2},{ry2}) size=({rx2-rx1}x{ry2-ry1}) pad_ratio={pad}")

    # ✅ 여기서 blob 후보를 만들고 meta를 (bx,by,bw,bh,x1,y1,x2,y2) 형태로 넣어줘야
    # _verify_score의 [best] global 좌표 로그가 정확해짐.
    score = _verify_score(
        region, tpl,
        rgb=rgb,
        debug=debug,
        color_s_min=color_s_min,
        color_v_min=color_v_min,
        region_offset_xy=region_offset_xy,
        use_blob=use_blob,
        use_color_sig=use_color_sig,
    )

    ok = score >= float(threshold)
    if debug:
        log(f"[exists_strict][poco] {os.path.basename(template_path)} score={score:.4f} threshold={threshold:.4f} -> {ok}")

    return (ok, score) if return_score else ok

# 최적의 템플릿 선택
def pick_best_template(
    badge: Optional[Any] = None,
    *,
    templates: dict,
    accept_threshold: float = 0.55,
    debug: bool = False,
    # 배지 주변을 얼마나 넓게 볼지 (배지 센터 기준)
    crop_half_w: int = 180,
    crop_half_h: int = 70,
    use_blob: bool = True,
    use_color_sig: bool = True,
    **exists_kwargs
):
    screen = G.DEVICE.snapshot()
    if screen is None:
        return None, 0.0
    sh, sw = screen.shape[:2]

    # ✅ NEW: 기준 poco_obj(badge)가 없으면 전체 화면에서 비교
    if badge is None:
        region_pack = (screen, (0, 0))  # (region, offset)
        if debug:
            log(f"[pick_best] badge=None -> FULLSCREEN compare ({sw}x{sh})")

        best_label, best_score = None, -1.0
        for label, path in templates.items():
            ok, score = exists_strict_template(
                None, path,
                return_score=True,
                threshold=accept_threshold,
                debug=debug,
                screen_override=screen,
                region_override=region_pack,
                use_blob=use_blob,
                use_color_sig=use_color_sig,
                **exists_kwargs
            )
            if debug:
                log(f"[pick_best] {label} -> ok={ok} score={score:.4f}")

            if score > best_score:
                best_score = score
                best_label = label

        if best_label is not None and best_score >= float(accept_threshold):
            return best_label, best_score
        return None, best_score

    # ✅ 1) bounds 대신 position(센터) 우선 사용
    center = None
    try:
        pos = badge.get_position()
        center = _to_px_point(pos, sw, sh)
    except Exception:
        center = None

    # ✅ 2) position이 실패하면 bounds fallback
    if center is None:
        try:
            b = badge.get_bounds()
            x1, y1, x2, y2 = _to_px_bounds(b, sw, sh)
            center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
        except Exception:
            center = None

    if center is None:
        if debug:
            log("[pick_best] failed to get center (position/bounds)")
        return None, 0.0

    cx, cy = center

    # ✅ 3) center 기준 region crop (이게 핵심)
    region, (rx1, ry1, rx2, ry2) = _crop_by_center(screen, cx, cy, int(crop_half_w), int(crop_half_h))
    region_pack = (region, (rx1, ry1))  # exists_strict_template가 global 좌표 찍을 때 필요

    if debug:
        log(f"[pick_best] screen=({sw}x{sh}) center=({cx},{cy})")
        log(f"[pick_best] region=({rx1},{ry1})-({rx2},{ry2}) size=({rx2-rx1}x{ry2-ry1})")

    best_label, best_score = None, -1.0

    # ✅ 4) 템플릿별 점수 비교 (최대 스코어 선택)
    for label, path in templates.items():
        ok, score = exists_strict_template(
            badge, path,
            return_score=True,
            threshold=accept_threshold,
            debug=debug,
            # ✅ 동일 screen/region에서만 비교 (공정)
            screen_override=screen,
            region_override=region_pack,
            **exists_kwargs
        )
        if debug:
            log(f"[pick_best] {label} -> ok={ok} score={score:.4f}")

        if score > best_score:
            best_score = score
            best_label = label

    if best_label is not None and best_score >= float(accept_threshold):
        return best_label, best_score
    return None, best_score

# ======================================================
# 특정 객체 나타나기 전까지 액션 반복
# ======================================================
def repeat_action_until_exists(poco_obj, action_fn, desc=None, timeout_sec=120.0, interval_sec=0.3):
    """
    poco_obj: 예) poco("a")
    action_fn: 반복할 액션(함수) 예) lambda: swipe((960,900),(960,300),0.4)
    """
    end = time.time() + float(timeout_sec)
    while time.time() < end:
        try:
            if poco_obj.exists():
                if desc is not None:
                    step(f"[OK] {desc}: PASS ✅ - {get_label(poco_obj)}")
                else:
                    step(f"[OK] object exists: PASS ✅ - {get_label(poco_obj)}")
                return True  # 나타남 → 종료
        except Exception:
            if desc is not None:
                soft_fail(f"[ERR] {desc}: FAIL ❌ - {get_label(poco_obj)}")
            else:
                soft_fail(f"[ERR] object exists: FAIL ❌ - {get_label(poco_obj)}")
            pass

        try:
            action_fn()  # 나타나기 전까지 액션 반복
        except Exception:
            if desc is not None:
                step(f"{desc}: 실패 ❌")
            else:
                step(f"[ERR] try action: 실패 ❌")
            pass

        time.sleep(float(interval_sec))

    return False
# 반복 액션 END ========================================


# =====================================================
# 검은 색상이 아닌 단어 찾은 후 클릭 → 추가 액션 진행
# - tap_color_words: 특정 영역 내에서 색상이 있는 단어를 찾아 클릭
# =====================================================
def _find_color_word_in_crop(
    crop_img,
    *,
    # “검정이 아닌(색 있는)” 판정 기준
    sat_min: int = 55,        # 채도 하한(높을수록 엄격)
    val_min: int = 45,        # 밝기 하한(너무 어두운 노이즈 제외)
    # 단어 묶기/필터링
    word_dilate_x: int = 18,  # 수평 팽창(글자들을 단어로 묶는 핵심)
    word_dilate_y: int = 5,   # 수직 팽창
    min_w: int = 16,
    min_h: int = 14,
    max_h_ratio: float = 0.35,  # ROI 대비 너무 큰 박스 제외
) -> List[Tuple[int, int, int, int]]:
    """
    ROI(crop) 안에서 '검정이 아닌 글자(색상 있는 글자)'를 단어 단위 박스로 검출.
    return: crop 좌표계의 (x1,y1,x2,y2) 리스트
    """
    if crop_img is None:
        return []

    h, w = crop_img.shape[:2]
    if h <= 0 or w <= 0:
        return []

    # HSV 변환 (Airtest snapshot의 채널 순서가 RGB/BGR 혼재 가능성이 있으나,
    # 채도/밝기 기반 마스크는 실전에서 큰 문제 없이 동작하는 편입니다.)
    hsv = cv2.cvtColor(crop_img, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)

    # 비검정(=색이 있는) 픽셀: 채도 >= sat_min AND 밝기 >= val_min
    mask = ((S >= sat_min) & (V >= val_min)).astype(np.uint8) * 255

    # 노이즈 정리
    mask = cv2.medianBlur(mask, 3)

    # 글자들을 단어로 묶기(수평 dilate가 핵심)
    kx = max(3, int(word_dilate_x))
    ky = max(3, int(word_dilate_y))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky))
    blob = cv2.dilate(mask, kernel, iterations=1)

    # 윤곽 검출
    contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    max_h = int(h * max_h_ratio)

    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < min_w or bh < min_h:
            continue
        if bh > max_h:
            continue
        boxes.append((x, y, x + bw, y + bh))

    # 위->아래, 좌->우 정렬
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


def tap_color_words(
    layer_poco,
    *,
    verify_fn=None,
    popup_close_fn: Callable[[], None],
    env=None,
    # 판정 파라미터(기본값은 “색상 다른 단어만” 타겟팅)
    sat_min: int = 55,          # 채도 하한
    val_min: int = 45,          # 밝기 하한
    word_dilate_x: int = 18,    # 수평 팽창
    word_dilate_y: int = 5,
    min_w: int = 16,
    min_h: int = 14,
    max_h_ratio: float = 0.35,
    # 실행 제어
    max_taps: int = 60,
    settle_after_tap_sec: float = 0.20,
    settle_after_close_sec: float = 0.20,
    dedupe_radius_px: int = 22,
    timeout_sec: float = 60.0,
    debug: bool = False,
) -> int:
    """
    layer_poco의 bounds(좌표) 내에서
    '검정이 아닌(색상 있는)' 단어를 순서대로 탭하고, 팝업 닫기를 반복.

    핵심: 탭/팝업닫기 후 화면 상태가 바뀌므로 "매 회 재스냅샷/재탐색"한다.
    """
    env = use_env(env)
    t0 = time.time()
    taps = 0
    tap_pts: List[Tuple[float, float]] = []
    used_exc_handler = False
    handler = getattr(env, "handle_exceptions", None) if env is not None else None  # ✅ 추가

    def _dedup_center(cx, cy) -> bool:
        r = float(dedupe_radius_px)
        for ox, oy in tap_pts:
            if abs(cx - ox) <= r and abs(cy - oy) <= r:
                return True
        return False

    # 루프: 매번 현재 화면에서 “다음 단어 1개”를 찾아 클릭하는 방식이 가장 안전
    while True:
        try:
            if taps >= int(max_taps):
                if debug:
                    log(f"[color_words] stop: max_taps={max_taps}")
                break
            if (time.time() - t0) >= float(timeout_sec):
                if debug:
                    log(f"[color_words] stop: timeout {timeout_sec}s")
                break

            screen = G.DEVICE.snapshot()
            if screen is None:
                if debug:
                    log("[color_words] snapshot is None")
                break

            h, w = screen.shape[:2]

            # ✅ layer 좌표는 common에 이미 있는 함수로 뽑기
            region_raw = _get_region_from_poco(layer_poco, w, h, debug=debug)
            if not region_raw:
                soft_fail("[COLOR_WORDS] get_region_from_poco: FAIL ❌ - region is None (layer bounds not available)")
                break

            x1, y1, x2, y2 = _normalize_region(region_raw, w, h)
            crop = screen[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                if debug:
                    log("[color_words] crop empty")
                break

            boxes = _find_color_word_in_crop(
                crop,
                sat_min=sat_min,
                val_min=val_min,
                word_dilate_x=word_dilate_x,
                word_dilate_y=word_dilate_y,
                min_w=min_w,
                min_h=min_h,
                max_h_ratio=max_h_ratio,
            )

            if debug:
                log(f"[color_words] boxes={len(boxes)} in region=({x1},{y1},{x2},{y2})")

            picked = None
            edge_pad = 6

            for (bx1, by1, bx2, by2) in boxes:
                cx = x1 + (bx1 + bx2) / 2.0
                cy = y1 + (by1 + by2) / 2.0

                if not (x1 <= cx < x2 and y1 <= cy < y2):
                    continue
                if (cx <= x1 + edge_pad) or (cx >= x2 - edge_pad) or (cy <= y1 + edge_pad) or (cy >= y2 - edge_pad):
                    continue

                cx = max(x1 + 1, min(cx, x2 - 2))
                cy = max(y1 + 1, min(cy, y2 - 2))

                if _dedup_center(cx, cy):
                    continue

                picked = (cx, cy, (bx1, by1, bx2, by2))
                break

            if picked is None:
                if debug:
                    log("[color_words] no new non-black word boxes; stop")
                break

            cx, cy, b = picked

            _tap_xy(
                cx, cy,
                shot_w=int(w), shot_h=int(h),
                method="adb",
                debug=debug,
                env=env,
                effect_check=True,
                verify_fn=verify_fn,
            )
            tap_pts.append((cx, cy))
            taps += 1

            time.sleep(float(settle_after_tap_sec))

            # 팝업 닫기
            try:
                popup_close_fn()
            except Exception as e:
                soft_fail(f"[COLOR_WORDS] popup_close_fn: FAIL ❌ - {e!r}")

            time.sleep(float(settle_after_close_sec))

        except Exception as e:
            # ✅ 전반 예외 발생 시: 예외처리기 1회 수행 후 재시도
            if (not used_exc_handler) and callable(handler):
                used_exc_handler = True
                step(f"[COLOR_WORDS] WARN ⚠️ unexpected error -> handle_exceptions then retry: {e!r}", True)
                try:
                    handler(e, env)
                except Exception as he:
                    step(f"[COLOR_WORDS] handle_exceptions 에러: {he!r}", True)
                time.sleep(0.3)
                continue

            # ✅ 이미 예외처리기 1회 사용했는데 또 터지면 종료
            soft_fail(f"[COLOR_WORDS] unexpected: FAIL ❌ - {e!r}")
            break
    step(f"[OK] tap_color_words: PASS ✅ - {taps} taps")
    return int(taps)
# 컬러단어 탭 END ========================================

# =====================================================
# 🖱️ 지정 레이어(ROI) 내 템플릿 기준: "살짝 위"에서 우측 끝까지 드래그 반복
#   - 완료/새로고침 버튼(종료 조건) 등장 시 반복 종료
# drag_right_from_target: 특정 영역 내에서 템플릿 이미지 여러 개 탐색 후 우측으로 드래그
# =====================================================
def drag_right_from_target(
    target,   # str(이미지 경로) 또는 poco 객체(selector 포함)
    *,
    layer_poco,
    done_poco,
    threshold: float = 0.82,
    rgb: bool = False,
    # 드래그 포인트 보정(템플릿/타겟 중심 기준 위로 이동)
    y_offset_px: int = 5,
    # 드래그 종료점(ROI 우측 끝에서 살짝 안쪽)
    end_margin_px: int = 8,
    # ROI 보정(가장자리 누락 방지)
    region_margin_px: int = 8,
    # 타이밍
    settle_before_sec: float = 0.25,
    settle_after_drag_sec: float = 0.50,
    duration: float = 0.8,
    steps: int = 200,
    # 반복 제어
    max_drags: int = 60,
    timeout_sec: float = 120.0,
    interval_on_miss_sec: float = 0.25,
    env=None,
    debug: bool = False,
) -> int:
    """
    기능 요약
      1) layer_poco 영역을 ROI로 설정 (_get_region_from_poco)
      2) ROI 내에서 target을 찾는다.
         - target이 str: 템플릿 매칭(_find_all_template_safe)으로 좌상단→우하단 우선
         - target이 poco: selector면 후보를 열거해 ROI 안쪽만 필터 후 좌상단 우선으로 1개 선택
      3) 드래그 시작점은 "타겟 중심보다 약간 위(y_offset_px)"
      4) 드래그 종료점은 ROI의 우측 끝(x2 - end_margin_px)
      5) 한 번 드래그를 시작하면, 타겟이 드래그 도중 사라져도 중단하지 않고 1회는 끝까지 수행
      6) 드래그 1회 완료 후 다시 target 탐색 → 반복
      7) done_poco(완료/새로고침 등)가 등장하면 종료

    반환: 수행한 drag 횟수
    """
    env = use_env(env)
    t0 = time.time()
    drags = 0

    is_template = isinstance(target, str)

    # 템플릿인 경우만 이미지 로드
    tpl_img = None
    if is_template:
        try:
            tpl_img = imread(target)
            if tpl_img is None:
                soft_fail(f"[DRAG_TARGET] template load: FAIL ❌ - {target}")
                return 0
        except Exception as e:
            soft_fail(f"[DRAG_TARGET] imread err: FAIL ❌ - {e!r}")
            return 0

    def _clamp_int(v, lo, hi):
        try:
            v = int(round(float(v)))
        except Exception:
            v = int(v)
        return int(max(lo, min(hi, v)))

    def _pick_poco_point_in_roi(sel, w, h, x1, y1, x2, y2):
        """
        selector(복수 매칭 가능)에서 ROI 내부 후보를 수집해
        좌상단→우하단 우선으로 1개 픽하여 (gx, gy) 반환.

        핵심 변경:
        - 후보가 하나도 없을 때, selector 대표 좌표를 '그냥 반환'하지 않는다.
        - fallback 대표 좌표도 ROI/edge 검증을 통과할 때만 사용하고,
            통과 못하면 (None, None)로 MISS 처리하게 한다.
        - 필요 시 hierarchy dump로 갱신을 1회 시도(특히 count/index가 불안정할 때).
        """
        edge_pad = max(6, int(region_margin_px))
        candidates = []

        def _inside_and_not_edge(cx, cy) -> bool:
            if cx is None or cy is None:
                return False
            if not (x1 <= cx < x2 and y1 <= cy < y2):
                return False
            if (cx <= x1 + edge_pad) or (cx >= x2 - edge_pad) or (cy <= y1 + edge_pad) or (cy >= y2 - edge_pad):
                return False
            return True

        def _get_center_xy(obj):
            tb = _get_region_from_poco(obj, w, h, debug=False)
            if tb:
                tx1, ty1, tx2, ty2 = map(int, tb)
                return (tx1 + tx2) / 2.0, (ty1 + ty2) / 2.0
            px, py = obj.get_position()
            return float(px) * float(w), float(py) * float(h)

        # (선택) native poco(apoco)면 dump로 갱신 1회 시도
        # - selector count()/index가 가끔 stale일 때가 있어 “후보 0개” 방지 목적
        try:
            a = getattr(env, "apoco", None)
            if a is not None and hasattr(a, "agent") and hasattr(a.agent, "hierarchy"):
                a.agent.hierarchy.dump()
        except Exception:
            pass

        # 1) sel.count() + sel[i]로 후보 열거
        n = None
        try:
            n = int(sel.count())
        except Exception:
            n = None

        if n is not None and n > 0:
            lim = min(n, 120)  # 필요 시 상향(복수 ImageView 케이스)
            for i in range(lim):
                try:
                    obj = sel[i]
                    if not obj.exists():
                        continue
                    cx, cy = _get_center_xy(obj)
                    if not _inside_and_not_edge(cx, cy):
                        continue
                    # 정렬키(y, x)
                    candidates.append((cy, cx))
                except Exception:
                    continue

        # 2) 후보가 있으면 좌상단 우선 1개 픽
        if candidates:
            candidates.sort(key=lambda t: (t[0], t[1]))
            cy, cx = candidates[0]
            return cx, cy

        # 3) 후보가 없으면 “대표 1개 fallback”은 하되, 검증 통과 시에만 반환
        #    (통과 못하면 MISS로 보내서 다음 루프에서 재탐색하게 함)
        try:
            cx, cy = _get_center_xy(sel)
            if _inside_and_not_edge(cx, cy):
                return cx, cy
            return None, None
        except Exception:
            return None, None

    while True:# 반복마다 최초 예외 처리기 수행
        handler = getattr(env, "handle_exceptions", None) if env is not None else None
        if callable(handler):
            try:
                handler(None, env)
            except Exception as he:
                step(f"[DRAG_TARGET] handle_exceptions 에러: {he}", True)
        if (time.time() - t0) >= float(timeout_sec):
            if debug:
                log(f"[DRAG_TARGET] stop: timeout {timeout_sec}s")
            break

        if drags >= int(max_drags):
            if debug:
                log(f"[DRAG_TARGET] stop: reached max_drags={max_drags}")
            break

        # 종료 조건(완료/새로고침 버튼 등장)
        try:
            if done_poco is not None and done_poco.exists():
                if debug:
                    log(f"[DRAG_TARGET] done_poco exists -> stop ({get_label(done_poco)})")
                step(f"[OK] drag_right_target: PASS ✅ - {drags} drags")
                break
        except Exception:
            pass

        # settle before
        if settle_before_sec:
            time.sleep(float(settle_before_sec))

        # 화면 캡쳐 및 ROI 계산
        screen = G.DEVICE.snapshot()
        if screen is None:
            time.sleep(0.2)
            continue

        h, w = screen.shape[:2]

        # ROI = layer_poco bbox (+ margin)
        bbox = _get_region_from_poco(layer_poco, w, h, debug=False)
        if not bbox:
            soft_fail("[DRAG_TARGET] FAIL: layer_poco bbox not found")
            time.sleep(0.2)
            continue

        lx1, ly1, lx2, ly2 = map(int, bbox)
        x1 = _clamp_int(lx1 - int(region_margin_px), 0, w - 1)
        y1 = _clamp_int(ly1 - int(region_margin_px), 0, h - 1)
        x2 = _clamp_int(lx2 + int(region_margin_px), 1, w)
        y2 = _clamp_int(ly2 + int(region_margin_px), 1, h)

        if x2 <= x1 + 10 or y2 <= y1 + 10:
            soft_fail(f"[DRAG_TARGET] FAIL: invalid region=({x1},{y1},{x2},{y2})")
            time.sleep(0.2)
            continue

        # ------------------------------------------------------------
        # 1) target 좌표(gx, gy) 산출
        #    - 드래그 시작과 동시에 타겟이 사라지는 시스템 대응:
        #      드래그 중 exists 재검증/재탐색 금지(좌표 확정 후 1회 끝까지)
        # ------------------------------------------------------------
        gx = gy = None
        conf = None

        if not is_template:
            # target이 poco(selector 포함)인 경우
            try:
                if not target.exists():
                    if debug:
                        log(f"[DRAG_TARGET] MISS - target poco not exists: {get_label(target)}")
                    time.sleep(float(interval_on_miss_sec))
                    continue

                gx, gy = _pick_poco_point_in_roi(target, w, h, x1, y1, x2, y2)
                if debug:
                    log(f"[DRAG_TARGET] poco pick -> ({gx},{gy}) in region=({x1},{y1},{x2},{y2})")
                if gx is None or gy is None:
                    if debug:
                        log(f"[DRAG_TARGET] MISS - cannot resolve poco point: {get_label(target)}")
                    time.sleep(float(interval_on_miss_sec))
                    continue

                conf = 1.0  # poco 기반은 confidence 개념이 없으니 1.0으로 둔다

            except Exception as e:
                soft_fail(f"[DRAG_TARGET] target poco err: FAIL ❌ - {e!r}")
                time.sleep(float(interval_on_miss_sec))
                continue

        else:
            # target이 템플릿(str)인 경우: ROI crop에서 매칭
            crop = screen[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                time.sleep(0.2)
                continue

            th0, tw0 = tpl_img.shape[:2]
            ch, cw = crop.shape[:2]
            if (cw < tw0 or ch < th0):
                soft_fail(f"[DRAG_TARGET] FAIL:template({tw0}x{th0}) > crop({cw}x{ch}) - region=({x1},{y1},{x2},{y2})")
                return int(drags)

            found = _find_all_template_safe(
                crop, tpl_img,
                threshold=float(threshold),
                rgb=bool(rgb),
                max_matches=60,
            ) or []

            pts = []
            for mobj in found:
                cx, cy = mobj.get("result", (None, None))
                if cx is None or cy is None:
                    continue
                c = float(mobj.get("confidence", 0.0) or 0.0)
                gx2, gy2 = float(cx + x1), float(cy + y1)
                pts.append((gx2, gy2, c))

            if not pts:
                if debug:
                    log(f"[DRAG_TARGET] MISS - region=({x1},{y1},{x2},{y2}) thr={threshold}")
                time.sleep(float(interval_on_miss_sec))
                continue

            # 좌상단 → 우하단 우선
            pts.sort(key=lambda t: (t[1], t[0]))
            gx, gy, conf = pts[0]

        # 드래그 시작점: 타겟보다 '조금 위' (단, ROI 안으로 강제 클램프)
        sx = _clamp_int(gx, x1 + 2, x2 - 2)
        sy = _clamp_int(gy - int(y_offset_px), y1 + 2, y2 - 2)

        # 드래그 종료점: ROI 우측 끝(약간 안쪽), y는 고정(수평 드래그)
        ex = _clamp_int((x2 - int(end_margin_px)), x1 + 2, x2 - 2)
        ey = sy

        # 너무 짧으면 무의미
        if ex <= sx + 8:
            if debug:
                log(f"[DRAG_TARGET] SKIP - drag too short sx={sx} ex={ex} region=({x1},{y1},{x2},{y2})")
            time.sleep(float(interval_on_miss_sec))
            continue

        if debug:
            try:
                log(f"[DRAG_TARGET] drag#{drags+1} conf={float(conf):.3f} start=({sx},{sy}) end=({ex},{ey}) region=({x1},{y1},{x2},{y2})")
            except Exception:
                log(f"[DRAG_TARGET] drag#{drags+1} start=({sx},{sy}) end=({ex},{ey}) region=({x1},{y1},{x2},{y2})")

        # ✅ 여기서부터는 “무조건 1회 끝까지” (드래그 도중 타겟 disappears 해도 중단 금지)
        try:
            swipe((sx, sy), (ex, ey), duration=float(duration), steps=int(steps))
            drags += 1
        except Exception as e:
            soft_fail(f"[DRAG_TARGET] swipe err: FAIL ❌ - {e!r}")
            return int(drags)

        if settle_after_drag_sec:
            _maybe_wait_settle(settle_after_drag_sec)

    return int(drags)
        # 다음 루프에서 다시 target 탐색 (드래그 후 재탐색이 요구사항)
# 드래그 라이트 타겟 END ===============================================

# 진행률 헬퍼
def parse_progress(progress_obj):
    """
    return: (done: bool, num: int|None, den: int|None, raw: str)
    """
    try:
        if not progress_obj.exists():
            return (False, None, None, "")
        raw = progress_obj.get_text() or ""
        m = re.search(r"(\d+)\s*/\s*(\d+)", raw)
        if not m:
            return (False, None, None, raw)
        num = int(m.group(1))
        den = int(m.group(2))
        done = (den > 0 and num == den)
        return (done, num, den, raw)
    except Exception:
        return (False, None, None, "")