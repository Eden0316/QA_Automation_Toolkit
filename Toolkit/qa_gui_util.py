# ==========================================================
# 🛠️ Tool: QA GUI 공통 유틸 (HiDPI + 콘솔창 억제)
# 👤 Author: Eden Kim
# 📅 Date: 2026-08-11 - v1.0.0
#   - 신규: Toolkit GUI 도구들이 공유하는 화면/프로세스 보정 유틸
# ==========================================================
# • 목적: Tkinter 기반 QA 도구들의 두 가지 고질 문제를 한 곳에서 해결
#   1) 고해상도(4K·150% 배율) 화면에서 창이 흐릿하게 확대되는 문제
#   2) GUI에서 adb 등을 호출할 때마다 검은 cmd 창이 깜빡이는 문제
# • 사용법(각 GUI 파일 상단에서):
#     sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
#     from qa_gui_util import enable_dpi_awareness, apply_tk_scaling, silence_console_windows
#     UI_SCALE = enable_dpi_awareness()      # ⚠ 반드시 Tk 창 생성 전에
#     silence_console_windows()              # 자식 프로세스(adb 등)가 콘솔을 안 만들게
#     relaunch_without_console()             # py.exe로 실행돼 딸려온 콘솔 창 제거
#     ...
#     root = tk.Tk(); apply_tk_scaling(root, UI_SCALE)
# • 주의: DPI 인식은 프로세스당 한 번만 확정된다 — Tk 창이 만들어진 뒤에 호출하면 효과가 없다
# ==========================================================
# -*- coding: utf-8 -*-
import os
import re
import sys
import ctypes
import subprocess

# Windows 프로세스 생성 플래그
CREATE_NEW_CONSOLE = 0x00000010   # 새 콘솔 창을 띄운다(스크립트 실행처럼 출력을 봐야 할 때)
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000     # 콘솔을 아예 만들지 않는다(조용한 보조 명령용)

_WINDOW_FLAGS = CREATE_NEW_CONSOLE | DETACHED_PROCESS | CREATE_NO_WINDOW


# ----------------------------------------------------------
# 1) 고해상도(HiDPI) 대응
# ----------------------------------------------------------
def enable_dpi_awareness() -> float:
    """DPI 인식을 선언하고 화면 배율(1.0 = 100%)을 돌려준다.

    이 선언이 없으면 Windows가 앱을 100% 기준으로 그린 뒤 배율만큼 비트맵 확대해서
    글자와 그래프가 뭉개진다(4K + 150% 환경에서 특히 심함).
    ⚠ 반드시 Tk 창(및 filedialog 등 숨은 root)이 만들어지기 전에 호출해야 한다.
    """
    if os.name != "nt":
        return 1.0

    ok = False
    try:
        # Windows 10 1703+ : 모니터별 DPI 인식 v2 (배율이 다른 모니터로 옮겨도 선명)
        ok = bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
    except Exception:
        ok = False
    if not ok:
        try:
            # Windows 8.1+ : PROCESS_PER_MONITOR_DPI_AWARE
            ok = ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
        except Exception:
            ok = False
    if not ok:
        try:
            # 그 이전 버전 폴백(시스템 DPI 기준)
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    dpi = 96
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem() or 96
    except Exception:
        try:
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) or 96  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
        except Exception:
            pass

    return dpi / 96.0


def apply_tk_scaling(root, scale: float) -> None:
    """Tk의 pt→px 변환 배율을 실제 DPI에 맞춘다.

    이걸 안 하면 DPI 인식만 켜진 상태라 창은 선명해지지만 글자가 배율만큼 작아진다.
    """
    try:
        root.tk.call("tk", "scaling", scale * 96.0 / 72.0)
    except Exception:
        pass


def scale_geometry(geom: str, scale: float) -> str:
    """"740x320" / "740x320+10+10" 형태의 창 크기를 배율만큼 키운다.

    창 크기는 픽셀 단위라 Tk scaling이 건드리지 않으므로 직접 곱해야 한다.
    """
    m = re.match(r"^(\d+)x(\d+)(.*)$", geom.strip())
    if not m:
        return geom
    w, h, rest = int(m.group(1)), int(m.group(2)), m.group(3)
    return f"{int(w * scale)}x{int(h * scale)}{rest}"


