# ==========================================================
# 🎨 Color Pipe
# 👤 Author: Eden Kim
# 📅 Date: 2026-01-07
#   - log 필터 하이라이트 수정
# ==========================================================
#   - 콘솔 출력(표준출력)용 컬러 필터
#   - stdin → stdout (파이프 라인용)
#   - Windows, Linux, macOS 공통
#   - Windows 터미널(명령 프롬프트, PowerShell, Windows Terminal)에서 ANSI VT 지원
#   - Windows 10 이상 권장 (이전 버전은 별도 설정 필요)
#   - Linux, macOS는 기본 지원
#   - Python 3.6 이상 권장 (f-string 사용)
# ==========================================================
# -*- coding: utf-8 -*-
# color_pipe.py  (logic-name; 파일명_생성날짜는 기록용에만 사용)
import sys, re

# ===== Windows ANSI VT enable =====
try:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if k32.GetConsoleMode(h, ctypes.byref(mode)):
        k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
except Exception:
    pass

RESET="\x1b[0m"; BOLD="\x1b[1m"; DIM="\x1b[2m"; UL="\x1b[4m"
FG={"blk":"\x1b[30m","wht":"\x1b[97m","gry":"\x1b[90m","red":"\x1b[31m","ylw":"\x1b[33m","grn":"\x1b[32m","blu":"\x1b[34m","mag":"\x1b[35m","cyn":"\x1b[36m",
    "k":"\x1b[38;2;0;0;0m"}
BG={"red":"\x1b[41m","ylw":"\x1b[43m","grn":"\x1b[42m","cyn":"\x1b[46m","bgr":"\x1b[100m","blu":"\x1b[44m","mag":"\x1b[45m"}

def box(text, fg, bg, bold=False):
    return (BOLD if bold else "") + fg + bg + text + RESET

# 1) 태그 정규화(고정폭 → 배경 줄맞춤)
TAG_PAT = re.compile(
    r"\[(?:ERROR|WARN(?:ING)?|INFO|DEBUG|STEP"
    # r"|RUN|SUB|BLOCK|SCROLL|CLICK|EXC|EXC-ACT|OK|ACCT|CHECK_CORE|CLICK_CORE"
    # r"|런처|Basic Test / 노출|Basic Test / 기능"
    r")\]"
)
def normalize_tag(m):
    raw = m.group(0)

    # 한글/공백 태그는 대문자화하지 않고 원형 유지가 보기 좋음
    up = raw.upper()

    if "ERROR" in up:                  label="[ERROR]"
    elif "WARN" in up:                 label="[WARN ]"
    elif "INFO" in up:                 label="[INFO ]"
    elif "DEBUG" in up:                label="[DEBUG]"
    elif "STEP" in up:                 label="[STEP ]"
    else:
        # RUN/SUB/... 같은 태그는 대문자 형태 그대로 쓰되, 런처/Basic Test는 원형 유지
        label = up if re.fullmatch(r"\[[A-Z0-9_\-]+\]", up) else raw
    return label


# 2) 태그 색(배경 라벨) — logfile_viewer 톤 유사
TAG_RULES = [
    (re.compile(r"\bWARN\b"), lambda s: FG["ylw"]+s+RESET),
    (re.compile(r"\bERR\b"), lambda s: FG["red"]+s+RESET),
    (re.compile(r"\[ERROR\]"), lambda s: box(s, FG["wht"], BG["red"], True)),
    (re.compile(r"\[WARN \]"), lambda s: box(s, FG["k"], BG["ylw"], True)),
    (re.compile(r"\[INFO \]"), lambda s: box(s, FG["k"], BG["grn"], False)),
    (re.compile(r"\[DEBUG\]"), lambda s: box(s, FG["wht"], BG["bgr"], False)),
    (re.compile(r"\[STEP \]"), lambda s: box(s, FG["k"], BG["cyn"], True)),
]

# --- [ADD] run.log 태그 박스 컬러 (태그 글자색 회색 금지) ---
# TAG_RULES += [
#     (re.compile(r"\[RUN\]"),        lambda s: box(s, FG["wht"], BG["blu"], True)),
#     (re.compile(r"\[SUB\]"),        lambda s: box(s, FG["blk"], BG["cyn"], True)),
#     (re.compile(r"\[BLOCK\]"),      lambda s: box(s, FG["wht"], BG["mag"], True)),
#     (re.compile(r"\[SCROLL\]"),     lambda s: box(s, FG["blk"], BG["ylw"], True)),
#     (re.compile(r"\[CLICK\]"),      lambda s: box(s, FG["blk"], BG["grn"], True)),

#     (re.compile(r"\[EXC-ACT\]"),    lambda s: box(s, FG["wht"], BG["red"], True)),
#     (re.compile(r"\[EXC\]"),        lambda s: box(s, FG["wht"], BG["red"], True)),

#     (re.compile(r"\[ACCT\]"),       lambda s: box(s, FG["blk"], BG["ylw"], True)),

#     (re.compile(r"\[CHECK_CORE\]"), lambda s: box(s, FG["wht"], BG["bgr"], True)),
#     (re.compile(r"\[CLICK_CORE\]"), lambda s: box(s, FG["wht"], BG["bgr"], True)),

#     (re.compile(r"\[런처\]"),            lambda s: box(s, FG["wht"], BG["blu"], True)),
#     (re.compile(r"\[Basic Test / 노출\]"), lambda s: box(s, FG["wht"], BG["blu"], True)),
#     (re.compile(r"\[Basic Test / 기능\]"), lambda s: box(s, FG["wht"], BG["blu"], True)),
# ]

