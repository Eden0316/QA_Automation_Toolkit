# ==========================================================
# 🛠️ Tool: QA Control Center - Multi-device QA execution, monitoring, and tooling hub
# 👤 Author: Eden Kim
# 📅 Date: 2026-08-11 - v1.0.6
#   - 고해상도 화면 흐림 해결: DPI 인식 선언 + Tk scaling/창크기 연동
#   - 불필요한 cmd 창 제거: adb 조회 시 깜빡임, scrcpy·리소스모니터·로그뷰어 실행 시 빈 콘솔
#     (테스트 스크립트 실행 콘솔은 출력을 봐야 하므로 그대로 유지)
# 📅 Date: 2026-01-08 - v1.0.5
#   - python 하드코딩 QA_PYTHON 변수로 대체
# ============================================================
# 기능:
#  1) 단말 선택(모델명(시리얼)) + 스크립트 실행(.py / .air)
#  2) color_pipe.py 파이프를 통한 컬러 출력(있으면 자동 적용)
#  3) scrcpy 실행(선택 단말)
#  4) 리소스 모니터 실행(선택 단말)
#  5) 로그파일 뷰어 실행(별도 로그파일 선택)
#  6) "모든 단말에 실행" (run_multi.ps1 동등 기능을 GUI로 제공)
#  7) "선택 단말에 실행"
#
# 전제:
#  - Tools 폴더에 본 파일과 color_pipe.py가 존재(없어도 일반 실행은 가능)
#  - adb PATH 설정 또는 플랫폼 도구 설치 필요
#  - scrcpy는 PATH 또는 아래 경로 중 하나에 존재하면 동작
# ==========================================================

import os, sys, subprocess, shutil, shlex
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qa_gui_util import (enable_dpi_awareness, apply_tk_scaling, scale_geometry,
                         silence_console_windows, relaunch_without_console, console_python,
                         CREATE_NO_WINDOW)

# ⚠ Tk 창이 만들어지기 전에 확정되어야 하므로 import 시점에 처리한다
relaunch_without_console()   # exe 런처가 py.exe로 실행해 딸려온 콘솔 창 제거(먼저 처리)
UI_SCALE = enable_dpi_awareness()
silence_console_windows()

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


# ----------------------------------------------------------
# 경로/탐색 유틸
# ----------------------------------------------------------
def get_base_dir() -> str:
    """이 런처 스크립트(or exe)가 있는 폴더 (Tools)."""
    return os.path.dirname(os.path.abspath(sys.argv[0]))

def get_python_exe() -> str:
    """
    프로젝트 표준 Python.
    우선순위:
      1) QA_PYTHON (유효 경로일 때)
      2) sys.executable
      3) PATH의 python (최후 fallback)
    """
    # ⚠ console_python()으로 감싼다 — 이 값은 테스트 스크립트 실행(콘솔에 컬러 출력)에도 쓰이고,
    # 자식이 부르는 adb가 새 콘솔 창을 만들지 않게 하려면 콘솔 서브시스템 python.exe여야 한다.
    # (relaunch_without_console() 이후 sys.executable은 pythonw.exe다)
    qa = (os.environ.get("QA_PYTHON") or "").strip().strip('"')
    if qa and os.path.exists(qa):
        return console_python(qa)

    if sys.executable and os.path.exists(sys.executable):
        return console_python(sys.executable)

    return shutil.which("python") or "python"

def q(s: str) -> str:
    """cmd.exe용 안전 따옴표 감싸기(경로 공백 대응)."""
    return f'"{s}"'

def find_color_pipe(base_dir: str) -> str | None:
    """
    base_dir에서 color_pipe.py 하나만 찾는다.
    (날짜 붙은 공유용 파일은 고려하지 않음)
    """
    path = os.path.join(base_dir, "color_pipe.py")
    return path if os.path.exists(path) else None