# ----------------------------------------------------------
# 2) 불필요한 콘솔(cmd) 창 억제
# ----------------------------------------------------------
def silence_console_windows() -> None:
    """이 프로세스가 앞으로 만드는 자식 프로세스에 콘솔 창을 만들지 않게 한다.

    GUI 도구는 adb·getprop 같은 보조 명령을 수시로 호출하는데, 그때마다 검은 창이
    깜빡였다. subprocess.Popen의 기본 creationflags에 CREATE_NO_WINDOW를 얹어
    호출부를 일일이 고치지 않고 한 번에 막는다.

    ⚠ 호출부가 창 옵션을 명시한 경우(예: 테스트 스크립트를 CREATE_NEW_CONSOLE로
    띄우는 곳)는 의도된 것이므로 그대로 존중한다.
    """
    if os.name != "nt":
        return
    if getattr(subprocess.Popen, "_qa_no_window_patched", False):
        return

    _orig_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0)
        if not (flags & _WINDOW_FLAGS):
            kwargs["creationflags"] = flags | CREATE_NO_WINDOW
        return _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init
    subprocess.Popen._qa_no_window_patched = True


# ----------------------------------------------------------
# 3) 자기 자신에게 딸려온 콘솔 창 숨기기
# ----------------------------------------------------------
# 콘솔에 붙어 있어도 숨기면 안 되는(= 사용자의 터미널인) 프로세스들
_SHELL_NAMES = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe",
                "bash.exe", "wt.exe", "code.exe"}
# 콘솔이 "우리 때문에 생긴 것"으로 볼 수 있는 프로세스들
_PY_NAMES = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe"}


def _console_process_names():
    """현재 콘솔에 붙어 있는 프로세스들의 실행 파일 이름 목록."""
    import ctypes.wintypes as wt

    buf = (wt.DWORD * 64)()
    n = ctypes.windll.kernel32.GetConsoleProcessList(buf, 64)
    pids = set(buf[i] for i in range(min(n, 64)))
    if not pids:
        return []

    class _PE32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
    e = _PE32()
    e.dwSize = ctypes.sizeof(_PE32)
    names = []
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.th32ProcessID in pids:
                names.append(e.szExeFile.decode("mbcs", "replace").lower())
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return names


def hide_own_console(dry_run: bool = False) -> str:
    """py.exe/python.exe로 GUI를 띄울 때 딸려오는 검은 콘솔 창을 숨긴다.

    exe 런처가 `py.exe <script>.py` 형태로 GUI를 실행하면 파이썬이 콘솔 앱이라
    쓸모없는 검은 창이 같이 뜬다. 그 창을 숨긴다.

    ⚠ 사용자가 자기 터미널에서 직접 실행한 경우에는 절대 숨기면 안 된다
    (그 터미널 자체가 사라져 버린다). 그래서 콘솔에 붙어 있는 프로세스가
    전부 파이썬 계열일 때만 숨긴다 — cmd/PowerShell이 끼어 있으면 그대로 둔다.

    반환: 어떤 판단을 했는지 설명하는 문자열(진단·테스트용)
    """
    if os.name != "nt":
        return "skip: not windows"

    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        return "skip: no console api"
    if not hwnd:
        return "skip: 콘솔 없음(이미 GUI로 실행됨)"

    names = [n for n in _console_process_names() if n != "conhost.exe"]
    if not names:
        return "skip: 콘솔 프로세스 목록 조회 실패"

    own = os.path.basename(sys.executable or "").lower()
    allowed = _PY_NAMES | ({own} if own else set())
    outsiders = [n for n in names if n not in allowed]

    if outsiders:
        return f"keep: 사용자 터미널로 판단({', '.join(sorted(set(outsiders)))}) → 숨기지 않음"

    if not dry_run:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    return f"hide: 우리가 띄운 콘솔로 판단({', '.join(sorted(set(names)))}) → 숨김"