# 3) 추가 하이라이트(다채로운 팔레트)
EXTRA = [
    # --- [ADD] 결과 토큰 강조 (PASS/FAIL/WARN/성공/실패 + 아이콘) ---
    (re.compile(r"\bPASS\b"), lambda s: BOLD+FG["grn"]+s+RESET),
    (re.compile(r"\bFAIL\b"), lambda s: BOLD+FG["red"]+s+RESET),

    # 한글 성공/실패(오탐 최소화: 한글/영문/숫자에 붙어있으면 제외)
    (re.compile(r"(?<![가-힣A-Za-z0-9])성공(?![가-힣A-Za-z0-9])"), lambda s: BOLD+FG["grn"]+s+RESET),
    (re.compile(r"(?<![가-힣A-Za-z0-9])실패(?![가-힣A-Za-z0-9])"), lambda s: BOLD+FG["red"]+s+RESET),

    # 자체 태그 별도 색상
    (re.compile(r"\bRUN\b"),                lambda s: FG["blu"]+s+RESET),
    (re.compile(r"\bSUB\b"),                lambda s: BOLD+FG["cyn"]+s+RESET),
    (re.compile(r"\bBLOCK\b"),              lambda s: FG["mag"]+s+RESET),
    (re.compile(r"\bSCROLL\b|\bRISK\b|\bTYPE\b"),    lambda s: FG["ylw"]+s+RESET),
    (re.compile(r"\bCLICK\b|\bRECOVERY\b"), lambda s: BOLD+FG["grn"]+s+RESET),

    (re.compile(r"\bEXC-ACT\b"),    lambda s: FG["mag"]+s+RESET),
    (re.compile(r"\bEXC\b"),        lambda s: FG["mag"]+s+RESET),

    (re.compile(r"\bACCT\b"),       lambda s: FG["ylw"]+s+RESET),

    (re.compile(r"\bCHECK_CORE\b"), lambda s: BOLD+FG["mag"]+s+RESET),
    (re.compile(r"\bCLICK_CORE\b"), lambda s: BOLD+FG["mag"]+s+RESET),

    (re.compile(r"\b런처\b"),            lambda s: BOLD+FG["ylw"]+s+RESET),
    (re.compile(r"\bBasic Test / 노출\b"), lambda s: FG["cyn"]+s+RESET),
    (re.compile(r"\bBasic Test / 기능\b"), lambda s: FG["cyn"]+s+RESET),

    # 아이콘
    (re.compile(r"✅"),    lambda s: BOLD+FG["grn"]+s+RESET),
    (re.compile(r"❌|⛔"), lambda s: BOLD+FG["red"]+s+RESET),
    (re.compile(r"⚠️|⚠"), lambda s: BOLD+FG["ylw"]+s+RESET),
    
    # 치명/예외/ANR
    (re.compile(r"FATAL EXCEPTION|CRASH|Traceback \(most recent call last\)"), lambda s: BOLD+FG["wht"]+BG["red"]+s+RESET),
    (re.compile(r"\bANR\b"),                                                lambda s: BOLD+FG["wht"]+BG["blu"]+s+RESET),

    # ADB/도구/컴포넌트 식별
    (re.compile(r"\badb(?:\.exe)?\b"),      lambda s: UL+FG["cyn"]+s+RESET),
    (re.compile(r"\bminicap\b"),            lambda s: FG["mag"]+s+RESET),
    (re.compile(r"\bminitouch\b"),          lambda s: FG["blu"]+s+RESET),
    (re.compile(r"\bpoco\b|\bairtest\b"),   lambda s: FG["mag"]+s+RESET),

    # 시스템 명령/서브시스템
    (re.compile(r"\bgetprop\b|\bdumpsys\b|\bsettings\b|\buiautomator\b|\bscreencap\b"), lambda s: FG["cyn"]+s+RESET),

    # 상태/전이 (성공/성립/연결/포워드/스킵/미지원 등)
    (re.compile(r"\bconnected\b|\bconnection established\b|\bready\b|\bsucceeded\b|\bok\b", re.I), lambda s: BOLD+FG["grn"]+s+RESET),
    (re.compile(r"\bforward\b|\b--no-rebind\b"),                                            lambda s: FG["ylw"]+s+RESET),
    (re.compile(r"\bskipped\b|\bnot supported\b"),                                          lambda s: FG["ylw"]+s+RESET),

    # GC
    (re.compile(r"\bGC\b|concurrent copying GC|Concurrent mark sweep"), lambda s: FG["gry"]+s+RESET),

    # 포트/프로세스/경로(보조 가독성)
    (re.compile(r"\btcp:\d+\b"),                   lambda s: FG["cyn"]+s+RESET),
    (re.compile(r"[A-Za-z]:\\[^\s]+|/data/[^\s]+"),lambda s: DIM+FG["gry"]+s+RESET),

    # 타임스탬프/모듈 (<airtest.core...>) 약화
    (re.compile(r"^\[\d{2}:\d{2}:\d{2}\]"),        lambda s: DIM+s+RESET),
    (re.compile(r"<[^>]+>"),                       lambda s: DIM+s+RESET),
]

def colorize(line: str) -> str:
    s = line.rstrip("\r\n")
    s = TAG_PAT.sub(normalize_tag, s)       # 1) 정규화
    for rx, fx in TAG_RULES:                # 2) 태그 배경 라벨
        s = rx.sub(lambda m: fx(m.group(0)), s)
    for rx, fx in EXTRA:                    # 3) 그 외 다채로운 필터
        s = rx.sub(lambda m: fx(m.group(0)), s)
    return s

def main():
    for raw in sys.stdin:
        try:
            print(colorize(raw))
        except Exception:
            print(raw, end="")
    try: sys.stdout.flush()
    except: pass

if __name__ == "__main__":
    main()