def find_scrcpy_exe(base_dir: str | None = None) -> str | None:
    """
    scrcpy.exe를 탐색한다.
    우선순위:
      1) PATH
      2) Tools\tools\scrcpy\scrcpy.exe (예시)
      3) Tools\scrcpy\scrcpy.exe
      4) C:\Program Files\scrcpy\scrcpy.exe
      5) C:\Program Files (x86)\scrcpy\scrcpy.exe
    """
    import shutil

    # 1) PATH
    p = shutil.which("scrcpy")
    if p:
        return p

    cand = []
    if base_dir:
        cand += [
            os.path.join(base_dir, "tools", "scrcpy", "scrcpy.exe"),
            os.path.join(base_dir, "scrcpy", "scrcpy.exe"),
        ]

    cand += [
        r"C:\Program Files\scrcpy\scrcpy.exe",
        r"C:\Program Files (x86)\scrcpy\scrcpy.exe",
    ]

    for c in cand:
        if os.path.exists(c):
            return c
    return None

def find_logfile_viewer_anywhere(tools_root: str, max_depth: int = 2) -> str | None:
    """
    Tools 폴더 및 하위 폴더를 재귀 탐색하여 'logfile_viewer_gui.py'를 찾는다.
    - 타임스탬프 버전(logfile_viewer_gui_YYMMDD-hhmm.py)은 탐색하지 않음.
    - 너무 깊은 폴더는 max_depth로 제한.
    """
    if not tools_root:
        return None
    tools_root = os.path.abspath(tools_root)
    if not os.path.isdir(tools_root):
        return None

    target = "logfile_viewer_gui.py"

    # 제외 폴더(탐색 비용/오탐 줄이기)
    exclude = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}

    base_depth = tools_root.rstrip("\\/").count(os.sep)

    for root, dirs, files in os.walk(tools_root):
        # 깊이 제한
        cur_depth = root.rstrip("\\/").count(os.sep)
        if cur_depth - base_depth >= max_depth:
            dirs[:] = []
            continue

        # 제외 폴더 가지치기
        dirs[:] = [d for d in dirs if d not in exclude]

        if target in files:
            return os.path.join(root, target)

    return None


