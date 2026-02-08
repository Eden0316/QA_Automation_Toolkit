# ==========================================================
# Tk 기반 QA Toolkit 환경 설정 마법사 (Windows)
# 👤 Author: Eden Kim
# 📅 Date: 2026-01-26 - v1.0.6
#   - 프리필 기능 추가: 프리필: (1) 현재 프로세스 환경변수 → (2) qa_env_var.txt → (3) fallback
# ==========================================================
# - InstallRoot: Tools\00_install
# - ToolkitRoot: Tools
# - QA_MAIL_PASS는 파일 저장 금지, setx로만 저장
# ==========================================================

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

SAFE_KEYS = (
    "QA_TOOLKIT", "QA_SCRIPT", "QA_PYTHON",
    "QA_MAIL_USER", "QA_MAIL_TO", "QA_MAIL_SMTP",
    # PATH 우선순위 강제 관련
    "QA_PYTHON_PATH_FIX",
    "QA_PYTHON_PATH_MODE",
    "QA_PYTHON_EXCLUDE_WINDOWSAPPS",
)
PASS_KEY = "QA_MAIL_PASS"

def normalize_win_path(p: str) -> str:
    """Windows 경로 정규화. / → \\ 로 수렴. 빈 문자열은 그대로."""
    if not p:
        return ""
    p = p.strip().strip('"')
    return os.path.normpath(p)

def run_setx(name: str, value: str):
    # setx는 새 콘솔부터 반영됨
    subprocess.check_call(["cmd.exe", "/c", "setx", name, value])

def pick_file(title, exts=None):
    ft = [("All", "*.*")]
    if exts:
        ft = [(title, exts), ("All", "*.*")]
    p = filedialog.askopenfilename(title=title, filetypes=ft) or ""
    return normalize_win_path(p)

def pick_dir(title):
    p = filedialog.askdirectory(title=title) or ""
    return normalize_win_path(p)

def _read_env_txt_value(path: str, key: str) -> str | None:
    """qa_env_var.txt 내 setx KEY "VALUE" / setx KEY VALUE 파싱"""
    if not os.path.exists(path):
        return None
    try:
        raw = open(path, "r", encoding="utf-8").read()
    except Exception:
        return None

    import re
    # setx KEY "VALUE"
    pat1 = re.compile(rf'(?im)^\s*setx\s+{re.escape(key)}\s+"([^"]*)"\s*$')
    m = pat1.search(raw)
    if m:
        return m.group(1).strip()

    # setx KEY VALUE
    pat2 = re.compile(rf'(?im)^\s*setx\s+{re.escape(key)}\s+([^\r\n]+)\s*$')
    m = pat2.search(raw)
    if m:
        v = m.group(1).strip().strip('"')
        if v.startswith("#") or v.startswith(";"):
            return None
        return v
    return None

def get_prefill(env_txt_path: str, key: str, fallback: str = "") -> str:
    """프리필: (1) 현재 프로세스 환경변수 → (2) qa_env_var.txt → (3) fallback"""
    v = os.environ.get(key)
    if v is not None and str(v).strip() != "":
        return str(v)
    tv = _read_env_txt_value(env_txt_path, key)
    if tv is not None and str(tv).strip() != "":
        return str(tv)
    return fallback