def console_python(path: str = None) -> str:
    """자식 파이썬 스크립트를 띄울 때 쓸 인터프리터 — pythonw.exe면 python.exe로 바꿔준다.

    ⚠ 이걸 안 하면 콘솔 창이 오히려 튀어나온다.
    relaunch_without_console() 이후 sys.executable은 pythonw.exe(GUI 서브시스템)라
    콘솔이 아예 없다. 그 상태로 자식 스크립트(event_tap.py 등)를 pythonw로 띄우면
    자식도 콘솔이 없고, 자식이 부르는 adb(손자)가 **새 콘솔 창을 할당**해 화면에 뜬다.
    자식을 콘솔 서브시스템인 python.exe로 띄우면 CREATE_NO_WINDOW로 만들어진
    '보이지 않는 콘솔'을 손자가 물려받아 창이 생기지 않는다.
    """
    p = path or sys.executable or ""
    if os.path.basename(p).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(p), "python.exe")
        if os.path.isfile(cand):
            return cand
    return p or "python"


def _console_is_ours() -> bool:
    """지금 붙어 있는 콘솔이 '우리 때문에 생긴 것'인지(= 없애도 되는지) 판단."""
    names = [n for n in _console_process_names() if n != "conhost.exe"]
    if not names:
        return False
    own = os.path.basename(sys.executable or "").lower()
    allowed = _PY_NAMES | ({own} if own else set())
    return all(n in allowed for n in names)


def relaunch_without_console(dry_run: bool = False) -> str:
    """콘솔이 딸려온 상태면 pythonw.exe로 자신을 다시 띄우고 이 프로세스는 종료한다.

    왜 '숨기기'가 아니라 '재실행'인가:
    Windows 11에서 Windows Terminal이 기본 콘솔 호스트면 GetConsoleWindow()가
    돌려주는 창은 클래스가 PseudoConsoleWindow인 대역 창이다. 실제로 눈에 보이는
    검은 창은 OpenConsole.exe/WindowsTerminal.exe 소유라, 이 대역 창을 숨겨도
    화면의 창은 그대로 남는다. 그래서 콘솔 자체를 갖지 않는 pythonw.exe로 갈아탄다.

    안전장치:
      - 사용자가 자기 터미널(cmd/PowerShell)에서 직접 실행한 경우엔 하지 않는다
      - 콘솔 창이 실제로 보이지 않으면(CREATE_NO_WINDOW로 띄워진 경우) 하지 않는다
        → 부모가 PID를 추적하는 실행 경로(common.py의 리소스 모니터 등)를 깨지 않는다
      - 재실행된 프로세스는 환경변수로 표시해 무한 재실행을 막는다

    반환: 어떤 판단을 했는지 설명하는 문자열(진단·테스트용)
    """
    if os.name != "nt":
        return "skip: not windows"
    if getattr(sys, "frozen", False):
        return "skip: 단일 exe로 빌드됨(콘솔 없음)"
    if os.environ.get("QA_GUI_NO_CONSOLE") == "1":
        return "skip: 이미 재실행된 프로세스"

    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        return "skip: no console api"
    if not hwnd:
        return "skip: 콘솔 없음"
    if not ctypes.windll.user32.IsWindowVisible(hwnd):
        # CREATE_NO_WINDOW로 띄워진 경우 — 이미 창이 없으므로 건드리지 않는다
        return "skip: 콘솔 창이 보이지 않음"
    if not _console_is_ours():
        return "keep: 사용자 터미널로 판단 → 그대로 둠"

    pythonw = os.path.join(os.path.dirname(sys.executable or ""), "pythonw.exe")
    if not os.path.isfile(pythonw):
        return "fallback: pythonw.exe 없음 → " + hide_own_console(dry_run=dry_run)

    script = os.path.abspath(sys.argv[0] or "")
    if not os.path.isfile(script):
        return "skip: 스크립트 경로를 알 수 없음"

    if dry_run:
        return f"relaunch: {pythonw} 로 재실행 예정"

    env = os.environ.copy()
    env["QA_GUI_NO_CONSOLE"] = "1"
    subprocess.Popen(
        [pythonw, script] + list(sys.argv[1:]),
        creationflags=DETACHED_PROCESS,
        cwd=os.getcwd(),
        env=env,
        close_fds=True,
    )
    os._exit(0)   # 이 프로세스가 끝나야 py.exe도 끝나고 콘솔 창이 닫힌다
