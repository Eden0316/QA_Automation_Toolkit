# ================================================
# 📦 QA Toolkit 통합 설치 (전역 pip 버전 + ADB 점검)
# 👤 Author: Eden Kim
# 📅 Date: 2026-02-06 - v1.0.6
#   - setup_wizard_gui 항상 실행되도록 수정: Python 3.11이 아니더라도 실행
#   - Python 3.11 검사 강화
#   - PATH 우선순위 정책 강화: qa_env_var.txt 있어도 바로 적용 되지 않도록 수정
#   - 스모크 테스트 추가: googleapiclient
# ================================================
# - 권장 Python: 3.11.9  (3.12+ 비권장)
# - ADB(Android Debug Bridge) 점검/안내 포함
# - 환경 변수 설정 파일(qa_env_var.txt) 로딩 지원
# - pip 전역 설치 (가상환경 미사용)
# - Airtest, Poco, 리포트, 오피스 관련 패키지 설치
# - .venv 미사용, requirements.txt 우선 설치
# - 사내 프록시/인덱스 설정 가능 (주석 참고)
# - PowerShell 5.1 기준
# - 설치 로그: Tools\00_install\setup_logs\setup_YYMMDD_HHMM.log
# - 설정 마법사(setup_wizard_gui.py) 자동 실행 지원
# - scrcpy 설치 권장 안내 포함
# - Pandoc 바이너리 설치 안내 포함
# ================================================

# setup_env.ps1 (Tools\00_install 기준 최종 패치)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}

# ------------------------------------------------------------
# InstallRoot = Tools\00_install
# ToolsRoot   = Tools
# ------------------------------------------------------------
$InstallRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsRoot   = Split-Path -Parent $InstallRoot

# 로그
$LogDir = Join-Path $InstallRoot "setup_logs"
if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Stamp  = Get-Date -Format "yyMMdd_HHmm"
$Log    = Join-Path $LogDir ("setup_{0}.log" -f $Stamp)

function Write-Log {
  param([string]$Message)
  # 콘솔 출력
  Write-Host $Message
  # 파일 기록(잠금 충돌 방지)
  Add-Content -LiteralPath $Log -Value $Message -Encoding UTF8
}

function Install-OptionalPip {
  param(
    [string[]]$PyCmd,
    [string]$Spec
  )
  try {
    Write-Log "📦 (옵션) 설치 시도: $Spec"
    Run-Python -PyCmd $PyCmd -PyArgs @("-m","pip","install",$Spec) |
      Tee-Object -FilePath $Log -Append
    Write-Log "✅ (옵션) 설치 완료: $Spec"
    return $true
  } catch {
    Write-Log "⚠ (옵션) 설치 실패(무시하고 계속): $Spec"
    Write-Log "   - $($_.Exception.Message)"
    return $false
  }
}


Write-Host "============================================"
Write-Host " 📦 QA Toolkit 환경 설정기 (PowerShell 5.1)"
Write-Host "--------------------------------------------"
Write-Host " InstallRoot: $InstallRoot"
Write-Host " ToolkitRoot  : $ToolsRoot"
Write-Host " Log        : $Log"
Write-Host "============================================`n"

# --- (A) ToolsRoot\platform-tools가 있으면 세션 PATH에 임시 추가 ---
$LocalPlatformTools = Join-Path $ToolsRoot "platform-tools"
if (Test-Path (Join-Path $LocalPlatformTools "adb.exe")) {
  $env:PATH = "$LocalPlatformTools;$env:PATH"
  Write-Log "✅ 로컬 platform-tools 감지 → 세션 PATH 임시 추가: $LocalPlatformTools"
} else {
  Write-Log "ℹ 로컬 platform-tools 미감지(권장 동봉 경로): $LocalPlatformTools"
}

# --- ADB 점검 ---
function Check-Adb {
  $adbCmd = $null
  try { $adbCmd = (Get-Command adb -ErrorAction Stop) } catch {}
  if (-not $adbCmd) {
    Write-Host "⚠ adb.exe 가 PATH에 없습니다." -ForegroundColor Yellow
    Write-Log  "⚠ ADB 미감지: PATH에 adb.exe 없음"

    Write-Host ""
    Write-Host "👉 설치 가이드(필수)"
    Write-Host "  권장: Tools\platform-tools\adb.exe 로 동봉"
    Write-Host "  또는 Android SDK Platform-Tools 설치 후 PATH 등록"
    Write-Host '  예) setx /M PATH "$env:PATH;C:\Android\platform-tools"'
    Write-Host ""
    return $false
  }

  Write-Log ("✅ ADB 감지: {0}" -f $adbCmd.Path)
  try {
    & adb start-server | Tee-Object -FilePath $Log -Append | Out-Null
    $dev = & adb devices
    Write-Log  "adb devices:`n$dev"
    if ($dev -match "unauthorized") {
      Write-Host "⚠ 단말에서 USB 디버깅 허용을 승인하세요(unauthorized)." -ForegroundColor Yellow
    }
  } catch {
    Write-Log  "⚠ adb devices 실패: $($_.Exception.Message)"
  }
  return $true
}
Check-Adb | Out-Null