# ----------------------------------------------------------
# ADB 유틸
# ----------------------------------------------------------
def list_devices(adb_path: str = "adb"):
    """
    adb devices 출력에서 단말 목록을 파싱.
    반환: ([(serial, state), ...], 오류메시지 또는 None)
    """
    try:
        out = subprocess.check_output(
            [adb_path, "devices"],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        return [], str(e)

    lines = out.strip().splitlines()
    devices = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            serial, state = line.split("\t", 1)
        else:
            parts = line.split()
            if len(parts) >= 2:
                serial, state = parts[0], parts[1]
            else:
                continue
        devices.append((serial.strip(), state.strip()))
    return devices, None


def get_device_model(serial: str, adb_path: str = "adb") -> str:
    """시리얼 기준 ro.product.model. 실패 시 시리얼 반환."""
    try:
        out = subprocess.check_output(
            [adb_path, "-s", serial, "shell", "getprop", "ro.product.model"],
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        model = (out or "").strip()
        return model if model else serial
    except Exception:
        return serial


# ----------------------------------------------------------
# 실행 라인 생성 (run_multi.ps1 동등)
# ----------------------------------------------------------
def _build_run_line(script_abs: str, extra: str) -> tuple[str, str]:
    """
    반환: (cmd_line, work_dir)
      - cmd_line: 실제 실행할 한 줄(파이프 적용 전)
      - work_dir: cd /d 할 작업 디렉터리
    """
    script_abs = os.path.abspath(script_abs)
    work_dir = os.path.dirname(script_abs)

    ext = os.path.splitext(script_abs)[1].lower()
    extra = (extra or "").strip()

    if ext == ".air":
        # airtest run: %QA_PYTHON% -m airtest run "<path.air>"
        # (extra 인자는 airtest CLI 규칙이 복잡하므로 일단 미지원. 필요하면 여기에서 확장)
        if extra:
            # 사용자가 넣어도 위험하지 않게 "경고" 수준으로만 처리(실행은 기본형)
            pass
        cmd = f'%QA_PYTHON% -m airtest run "{script_abs}"'
        return cmd, work_dir

    # 기본: %QA_PYTHON% -u "<script.py>" [extra...]
    if extra:
        cmd = f'%QA_PYTHON% -u "{script_abs}" {extra}'
    else:
        cmd = f'%QA_PYTHON% -u "{script_abs}"'
    return cmd, work_dir


def _wrap_with_color_pipe(cmd_main: str, color_pipe_abs: str) -> str:
    """
    cmd_main의 stdout/stderr를 color_pipe로 파이프.
    """
    color_pipe_abs = os.path.abspath(color_pipe_abs)
    # stderr 포함 후 color_pipe로
    return f'{cmd_main} 2>&1 | %QA_PYTHON% -u "{color_pipe_abs}"'


def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def _write_cmd_file(cmd_path: str, lines: list[str]):
    """
    .cmd 파일 작성.
    - UTF-8 BOM(utf-8-sig)로 저장해도 cmd에서 ASCII 구문은 안전.
    - 첫 줄에서 chcp 65001 로 전환하여 이후 출력/파이프가 UTF-8로 흐르도록 유도.
    """
    content = "\r\n".join(lines) + "\r\n"
    with open(cmd_path, "w", encoding="utf-8-sig") as f:
        f.write(content)


def _launch_cmd_new_console(cmd_path: str, cwd: str):
    subprocess.Popen(
        ["cmd.exe", "/k", cmd_path],
        cwd=cwd,
        creationflags=CREATE_NEW_CONSOLE,
    )


# ----------------------------------------------------------
# GUI
# ----------------------------------------------------------
class ColorRunnerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QA Control Center - Tooling Hub")
        apply_tk_scaling(self, UI_SCALE)
        self.geometry(scale_geometry("740x320", UI_SCALE))

        self.base_dir = get_base_dir()
        self.color_pipe_path = find_color_pipe(self.base_dir)

        self.devices: list[tuple[str, str]] = []
        self.device_map: dict[str, str] = {}  # display → serial

        self.selected_display = tk.StringVar()
        self.script_path = tk.StringVar()
        self.extra_args = tk.StringVar()
        self.status_var = tk.StringVar()

        self._build_ui()
        self.refresh_devices(initial=True)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 단말
        frm_dev = ttk.LabelFrame(self, text="단말 선택 (ADB devices)")
        frm_dev.pack(fill=tk.X, **pad)

        self.cbb_devices = ttk.Combobox(
            frm_dev, textvariable=self.selected_display, state="readonly"
        )
        self.cbb_devices.grid(row=0, column=0, sticky="we", padx=4, pady=6)

        btn_refresh = ttk.Button(frm_dev, text="새로고침", command=self.refresh_devices)
        btn_refresh.grid(row=0, column=1, sticky="e", padx=4, pady=6)

        btn_scrcpy = ttk.Button(frm_dev, text="🖥 scrcpy 실행", command=self.run_scrcpy_selected)
        btn_scrcpy.grid(row=0, column=2, sticky="e", padx=4, pady=6)

        btn_resource = ttk.Button(frm_dev, text="📈 리소스 모니터", command=self.run_resource_monitor_selected)
        btn_resource.grid(row=0, column=3, sticky="e", padx=4, pady=6)

        btn_logviewer = ttk.Button(frm_dev, text="📜 로그파일 뷰어", command=self.run_logfile_viewer_selected)
        btn_logviewer.grid(row=0, column=4, sticky="e", padx=4, pady=6)

        frm_dev.columnconfigure(0, weight=1)

        # 스크립트
        frm_script = ttk.LabelFrame(self, text="스크립트 선택 (.py / .air)")
        frm_script.pack(fill=tk.X, **pad)

        ent_script = ttk.Entry(frm_script, textvariable=self.script_path)
        ent_script.grid(row=0, column=0, columnspan=2, sticky="we", padx=4, pady=4)

        btn_browse = ttk.Button(frm_script, text="찾기", command=self.browse_script)
        btn_browse.grid(row=0, column=2, sticky="e", padx=4, pady=4)

        ttk.Label(frm_script, text="추가 인자(.py용):").grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        ent_args = ttk.Entry(frm_script, textvariable=self.extra_args)
        ent_args.grid(row=1, column=1, columnspan=2, sticky="we", padx=4, pady=4)

        frm_script.columnconfigure(1, weight=1)

        # 실행
        frm_bottom = ttk.Frame(self)
        frm_bottom.pack(fill=tk.X, **pad)

        btn_run_one = ttk.Button(frm_bottom, text="선택 단말 실행", command=self.run_one_selected)
        btn_run_one.pack(side=tk.RIGHT, padx=(6, 0))

        btn_run_all = ttk.Button(frm_bottom, text="모든 단말 실행", command=self.run_all_devices)
        btn_run_all.pack(side=tk.RIGHT)

        # 상태
        lbl_status = ttk.Label(self, textvariable=self.status_var, foreground="gray")
        lbl_status.pack(fill=tk.X, padx=8, pady=(0, 8))

        # color_pipe 상태
        if not self.color_pipe_path:
            self.status_var.set("경고: 현재 폴더에서 color_pipe.py를 찾지 못했습니다. (일반 모드로 실행)")
        else:
            self.status_var.set(f"color_pipe 사용 준비 완료: {self.color_pipe_path}")

    # ---------------- helpers ----------------
    def browse_script(self):
        path = filedialog.askopenfilename(
            title="실행할 스크립트 선택",
            filetypes=[
                ("Test Scripts (*.py;*.air)", "*.py;*.air"),
                ("Python 파일", "*.py"),
                ("Airtest 폴더", "*.air"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.script_path.set(path)

    def refresh_devices(self, initial: bool = False):
        devs, err = list_devices()
        self.devices = devs
        self.device_map.clear()

        if err:
            msg = f"adb devices 실행 중 오류가 발생했습니다:\n{err}"
            if not initial:
                messagebox.showerror("단말 검색 오류", msg)
            self.cbb_devices["values"] = []
            self.selected_display.set("")
            return

        if not devs:
            self.cbb_devices["values"] = []
            self.selected_display.set("")
            self.status_var.set("연결된 단말이 없습니다. USB 연결 및 adb 인식을 확인해 주세요.")
            return

        items = []
        for serial, state in devs:
            model = get_device_model(serial)
            display = f"{model}({serial})"
            items.append(display)
            self.device_map[display] = serial

        self.cbb_devices["values"] = items

        # 'device' 상태 우선 선택
        serial_to_select = None
        for s, st in devs:
            if st == "device":
                serial_to_select = s
                break
        if serial_to_select is None:
            serial_to_select = devs[0][0]

        display_to_select = None
        for disp, s in self.device_map.items():
            if s == serial_to_select:
                display_to_select = disp
                break

        if not display_to_select and items:
            display_to_select = items[0]

        if display_to_select:
            self.selected_display.set(display_to_select)
            self.status_var.set(f"단말 {display_to_select} 선택됨. 총 {len(devs)}대 연결됨.")
        else:
            self.selected_display.set("")
            self.status_var.set(f"단말 목록 갱신 완료 (총 {len(devs)}대).")

    def _selected_serial(self) -> str | None:
        sel_display = (self.selected_display.get() or "").strip()
        if not sel_display:
            return None
        return self.device_map.get(sel_display)

    def _validate_script(self) -> str | None:
        script_input = (self.script_path.get() or "").strip()
        if not script_input:
            messagebox.showwarning("실행 불가", "실행할 스크립트를 선택해 주세요.")
            return None
        if not os.path.exists(script_input):
            messagebox.showerror("실행 불가", f"스크립트를 찾을 수 없습니다:\n{script_input}")
            return None
        ext = os.path.splitext(script_input)[1].lower()
        if ext not in (".py", ".air"):
            messagebox.showerror("실행 불가", "지원 확장자: .py / .air")
            return None
        return os.path.abspath(script_input)

    def _device_list_online(self) -> list[str]:
        """현재 연결된 device 상태 단말 시리얼만 반환."""
        return [s for (s, st) in self.devices if st == "device"]

    # ---------------- scrcpy ----------------
    def run_scrcpy_selected(self):
        ser = self._selected_serial()
        if not ser:
            messagebox.showinfo("안내", "Device를 먼저 선택하세요.")
            return

        scrcpy = find_scrcpy_exe(self.base_dir)
        if not scrcpy:
            messagebox.showerror(
                "scrcpy 없음",
                "scrcpy 실행 파일을 찾지 못했습니다.\n\n"
                "해결 방법:\n"
                " 1) scrcpy를 PATH에 추가하거나\n"
                " 2) Tools\\scrcpy\\scrcpy.exe 에 배치하거나\n"
                " 3) C:\\Program Files\\scrcpy\\scrcpy.exe 로 설치하세요.",
            )
            return

        try:
            # scrcpy는 자체 창을 띄우는 GUI라 콘솔이 필요 없다
            subprocess.Popen([scrcpy, "-s", ser], creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("실행 오류", f"scrcpy 실행 실패: {e}")
            return

        os.environ["ADB_SERIAL"] = ser
        os.environ["ANDROID_SERIAL"] = ser
        self.status_var.set(f"scrcpy 실행: {os.path.basename(scrcpy)} -s {ser}")

    # ---------------- resource monitor ----------------
    def run_resource_monitor_selected(self):
        ser = self._selected_serial()
        if not ser:
            messagebox.showinfo("안내", "단말을 먼저 선택하세요.")
            return

        rm_path = os.path.join(self.base_dir, "resource_monitor_gui.py")
        if not os.path.exists(rm_path):
            messagebox.showerror(
                "실행 불가",
                f"resource_monitor_gui.py를 찾을 수 없습니다:\n{rm_path}",
            )
            return

        py = get_python_exe()
        env = os.environ.copy()
        env["ADB_SERIAL"] = ser
        env["ANDROID_SERIAL"] = ser

        # 🔴 핵심: 자동 시작 플래그
        env["RM_AUTO_START"] = "1"

        env["QA_PYTHON"] = py  # (권장) 자식도 동일 표준 Python을 알게 함

        try:
            subprocess.Popen(
                [
                    py,
                    rm_path,
                    "--auto",          # 🔴 실행 인자로도 auto 전달
                ],
                cwd=self.base_dir,
                env=env,
                creationflags=CREATE_NO_WINDOW,   # 리소스 모니터는 GUI라 콘솔 불필요
            )
        except Exception as e:
            messagebox.showerror("실행 오류", f"리소스 모니터 실행 실패:\n{e}")
            return

        self.status_var.set(f"리소스 모니터 자동 시작: {ser}")

    def run_logfile_viewer_selected(self):
        viewer = find_logfile_viewer_anywhere(self.base_dir)
        if not viewer or not os.path.exists(viewer):
            messagebox.showerror(
                "실행 불가",
                "Tools 폴더(하위 포함)에서 logfile_viewer_gui.py를 찾지 못했습니다.\n\n"
                "확인 사항:\n"
                " - logfile_viewer_gui.py 파일명이 정확한지\n"
                " - Tools 폴더 하위 어딘가에 존재하는지",
            )
            return

        viewer_dir = os.path.dirname(os.path.abspath(viewer))

        try:
            # 인자 없이 실행(뷰어에서 파일 선택/열기 흐름 유지)
            subprocess.Popen(
                [get_python_exe(), viewer],
                cwd=viewer_dir,
                env=os.environ.copy(),
                creationflags=CREATE_NO_WINDOW,   # 로그파일 뷰어는 GUI라 콘솔 불필요
            )
        except Exception as e:
            messagebox.showerror("실행 오류", f"로그파일 뷰어 실행 실패:\n{e}")
            return

        self.status_var.set(f"로그파일 뷰어 실행: {ser}\nPATH: {viewer}")


    # ---------------- run (single) ----------------
    def run_one_selected(self):
        ser = self._selected_serial()
        if not ser:
            messagebox.showwarning("실행 불가", "단말을 선택해 주세요.")
            return

        script_abs = self._validate_script()
        if not script_abs:
            return

        extra = (self.extra_args.get() or "").strip()
        self._launch_for_serial(serial=ser, script_abs=script_abs, extra=extra, keep_cmd_in_result=False)

    # ---------------- run (all) ----------------
    def run_all_devices(self):
        script_abs = self._validate_script()
        if not script_abs:
            return

        devs = self._device_list_online()
        if not devs:
            messagebox.showinfo("안내", "실행 가능한(device 상태) 단말이 없습니다.")
            return

        extra = (self.extra_args.get() or "").strip()

        launched = 0
        for ser in devs:
            try:
                self._launch_for_serial(serial=ser, script_abs=script_abs, extra=extra, keep_cmd_in_result=True)
                launched += 1
            except Exception as e:
                # 한 대가 실패해도 전체 실행은 계속
                self.status_var.set(f"[WARN] {ser} 실행 실패: {e}")

        self.status_var.set(f"모든 단말 실행 시작: {launched}대 (device 상태 기준)")

    # ---------------- core launcher ----------------
    def _launch_for_serial(self, serial: str, script_abs: str, extra: str, keep_cmd_in_result: bool):
        """
        run_multi.ps1 방식 유지:
          - result\<serial> 생성
          - run_<serial>.cmd 생성(또는 Tools\_run_color_tmp.bat처럼 1개만 덮어쓰기)
          - cmd.exe 새 콘솔로 실행
        """
        script_abs = os.path.abspath(script_abs)

        # 결과 폴더: Tools\result\<serial>
        result_dir = os.path.join(self.base_dir, "result", serial)
        _ensure_dir(result_dir)

        # 실행 라인/작업 폴더
        cmd_main, work_dir = _build_run_line(script_abs, extra)

        # color_pipe 적용(있으면)
        if self.color_pipe_path:
            cmd_main = _wrap_with_color_pipe(cmd_main, self.color_pipe_path)

        # cmd 파일 경로 결정
        if keep_cmd_in_result:
            cmd_path = os.path.join(result_dir, f"run_{serial}.cmd")
        else:
            cmd_path = os.path.join(self.base_dir, "_run_color_tmp.cmd")

        # Python 실행 파일 경로
        py_exe = get_python_exe()

        # cmd 내용
        cmd_lines = [
            "@echo off",
            "setlocal",
            "chcp 65001 >nul",
            f'set "QA_PYTHON={py_exe}"',  # 추가: 새 콘솔에서도 확실히 동일 Python 사용
            f'set "ADB_SERIAL={serial}"',
            f'set "ANDROID_SERIAL={serial}"',
            f'set "RESULT_DIR={result_dir}"',
            'set "PYTHONIOENCODING=utf-8"',
            "",
            f'cd /d "{work_dir}"',
            cmd_main,
            "echo.",
            "echo ===== [ Done ] Press any key to exit. =====",
            "pause",
            "endlocal",
        ]

        _write_cmd_file(cmd_path, cmd_lines)

        # 실행
        _launch_cmd_new_console(cmd_path, cwd=self.base_dir)

        # 상태
        disp = None
        for k, v in self.device_map.items():
            if v == serial:
                disp = k
                break
        disp = disp or serial
        self.status_var.set(f"[LAUNCH] {disp}\nCMD: {cmd_path}")


def main():
    app = ColorRunnerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