def main():
    install_dir = os.path.dirname(os.path.abspath(sys.argv[0]))          # Tools\00_install
    tools_dir   = os.path.abspath(os.path.join(install_dir, os.pardir))  # Tools
    env_txt_path = os.path.join(install_dir, "qa_env_var.txt")

    root = tk.Tk()
    root.title("QA Toolkit Setup Wizard")

    exit_code = {"code": 0}  # 0=정상 적용/종료, 2=사용자 스킵

    # 기본 창 크기 상향 + 최소 크기 보장(옵션 영역 추가로 버튼이 가려지는 문제 방지)
    root.geometry("760x680")
    root.minsize(760, 680)
    root.resizable(True, True)


    defaults = {
        "QA_TOOLKIT": normalize_win_path(get_prefill(env_txt_path, "QA_TOOLKIT", os.path.join(tools_dir, "qa_common"))),
        "QA_SCRIPT":  normalize_win_path(get_prefill(env_txt_path, "QA_SCRIPT",  tools_dir)),
        "QA_PYTHON":  normalize_win_path(get_prefill(env_txt_path, "QA_PYTHON",  "")),
        "QA_MAIL_USER": get_prefill(env_txt_path, "QA_MAIL_USER", ""),
        "QA_MAIL_TO":   get_prefill(env_txt_path, "QA_MAIL_TO", ""),
        "QA_MAIL_SMTP": get_prefill(env_txt_path, "QA_MAIL_SMTP", "smtp.gmail.com:465"),
        "QA_MAIL_PASS": get_prefill(env_txt_path, "QA_MAIL_PASS", ""),
        "QA_PYTHON_PATH_FIX": get_prefill(env_txt_path, "QA_PYTHON_PATH_FIX", "0"),
        "QA_PYTHON_PATH_MODE": get_prefill(env_txt_path, "QA_PYTHON_PATH_MODE", "KEEP"),
        "QA_PYTHON_EXCLUDE_WINDOWSAPPS": get_prefill(env_txt_path, "QA_PYTHON_EXCLUDE_WINDOWSAPPS", "1"),
    }
    vars = {k: tk.StringVar(value=v) for k, v in defaults.items()}

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="QA Toolkit 환경 설정", font=("Malgun Gothic", 12, "bold")).pack(anchor="w", pady=(0, 8))
    ttk.Label(
        frm,
        text=(f"InstallRoot = {install_dir}\n"
              f"ToolkitRoot   = {tools_dir}\n"
              f"저장 파일   = {env_txt_path}\n\n"
              f"• 경로 입력값은 자동으로 Windows 경로(\\)로 정규화됩니다.\n"
              f"• QA_MAIL_PASS는 보안상 파일 저장 없이 setx로만 저장합니다."),
        foreground="gray"
    ).pack(anchor="w", pady=(0, 10))

    def add_row(label, key, browse=None, is_password=False, note=None):
        r = ttk.Frame(frm)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text=label, width=18).pack(side="left")
        ent = ttk.Entry(r, textvariable=vars[key], show="*" if is_password else "")
        ent.pack(side="left", fill="x", expand=True, padx=(0, 6))
        if browse:
            ttk.Button(r, text="찾기", command=browse).pack(side="left")
        if note:
            ttk.Label(frm, text=note, foreground="gray").pack(anchor="w", padx=(18, 0))
        return ent

    # 경로
    add_row("QA_TOOLKIT", "QA_TOOLKIT", browse=lambda: vars["QA_TOOLKIT"].set(pick_dir("QA_TOOLKIT(qa_common) 폴더 선택")))
    add_row("QA_SCRIPT",  "QA_SCRIPT",  browse=lambda: vars["QA_SCRIPT"].set(pick_dir("QA_SCRIPT(Tools) 폴더 선택")))
    add_row("QA_PYTHON",  "QA_PYTHON",  browse=lambda: vars["QA_PYTHON"].set(pick_file("python.exe 선택", "*.exe")),
            note="python.exe까지 선택하세요. - 권장: Python 3.11.x (64-bit). 비워두면 설치기가 py -3.11 / python을 탐색합니다.")
    
    # -------------------------------
    # PATH 우선순위 강제 옵션
    # -------------------------------
    path_box = ttk.LabelFrame(frm, text="Python PATH 우선순위 (옵션)", padding=10)
    path_box.pack(fill="x", pady=(8, 0))

    def _bool_strvar_is_true(v: str) -> bool:
        return (v or "").strip() in ("1", "true", "True", "YES", "yes", "Y", "y", "on", "ON")

    # 체크박스(적용 여부)
    cb_fix_var = tk.BooleanVar(value=_bool_strvar_is_true(vars["QA_PYTHON_PATH_FIX"].get()))
    def _sync_fix_var():
        vars["QA_PYTHON_PATH_FIX"].set("1" if cb_fix_var.get() else "0")
    ttk.Checkbutton(
        path_box,
        text="(옵션) QA_PYTHON을 사용자 PATH 최상단에 추가/우선 적용하여, 콘솔에서 python 실행도 3.11.x로 유도",
        variable=cb_fix_var,
        command=_sync_fix_var
    ).pack(anchor="w")

    ttk.Label(path_box, text="※ 주의: 사용자 PATH를 수정합니다. 회사 PC 정책/개인 환경에 영향이 있을 수 있어 기본은 OFF입니다.", foreground="gray").pack(anchor="w", pady=(4, 0))

    # 모드(KEEP/REMOVE)
    ttk.Label(path_box, text="기존 Python 경로 처리:", foreground="gray").pack(anchor="w", pady=(6, 2))

    mode_var = tk.StringVar(value=(vars["QA_PYTHON_PATH_MODE"].get().strip() or "KEEP").upper())
    def _sync_mode_var():
        vars["QA_PYTHON_PATH_MODE"].set((mode_var.get() or "KEEP").upper())

    r1 = ttk.Radiobutton(path_box, text="KEEP: 삭제하지 않고 뒤로 이동(권장, 안전)", value="KEEP", variable=mode_var, command=_sync_mode_var)
    r2 = ttk.Radiobutton(path_box, text="REMOVE: 기존 Python 경로 제거(충돌 최소화, 주의)", value="REMOVE", variable=mode_var, command=_sync_mode_var)
    r1.pack(anchor="w")
    r2.pack(anchor="w")

    # WindowsApps 제외 옵션
    cb_wa_var = tk.BooleanVar(value=_bool_strvar_is_true(vars["QA_PYTHON_EXCLUDE_WINDOWSAPPS"].get()))
    def _sync_wa_var():
        vars["QA_PYTHON_EXCLUDE_WINDOWSAPPS"].set("1" if cb_wa_var.get() else "0")

    ttk.Checkbutton(
        path_box,
        text=r"Microsoft\WindowsApps 의 python alias 경로는 제외(권장)",
        variable=cb_wa_var,
        command=_sync_wa_var
    ).pack(anchor="w", pady=(6, 0))


    ttk.Separator(frm).pack(fill="x", pady=10)

    # 메일
    add_row("QA_MAIL_USER", "QA_MAIL_USER")
    add_row("QA_MAIL_TO",   "QA_MAIL_TO")
    add_row("QA_MAIL_SMTP", "QA_MAIL_SMTP")
    add_row("QA_MAIL_PASS", "QA_MAIL_PASS", is_password=True,
            note="보안상 qa_env_var.txt에는 저장하지 않습니다. setx로만 저장됩니다.")

    ttk.Separator(frm).pack(fill="x", pady=10)

    def validate() -> bool:
        qt = normalize_win_path(vars["QA_TOOLKIT"].get())
        qs = normalize_win_path(vars["QA_SCRIPT"].get())
        vars["QA_TOOLKIT"].set(qt)
        vars["QA_SCRIPT"].set(qs)

        if not qt or not os.path.isdir(qt):
            messagebox.showerror("필수 값 확인", "QA_TOOLKIT 경로가 올바르지 않습니다.")
            return False
        if not qs or not os.path.isdir(qs):
            messagebox.showerror("필수 값 확인", "QA_SCRIPT 경로가 올바르지 않습니다.")
            return False
        
        # PATH 우선순위 강제 적용 시 QA_PYTHON 필수/유효성 체크
        fix_on = (vars["QA_PYTHON_PATH_FIX"].get().strip() == "1")
        pyexe = normalize_win_path(vars["QA_PYTHON"].get())
        vars["QA_PYTHON"].set(pyexe)

        if fix_on:
            if not pyexe:
                messagebox.showerror("필수 값 확인", "PATH 최상단 적용을 선택했지만 QA_PYTHON이 비어있습니다.\npython.exe 경로를 지정하세요.")
                return False
            if not os.path.exists(pyexe) or not pyexe.lower().endswith("python.exe"):
                messagebox.showerror("필수 값 확인", f"QA_PYTHON이 유효한 python.exe 경로가 아닙니다:\n{pyexe}")
                return False

        return True

    def apply():
        if not validate():
            return

        # 0) 값 정규화(경로는 무조건 normpath)
        for k in ("QA_TOOLKIT", "QA_SCRIPT", "QA_PYTHON"):
            vars[k].set(normalize_win_path(vars[k].get().strip()))
        for k in ("QA_MAIL_USER", "QA_MAIL_TO", "QA_MAIL_SMTP", "QA_MAIL_PASS"):
            vars[k].set(vars[k].get().strip())

        # 1) setx 적용 (PASS 포함)
        try:
            for k in SAFE_KEYS:
                v = vars[k].get().strip()
                if v:
                    run_setx(k, v)

            pass_v = vars[PASS_KEY].get().strip()
            if pass_v:
                run_setx(PASS_KEY, pass_v)

        except Exception as e:
            messagebox.showerror("환경변수 설정 실패", str(e))
            return

        # 2) qa_env_var.txt 저장 (PASS 제외)
        try:
            lines = []
            for k in SAFE_KEYS:
                v = vars[k].get().strip()
                if v:
                    lines.append(f'setx {k} "{v}"')

            with open(env_txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                f.flush()
                os.fsync(f.fileno())

        except Exception as e:
            messagebox.showwarning("파일 저장 경고", f"qa_env_var.txt 저장 실패:\n{e}")

        # 3) 저장 검증(사용자 체감 문제 방지)
        missing = []
        for k in SAFE_KEYS:
            # PASS는 파일 저장 대상 아님
            if not _read_env_txt_value(env_txt_path, k) and vars[k].get().strip():
                missing.append(k)

        if missing:
            messagebox.showwarning(
                "저장 검증 경고",
                "다음 키가 qa_env_var.txt에 기록되지 않았습니다:\n"
                f"- {', '.join(missing)}\n\n"
                f"저장 경로: {env_txt_path}\n"
                "권한/백신/동기화 폴더 잠금 여부를 확인하세요."
            )

        messagebox.showinfo(
            "설정 완료",
            "환경변수 저장이 완료되었습니다.\n\n"
            "• setx로 저장된 값은 '새 CMD/PowerShell'부터 자동 적용됩니다.\n"
            "• 설치기는 qa_env_var.txt를 즉시 다시 읽어 현재 세션에 반영하여 다음 단계(패키지 설치)를 진행합니다.\n\n"
            "이 창을 닫으면 설치기가 계속 진행됩니다."
        )
        exit_code["code"] = 0
        root.destroy()

    def cancel():
        exit_code["code"] = 2
        root.destroy()

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=8)
    ttk.Button(btns, text="적용", command=apply).pack(side="right")
    ttk.Button(btns, text="취소", command=cancel).pack(side="right", padx=6)
    root.protocol("WM_DELETE_WINDOW", cancel)

    # ------------------------------------------------------------
    # UI 추가/변경으로 필요한 높이가 증가할 수 있으므로,
    # 위젯 요구 크기 기반으로 창 크기를 자동 조정(화면 크기 상한 적용)
    # ------------------------------------------------------------
    root.update_idletasks()

    # 요청 크기(필요한 실제 UI 크기)
    req_w = root.winfo_reqwidth()
    req_h = root.winfo_reqheight()

    # 화면 크기(너무 커지지 않게 상한)
    scr_w = root.winfo_screenwidth()
    scr_h = root.winfo_screenheight()

    # 여백 포함, 화면 밖으로 나가지 않게 제한
    new_w = min(max(760, req_w + 20), scr_w - 80)
    new_h = min(max(680, req_h + 20), scr_h - 120)

    root.geometry(f"{new_w}x{new_h}")

    root.mainloop()
    sys.exit(exit_code["code"])

if __name__ == "__main__":
    main()