# --- scrcpy 점검(가이드) ---
function Find-ScrcpyInTools {
  param(
    [string]$ToolsRoot,
    [int]$MaxDepth = 6
  )

  # 제외 폴더(검색 비용/오탐 줄이기)
  $exclude = @(".git", "venv", ".venv", "__pycache__", "node_modules", "dist", "build")

  # 우선순위 후보(빠른 경로)
  $cands = @(
    (Join-Path $ToolsRoot "scrcpy\scrcpy.exe"),
    (Join-Path $ToolsRoot "tools\scrcpy\scrcpy.exe"),
    (Join-Path $ToolsRoot "_deps\scrcpy\scrcpy.exe")
  )
  foreach ($c in $cands) {
    if (Test-Path $c) { return $c }
  }

  # Tools 하위 전체 검색(깊이 제한 + 제외 폴더)
  try {
    $rootItem = Get-Item -LiteralPath $ToolsRoot -ErrorAction Stop
    $rootFull = $rootItem.FullName.TrimEnd('\')

    $items = Get-ChildItem -LiteralPath $ToolsRoot -Recurse -File -Filter "scrcpy.exe" -ErrorAction SilentlyContinue

    foreach ($it in $items) {
      $full = $it.FullName
      # 깊이 제한
      $rel = $full.Substring($rootFull.Length).TrimStart('\')
      $depth = ($rel -split '\\').Count
      if ($depth -gt $MaxDepth) { continue }

      # 제외 폴더 경로 포함 시 스킵
      $skip = $false
      foreach ($ex in $exclude) {
        if ($full -match ("\\{0}\\" -f [regex]::Escape($ex))) { $skip = $true; break }
      }
      if ($skip) { continue }

      return $full
    }
  } catch {
    return $null
  }

  return $null
}

function Check-Scrcpy {
  # 1) PATH
  try {
    $p = (Get-Command scrcpy -ErrorAction Stop).Path
    if ($p) {
      Write-Log "✅ scrcpy 감지(PATH): $p"
      return $true
    }
  } catch {}

  # 2) Tools 하위 검색
  $found = Find-ScrcpyInTools -ToolsRoot $ToolsRoot -MaxDepth 6
  if ($found) {
    Write-Log "✅ scrcpy 감지(Tools 하위 검색): $found"

    # (선택) 세션 PATH에 임시 추가: scrcpy.exe가 있는 폴더
    $dir = Split-Path -Parent $found
    if ($env:PATH -notmatch [regex]::Escape($dir)) {
      $env:PATH = "$dir;$env:PATH"
      Write-Log "ℹ scrcpy 폴더를 세션 PATH에 임시 추가: $dir"
    }
    return $true
  }

  Write-Log "⚠ scrcpy 미감지"
  Write-Log "👉 가이드: scrcpy를 Tools 하위 아무 폴더에 두어도 되지만, 권장 위치는 Tools\\scrcpy\\scrcpy.exe"
  return $false
}
Check-Scrcpy | Out-Null

# --- (B) 설정 마법사 실행 조건 ---
$EnvTxt = Join-Path $InstallRoot "qa_env_var.txt"
$Wizard = Join-Path $InstallRoot "setup_wizard_gui.py"
$Req    = Join-Path $InstallRoot "requirements.txt"

function Get-EnvTxtValue {
  param(
    [string]$Key,
    [string]$Path
  )
  if (-not (Test-Path $Path)) { return $null }

  # setx KEY "VALUE"  또는 setx KEY VALUE
  $pattern1 = "(?im)^\s*setx\s+$([regex]::Escape($Key))\s+`"([^`"]*)`"\s*$"
  $pattern2 = "(?im)^\s*setx\s+$([regex]::Escape($Key))\s+([^\r\n]+)\s*$"

  try {
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop

    $m = [regex]::Match($raw, $pattern1)
    if ($m.Success) { return $m.Groups[1].Value.Trim() }

    $m = [regex]::Match($raw, $pattern2)
    if ($m.Success) {
      $v = $m.Groups[1].Value.Trim()
      # 주석/빈값 방지
      if ($v -match "^\s*[;#]" ) { return $null }
      return $v
    }
  } catch {}
  return $null
}

function Has-Value {
  param(
    [string]$Key
  )

  # 1) 현재 세션 환경변수
  $envV = (Get-Item -Path "Env:$Key" -ErrorAction SilentlyContinue).Value
  if ($envV -and $envV.Trim().Length -gt 0) { return $true }

  # 2) qa_env_var.txt에 기록된 값
  $txtV = Get-EnvTxtValue -Key $Key -Path $EnvTxt
  if ($txtV -and $txtV.Trim().Length -gt 0) { return $true }

  return $false
}

function Need-Wizard {
  # 기존 placeholder 기준도 유지(방어적)
  if (Test-Path $EnvTxt) {
    try {
      $t = Get-Content -LiteralPath $EnvTxt -Raw -ErrorAction Stop
      if ($t -match "앱비밀번호" -or $t -match "사용자아이디") { return $true }
    } catch {}
  }

  $required = @(
    "QA_TOOLKIT",
    "QA_SCRIPT",
    "QA_PYTHON",
    "QA_MAIL_USER",
    "QA_MAIL_TO",
    "QA_MAIL_SMTP",
    "QA_MAIL_PASS"
  )

  foreach ($k in $required) {
    if (-not (Has-Value -Key $k)) {
      Write-Log "🧩 Wizard 필요: $k 값이 환경변수/qa_env_var.txt 모두에 없음"
      return $true
    }
  }
  return $false
}

function Load-EnvFromTxtToSession {
  param(
    [string]$Path,
    [switch]$Force
  )

  if (-not (Test-Path $Path)) {
    Write-Log "ℹ qa_env_var.txt 없음 → 세션 로드 스킵"
    return
  }

  $keys = @(
    "QA_TOOLKIT","QA_SCRIPT","QA_PYTHON","QA_MAIL_USER","QA_MAIL_TO","QA_MAIL_SMTP",
    "QA_PYTHON_PATH_FIX","QA_PYTHON_PATH_MODE","QA_PYTHON_EXCLUDE_WINDOWSAPPS"
  )
  foreach ($k in $keys) {
    $v = Get-EnvTxtValue -Key $k -Path $Path
    if ($v -and $v.Trim().Length -gt 0) {
      $cur = (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue).Value

      if ($Force) {
        Set-Item -Path "Env:$k" -Value $v
        if ($cur -and $cur.Trim().Length -gt 0 -and $cur.Trim() -ne $v.Trim()) {
          Write-Log "🔁 세션 환경변수 갱신(Force): $k = $cur -> $v"
        } else {
          Write-Log "✅ 세션 환경변수 로드(Force): $k = $v"
        }
      } else {
        if ($cur -and $cur.Trim().Length -gt 0) {
          Write-Log "ℹ 세션 환경변수 유지(이미 값 존재): $k = $cur"
        } else {
          Set-Item -Path "Env:$k" -Value $v
          Write-Log "✅ 세션 환경변수 로드(qa_env_var.txt): $k = $v"
        }
      }
    }
  }

  # QA_MAIL_PASS는 qa_env_var.txt에 저장하지 않으므로 여기서 로드 대상 아님(정책 유지)
  # 필요하면 Wizard가 setx로만 저장한 값을 레지스트리에서 읽어오는 확장도 가능하지만,
  # '첫 실행'에서 메일 기능이 필수가 아니라면 여기서 강제할 필요는 없음.
}


# ------------------------------------------------------------
# (C) QA_PYTHON 기반 사용자 PATH 우선순위 강제
#  - QA_PYTHON_PATH_FIX: "1"이면 적용, 그 외 미적용
#  - QA_PYTHON_PATH_MODE: KEEP | REMOVE
#  - QA_PYTHON_EXCLUDE_WINDOWSAPPS: "1"이면 WindowsApps 제외
# ------------------------------------------------------------

function Get-EffectiveValue {
  param(
    [string]$Key,
    [string]$Default = $null
  )

  $envV = (Get-Item -Path "Env:$Key" -ErrorAction SilentlyContinue).Value
  if ($envV -and $envV.Trim().Length -gt 0) { return $envV.Trim() }

  $txtV = Get-EnvTxtValue -Key $Key -Path $EnvTxt
  if ($txtV -and $txtV.Trim().Length -gt 0) { return $txtV.Trim() }

  return $Default
}

function Normalize-PathToken {
  param([string]$P)
  if (-not $P) { return $null }
  try {
    $x = $P.Trim()
    if ($x.Length -eq 0) { return $null }
    # 따옴표 제거
    $x = $x.Trim('"')
    # 후행 \ 제거(루트 제외)
    if ($x.Length -gt 3) { $x = $x.TrimEnd('\') }
    return $x
  } catch {
    return $P
  }
}

function Is-PythonCandidatePath {
  param(
    [string]$P,
    [bool]$ExcludeWindowsApps = $true
  )

  if (-not $P) { return $false }
  $n = $P.ToLowerInvariant()

  if ($ExcludeWindowsApps -and $n -like "*\microsoft\windowsapps*") {
    return $true
  }

  # 공식 설치 경로/명명 패턴 기반(보수적)
  if ($n -like "*\programs\python\python*") { return $true }  # %LOCALAPPDATA%\Programs\Python\Python311\
  if ($n -match "\\python\d{2,3}\\") { return $true }         # \Python311\
  if ($n -like "*\python*\scripts") { return $true }          # \Python311\Scripts

  return $false
}

function Build-NewUserPath {
  param(
    [string[]]$ExistingTokens,
    [string]$QaPythonDir,
    [string]$QaScriptsDir,
    [ValidateSet("KEEP","REMOVE")] [string]$Mode = "KEEP",
    [bool]$ExcludeWindowsApps = $true
  )

  $qa1 = Normalize-PathToken $QaPythonDir
  $qa2 = Normalize-PathToken $QaScriptsDir

  $normalized = New-Object System.Collections.Generic.List[string]
  foreach ($t in $ExistingTokens) {
    $nt = Normalize-PathToken $t
    if ($nt) { $normalized.Add($nt) }
  }

  # Python 후보 분리
  $pyTokens = New-Object System.Collections.Generic.List[string]
  $otherTokens = New-Object System.Collections.Generic.List[string]

  foreach ($t in $normalized) {
    $isPy = Is-PythonCandidatePath -P $t -ExcludeWindowsApps $ExcludeWindowsApps
    if ($isPy) { $pyTokens.Add($t) } else { $otherTokens.Add($t) }
  }

  # QA python 경로는 무조건 최상단
  $result = New-Object System.Collections.Generic.List[string]
  if ($qa1) { $result.Add($qa1) }
  if ($qa2 -and (Test-Path $qa2)) { $result.Add($qa2) }

  # 중복 제거용(대소문자 무시)
  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($x in $result) { [void]$seen.Add($x) }

  # 우선 non-python
  foreach ($t in $otherTokens) {
    if (-not $seen.Contains($t)) {
      $result.Add($t)
      [void]$seen.Add($t)
    }
  }

  if ($Mode -eq "KEEP") {
    # python 후보는 맨 뒤로(삭제하지 않음)
    foreach ($t in $pyTokens) {
      # QA python 경로와 동일한 건 제외
      if ($qa1 -and ($t -ieq $qa1)) { continue }
      if ($qa2 -and ($t -ieq $qa2)) { continue }
      if (-not $seen.Contains($t)) {
        $result.Add($t)
        [void]$seen.Add($t)
      }
    }
  } else {
    # REMOVE: python 후보는 제거
  }

  return ,$result.ToArray()
}

function Update-UserPathForQAPython {
  param(
    [string]$QaPythonExe,
    [ValidateSet("KEEP","REMOVE")] [string]$Mode = "KEEP",
    [bool]$ExcludeWindowsApps = $true
  )

  if (-not $QaPythonExe) {
    Write-Log "ℹ PATH 우선순위: QA_PYTHON 비어있음 → 스킵"
    return
  }
  if (-not (Test-Path $QaPythonExe)) {
    Write-Log "⚠ PATH 우선순위: QA_PYTHON 경로가 존재하지 않음 → 스킵: $QaPythonExe"
    return
  }

  $qaDir = Split-Path -Parent $QaPythonExe
  $qaScripts = Join-Path $qaDir "Scripts"

  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not $userPath) { $userPath = "" }

  $tokens = $userPath -split ';'
  $newTokens = Build-NewUserPath -ExistingTokens $tokens -QaPythonDir $qaDir -QaScriptsDir $qaScripts -Mode $Mode -ExcludeWindowsApps $ExcludeWindowsApps
  $newPath = ($newTokens -join ';')

  if ($newPath -eq $userPath) {
    Write-Log "ℹ PATH 우선순위: 변경 사항 없음 (Mode=$Mode, ExcludeWindowsApps=$ExcludeWindowsApps)"
  } else {
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    # 현재 세션에도 즉시 반영(설치기 진행 중 python/pip 호출 안정화)
    $env:Path = $newPath
    Write-Log "✅ 사용자 PATH 업데이트 완료: QA_PYTHON 최상단 적용 (Mode=$Mode, ExcludeWindowsApps=$ExcludeWindowsApps)"
    Write-Log "   - QA Dir    : $qaDir"
    if (Test-Path $qaScripts) { Write-Log "   - QA Scripts: $qaScripts" }
  }
}

function Apply-QAPythonPathPolicy {
  # 적용 여부
  $fix = Get-EffectiveValue -Key "QA_PYTHON_PATH_FIX" -Default "0"
  if ($fix -ne "1") {
    Write-Log "ℹ PATH 우선순위: QA_PYTHON_PATH_FIX != 1(기본 OFF) → 스킵"
    return
  }

  $mode = (Get-EffectiveValue -Key "QA_PYTHON_PATH_MODE" -Default "KEEP").ToUpperInvariant()
  if ($mode -ne "KEEP" -and $mode -ne "REMOVE") { $mode = "KEEP" }

  $exWa = Get-EffectiveValue -Key "QA_PYTHON_EXCLUDE_WINDOWSAPPS" -Default "1"
  $excludeWindowsApps = ($exWa -eq "1")

  $qaPythonExe = Get-EffectiveValue -Key "QA_PYTHON" -Default $null

  Update-UserPathForQAPython -QaPythonExe $qaPythonExe -Mode $mode -ExcludeWindowsApps:$excludeWindowsApps
}


# --- Python 후보 탐색: QA_PYTHON → py -3.11 → python ---
function Get-PythonCandidate {
  # 반환값: 항상 [string[]] 형태로 유지되도록 단일 반환엔 콤마(,) 사용

  if ($env:QA_PYTHON -and (Test-Path $env:QA_PYTHON)) {
    return ,$env:QA_PYTHON
  }

  try {
    $py = (Get-Command py -ErrorAction Stop).Path
    if ($py) { return @("py", "-3.11") }
  } catch {}

  try {
    $p = (Get-Command python -ErrorAction Stop).Path
    if ($p) { return ,$p }
  } catch {}

  return $null
}

function Run-Python {
  param(
    [string[]]$PyCmd,     # 예: @("py","-3.11") 또는 @("C:\...\python.exe")
    [string[]]$PyArgs     # 예: @("-m","pip","install",...)
  )

  if (-not $PyCmd -or $PyCmd.Count -eq 0) { throw "PyCmd is empty" }

  $cmdLine = ($PyCmd + $PyArgs) -join ' '
  Write-Log "RUN> $cmdLine"

  if ($PyCmd.Count -gt 1) {
    & $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)]) @PyArgs
  } else {
    & $PyCmd[0] @PyArgs
  }
}

function Test-Python311 {
    param(
        [string]$QaPythonPath
    )

    $result = [PSCustomObject]@{
        Has311 = $false
        Reason = @()
        QaPythonExists = $false
        QaPythonIs311 = $false
        PyLauncherHas311 = $false
    }

    # 1) QA_PYTHON 경로 검증
    if (-not [string]::IsNullOrWhiteSpace($QaPythonPath)) {
        if (Test-Path $QaPythonPath) {
            $result.QaPythonExists = $true
            try {
                $ver = & $QaPythonPath --version 2>&1
                if ($ver -match "Python\s+3\.11(\.|$)") {
                    $result.QaPythonIs311 = $true
                    $result.Has311 = $true
                    return $result
                } else {
                    $result.Reason += "QA_PYTHON이 존재하지만 3.11이 아님: $ver"
                }
            } catch {
                $result.Reason += "QA_PYTHON 실행 실패: $($_.Exception.Message)"
            }
        } else {
            $result.Reason += "QA_PYTHON 경로가 존재하지 않음: $QaPythonPath"
        }
    } else {
        $result.Reason += "QA_PYTHON이 설정되어 있지 않음"
    }

    # 2) py 런처에서 3.11 유무 검사 (py가 없으면 여기서도 안내)
    $py = (Get-Command py -ErrorAction SilentlyContinue)
    if ($null -ne $py) {
        try {
            # py -0p : 설치된 파이썬 목록(경로 포함)
            $list = & py -0p 2>&1
            if ($list -match "\b3\.11\b") {
                $result.PyLauncherHas311 = $true
                $result.Has311 = $true
                return $result
            } else {
                $result.Reason += "py 런처에서 Python 3.11을 찾지 못함 (py -0p 결과에 3.11 없음)"
            }
        } catch {
            $result.Reason += "py -0p 실행 실패: $($_.Exception.Message)"
        }
    } else {
        $result.Reason += "py 런처(py.exe)가 없음"
    }

    return $result
}

function Show-Python311Guidance {
    param(
        [string]$QaPythonPath
    )

    $r = Test-Python311 -QaPythonPath $QaPythonPath

    if (-not $r.Has311) {
        Write-Host ""
        Write-Host "🧩 Python 3.11이 필요합니다. (권장: 3.11.9)" -ForegroundColor Yellow
        Write-Host " - 원인:" -ForegroundColor Yellow
        foreach ($x in $r.Reason) {
            Write-Host "   • $x" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "✅ 조치 방법(택1):" -ForegroundColor Cyan
        Write-Host "  1) Python 3.11 설치/Repair 후 재실행 (py -0p에 3.11이 보여야 함)" -ForegroundColor Cyan
        Write-Host "  2) qa_env_var.txt의 QA_PYTHON을 3.11 python.exe 실제 경로로 수정 후 재실행" -ForegroundColor Cyan
        Write-Host "     예) QA_PYTHON=C:\Users\Owner\AppData\Local\Programs\Python\Python311\python.exe" -ForegroundColor Cyan
        Write-Host ""
    }

    return $r
}

# Wizard는 어떤 상황에서도 먼저 실행(입력 UX) - 사용자는 스킵 가능
$needWizard = Need-Wizard
if ($needWizard) {
  Write-Log "🧩 필수 변수 누락 감지: Wizard에서 입력 권장"
} else {
  Write-Log "ℹ 필수 변수는 이미 존재하지만, 정책상 Wizard를 항상 실행합니다."
}

# ❌ 정책 변경: Wizard 실행 전에는 qa_env_var.txt를 세션에 주입하지 않음
# - 잘못된 qa_env_var.txt가 Wizard 프리필 1순위를 오염시키는 문제 방지
# Load-EnvFromTxtToSession -Path $EnvTxt

$py311Status = Show-Python311Guidance -QaPythonPath $env:QA_PYTHON

if (-not $py311Status.Has311) {
    Write-Host "⚠ Python 3.11이 준비되지 않았습니다. Wizard에서 QA_PYTHON을 올바른 3.11 경로로 설정하거나 3.11 설치/Repair를 진행하세요." -ForegroundColor Yellow
    # throw 하지 말 것 (Wizard를 띄워서 수정 기회 제공)
} else {
  Write-Log "✅ Python 3.11 준비 완료"
}

function Get-WizardPythonCmd {
    # 1) QA_PYTHON이 유효하면 그걸로
    if ($env:QA_PYTHON -and (Test-Path $env:QA_PYTHON)) {
        return @($env:QA_PYTHON)
    }

    # 2) py 런처에서 3.11 시도
    $py = (Get-Command py -ErrorAction SilentlyContinue)
    if ($null -ne $py) {
        try {
            $v = (& py -3.11 --version 2>&1) -join "`n"
            if ($v -match "Python\s+3\.11") { return @("py","-3.11") }
        } catch {}
        # 3) 없으면 3.10으로라도 Wizard 실행(입력 받기 목적)
        try {
            $v = (& py -3.10 --version 2>&1) -join "`n"
            if ($v -match "Python\s+3\.10") { return @("py","-3.10") }
        } catch {}
        # 4) 최신 Python 3 (예: 3.13만 있는 경우 여기로)
        try {
            $v = (& py -3 --version 2>&1) -join "`n"
            if ($v -match "Python\s+3\.") { return @("py","-3") }
        } catch {}
    }

    # 5) 최후: python (PATH)
    return @("python")
}

Write-Log "🧩 설정 마법사 실행(항상) - 사용자가 스킵 가능"

if (Test-Path $Wizard) {
  $wizPyCmd = Get-WizardPythonCmd
  if (-not $wizPyCmd) {
    Write-Log "❌ Python 미감지: Wizard 실행 불가. (QA_PYTHON/py/python 모두 실패) Python 설치 후 재시도 필요."
    throw "python-not-found"
  }

  Write-Log ("Wizard 실행 Python: {0}" -f ($wizPyCmd -join ' '))

  $wizExit = -1
  try {
    # Wizard는 스킵 시 ExitCode=2로 종료(아래 wizard 패치 기준)
    Run-Python -PyCmd $wizPyCmd -PyArgs @($Wizard) | Tee-Object -FilePath $Log -Append

    $wizExit = $LASTEXITCODE
    Write-Log "Wizard 종료 코드: $wizExit"

    if ($wizExit -eq 2) {
      Write-Log "ℹ 사용자가 Wizard를 스킵했습니다. 설치는 계속 진행합니다."
    } elseif ($wizExit -ne 0) {
      Write-Log "⚠ Wizard 비정상 종료(코드 $wizExit). 설치는 계속 진행합니다."
    }
  } catch {
    Write-Log "⚠ 설정 마법사 실행 실패: $($_.Exception.Message)"
    # Wizard 실패해도 설치 자체는 진행할 수 있게(요구사항: 스킵 가능)
    Write-Log "ℹ Wizard 실행 실패 → 설치를 계속 진행합니다."
  }
} else {
  Write-Log "⚠ setup_wizard_gui.py 없음: 수동 설정 필요"
}

# Wizard 실행 직후: '적용(ExitCode=0)'일 때만 qa_env_var.txt를 Force로 세션 재로딩
if ($wizExit -eq 0) {
  if (Test-Path $EnvTxt) {
    Write-Log "🔁 Wizard 적용 완료 → qa_env_var.txt 재감지 → 세션 Force 재로딩"
    Load-EnvFromTxtToSession -Path $EnvTxt -Force
  } else {
    Write-Log "⚠ Wizard는 0으로 종료됐지만 qa_env_var.txt가 없습니다: $EnvTxt"
  }
} else {
  # 2=사용자 스킵/취소, 그 외=비정상 종료 포함
  Write-Log "ℹ Wizard 미적용(ExitCode=$wizExit) → qa_env_var.txt Force 재로딩 스킵"
}

# ✅ Wizard 이후 최종 확인: 여전히 3.11 없으면 중단(설치 단계 차단)
$py311Status2 = Show-Python311Guidance -QaPythonPath $env:QA_PYTHON
if (-not $py311Status2.Has311) {
  Write-Host "❌ Wizard 이후에도 Python 3.11이 확인되지 않습니다. Python 3.11 설치/경로 설정 후 재시도하세요." -ForegroundColor Red
  throw "python-311-required"
}

# ✅ Wizard에서 QA_PYTHON/정책 값이 갱신됐을 수 있으므로 즉시 PATH 정책 적용
try {
  Apply-QAPythonPathPolicy
} catch {
  Write-Log "⚠ PATH 우선순위 정책 적용 실패(설치는 계속): $($_.Exception.Message)"
}

# 필수 키(비민감) 최소 충족 재검증 (PASS는 파일 저장 대상 아님)
$mustKeys = @("QA_TOOLKIT","QA_SCRIPT","QA_PYTHON","QA_MAIL_USER","QA_MAIL_TO","QA_MAIL_SMTP")
$stillMissing = @()
foreach ($k in $mustKeys) {
  $v = (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue).Value
  if (-not $v -or $v.Trim().Length -eq 0) { $stillMissing += $k }
}
if ($stillMissing.Count -gt 0) {
  Write-Log ("⚠ Wizard 이후에도 세션에 비어있는 값이 있습니다: " + ($stillMissing -join ", "))
  Write-Log "   - 원인 후보: qa_env_var.txt 저장 실패/잠금, Wizard에서 공란으로 적용, 또는 파일 경로 불일치"
}


# ✅ Wizard를 실행하지 않았더라도, 기존 설정 기반으로 PATH 정책 1회 적용
try {
  Apply-QAPythonPathPolicy
} catch {
  Write-Log "⚠ PATH 우선순위 정책 적용 실패(설치는 계속): $($_.Exception.Message)"
}

# 설치용 Python 다시 확정(마법사에서 QA_PYTHON 설정했을 수도 있음)
$PyCmd = Get-PythonCandidate
Write-Log ("DEBUG PyCmdType: {0}, Count: {1}" -f $PyCmd.GetType().FullName, $PyCmd.Count)

if (-not $PyCmd) {
  Write-Log "❌ Python 을 찾지 못했습니다. 3.11.x (64-bit) 설치 후 재시도하세요."
  throw "python-not-found"
}
Write-Log ("현재 Python 후보: {0}" -f ($PyCmd -join ' '))

# 버전 체크 (Run-Python으로 통일: PS 5.1에서 가장 안전)
$verOut = (Run-Python -PyCmd $PyCmd -PyArgs @("--version") 2>&1) | Out-String
$verOut = $verOut.Trim()
Write-Log "현재 Python 버전: $verOut"

# pip 업그레이드
Write-Log "🔄 pip/setuptools/wheel 업데이트"
Run-Python -PyCmd $PyCmd -PyArgs @("-m","pip","install","--upgrade","pip","setuptools","wheel") |
  Tee-Object -FilePath $Log -Append

# 패키지 설치
Write-Log "📦 패키지 설치 시작"
if (Test-Path $Req) {
  Write-Log "📄 requirements.txt 감지(InstallRoot) → 설치"
  Run-Python -PyCmd $PyCmd -PyArgs @("-m","pip","install","-r",$Req) |
    Tee-Object -FilePath $Log -Append
} else {
  Write-Log "🧩 requirements.txt 없음 → 기본 세트 설치"
  $pkgs = @(
    "airtest>=1.3,<2.0",
    "pywin32>=306",
    "matplotlib>=3.7,<3.9",
    "reportlab>=3.6,<4.0",
    "openpyxl>=3.1,<4.0",
    "python-docx>=0.8.11,<1.0",
    "python-pptx>=0.6.21,<1.0",
    "odfpy>=1.4,<2.0",
    "pypandoc>=1.13,<2.0"
  )
  Run-Python -PyCmd $PyCmd -PyArgs @("-m","pip","install") + $pkgs |
    Tee-Object -FilePath $Log -Append
}
# pocoui는 선택 설치(환경/인덱스에 따라 실패 가능)
Install-OptionalPip -PyCmd $PyCmd -Spec "pocoui>=1.0,<2.0" | Out-Null

Write-Log "🔎 pip 패키지 요약(airtest/poco/pocoui 확인용)"
Run-Python -PyCmd $PyCmd -PyArgs @("-m","pip","list") | Tee-Object -FilePath $Log -Append

# 스모크 테스트 (pocoui는 환경 차이 대비: optional)
Write-Log "🔎 임포트 스모크 테스트"
$TmpPy = Join-Path $env:TEMP ("qa_setup_smoke_{0}.py" -f (Get-Date -Format 'yyMMdd_HHmmssfff'))

$PyCode = @'
import importlib

mods_required = ("airtest","poco","pypandoc","matplotlib","openpyxl","googleapiclient")
# opcional package 설치 여부는 dist 기준으로 확인 (pip 패키지명과 import 모듈명이 불일치할 수 있음)
dists_optional = ("pocoui",)

ok = True

def try_import(name: str, required: bool = True):
    global ok
    try:
        importlib.import_module(name)
        print("OK:", name)
        return True
    except Exception as e:
        if required:
            ok = False
            print("FAIL:", name, "->", repr(e))
        else:
            print("WARN(opt):", name, "->", repr(e))
        return False

def try_dist(dist_name: str):
    # Python 3.11+는 importlib.metadata 내장
    try:
        from importlib.metadata import version
        v = version(dist_name)
        print("OK(opt-dist):", dist_name, v)
        return True
    except Exception as e:
        print("WARN(opt-dist):", dist_name, "->", repr(e))
        return False

for m in mods_required:
    try_import(m, required=True)

for d in dists_optional:
    try_dist(d)

print("SMOKE:", "OK" if ok else "FAIL")
'@

Set-Content -LiteralPath $TmpPy -Value $PyCode -Encoding UTF8 -Force
try {
  Run-Python -PyCmd $PyCmd -PyArgs @($TmpPy) | Tee-Object -FilePath $Log -Append
} finally {
  Remove-Item -LiteralPath $TmpPy -ErrorAction SilentlyContinue
}

$PyCmdStr = ($PyCmd -join ' ')

Write-Log "ℹ pypandoc 사용 시 Pandoc 바이너리 필요(없으면 변환 기능 실패 가능)."
Write-Log "🎉 완료! 로그: $Log"

Write-Host "`n✅ 설치 완료"
Write-Host ("   - InstallRoot: {0}" -f $InstallRoot)
Write-Host ("   - ToolsRoot  : {0}" -f $ToolsRoot)
Write-Host ("   - Python     : {0}" -f $PyCmdStr)
Write-Host ("   - Log        : {0}" -f $Log)
exit 0
