# 🛠️ QA Automation Toolkit

Android 앱 QA를 위한 **자동화 실행 · 로그 수집 · 리소스 모니터링 · 리포트 생성**을 하나의 흐름으로 통합한  
**Windows 기반 QA Automation Toolkit**입니다.

Airtest / Poco 기반 UI 자동화와 ADB 로그 분석, GUI 도구를 결합하여  
실무 QA 환경에서 **즉시 활용 가능한 도구 체계**를 목표로 설계되었습니다.

---

## ✨ 주요 특징

- Airtest + Poco 기반 Android 자동화 테스트
- GUI 기반 단말 선택 및 자동화 실행
- logcat 이벤트 자동 수집 (ANR / CRASH / GC / STEP)
- CPU / Memory 실시간 리소스 모니터링
- 테스트 결과 자동 리포트 생성 (PDF / CSV / JSON)
- Python / ADB / PATH / 환경변수 자동 설정

---

## 🖥️ 실행 환경

- **OS**: Windows 10 / 11
- **Python**: 3.11.x (권장)
- **Shell**: PowerShell 5.1
- **ADB**: Android Platform-Tools
- **대상 앱**: Android (Native / Unity)

---

## 📁 프로젝트 폴더 구조

```text
Toolkit/
├─ 00_install/                    # 환경 설정 및 설치
│  ├─ QA Toolkit 환경 설정기.exe   # 통합 설치 실행 파일
│  ├─ setup_env.ps1               # 패키지 설치 / ADB 점검
│  ├─ setup_wizard_gui.py         # 환경변수 설정 GUI
│  ├─ requirements.txt            # 필요한 파이썬 패키지 목록
│  ├─ qa_env_var.txt              # 환경변수 사전 세팅 파일
│  └─ setup_logs/                 # 설치 로그
│
├─ qa_common/                     # 자동화 공통 모듈 (패키지 아님)
│  ├─ common.py                   # Airtest / Poco 공통 유틸
│  └─ _accounts/
│     └─ *_accounts.json          # 앱별 계정 풀
│  └─ _secrets/
│     └─ gdrive_credentials.json  # Google Drive OAuth 클라이언트 ID
│
├─ 99_scripts/                    # 앱별 자동화 스크립트
│  ├─ literacy_test.air/
│  │  ├─ literacy_runner.py
│  │  ├─ content_actions.py
│  │  └─ basic_tc_suite.py
│  └─ other_app.air/
│
├─ result/                        # 테스트 결과 (단말별 분리)
│  └─ <serial>/
│     ├─ airtest_log/
│     ├─ events.csv
│     ├─ logcat_recent_*.txt
│     ├─ logcat_slice_*.txt
│     └─ resource_report_*.pdf
│
├─ platform-tools/                # Android SDK platform-tools (adb)
│  └─ adb.exe
│
├─ scrcpy/                        # scrcpy 실행 파일
│  └─ scrcpy.exe
│
├─ color_pipe.py                  # 콘솔 로그 컬러 출력 파이프
├─ event_tap.py                   # logcat 이벤트 수집기
├─ generate_report.py             # 테스트 결과 리포트 생성
├─ resource_monitor_gui.py        # 리소스 모니터 GUI
├─ logfile_viewer_gui.py          # 로그파일 뷰어 GUI
├─ logfile_to_html.py             # 로그파일 html 컨버터
├─ qa_control_center_gui.py       # QA Control Center (통합 실행 GUI)
├─ QA Control Center.exe          # QA Control Center 실행 파일
├─ 리소스 모니터 GUI.exe           # 리소스 모니터 GUI 실행 파일
└─ 로그파일 뷰어 GUI.exe           # 로그파일 뷰어 GUI 실행 파일
```
---

## ⚙️ 환경 변수

본 툴킷은 **전역 환경 변수 기반 실행**을 전제로 설계되었습니다.

| 환경 변수 | 설명 |
|----------|------|
| `QA_SCRIPT` | Tools 루트 폴더 경로 |
| `QA_TOOLKIT` | 공통 모듈(예: `common.py`)이 위치한 폴더 경로 |
| `QA_PYTHON` | Python 실행 파일(`python.exe`) 경로 |
| `ADB_SERIAL` | 대상 단말 시리얼 (선택) |
| `ANDROID_SERIAL` | `ADB_SERIAL`과 동일 목적(호환) |
| `RESULT_DIR` | 테스트 결과 저장 경로 (실행 시 자동 생성/설정) |
| `QA_MAIL_USER` | 메일 발송 계정(선택) |
| `QA_MAIL_TO` | 메일 수신자(선택) |
| `QA_MAIL_PASS` | 메일 앱 비밀번호(선택) |

> 환경 변수는 사전 설정 파일 또는 **환경 설정 GUI(Setup Wizard)** 를 통해 설정할 수 있습니다.  
> 보안 정책상 `QA_MAIL_PASS`는 파일 저장을 지양하고, 필요한 경우 OS 환경변수로만 유지하는 방식을 권장합니다.

---

## 🧰 설치 및 실행 가이드

1. **한글 경로가 포함되지 않은 위치에 압축 해제**  
   - 예: `D:\QA\Tools` (권장)

2. **Python 3.11.9 설치**  
   - 다운로드: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
   - 설치 시 파이썬 환경 변수 등록(Add Python to environment variables) 옵션 체크(필수)
   - 설치 경로에 띄어쓰기 불가(Program Files 내부 설치 하지 말것)
   - 기존 Python을 교체하지 않고 **개별 폴더에 설치**한 뒤, 이후 설정 단계에서 경로 지정 가능

3. **Airtest 설치 (선택)**  
   - https://airtest.netease.com/  
   - Poco 객체 확인(AirtestIDE 활용)이 필요한 경우에만 설치 (자동화 실행 자체에는 필수 아님)

4. **`QA_MAIL_PASS`(Google 앱 비밀번호) 설정 (선택)**
   - 테스트 결과 메일 송신을 위한 앱 비밀번호 설정으로 필수 아님 (단, 미설정 시 결과 메일 송신 불가)
   - 참고: https://support.google.com/accounts/answer/185833?hl=ko

5. **사전 환경변수 세팅 (선택)**  
   - _환경 설정기 실행 시 UI 입력란을 통해 필요한 환경 변수를 입력 받으므로 **하기의 내용은 참고만** 할 것_
   - `00_install/qa_env_var.txt`에 값을 미리 입력하여 설치 시 자동 반영
   - 템플릿: `qa_env_var_Template.txt` 참고
   - **주의**: 변수명은 변경하지 말고 **경로 값만 수정**  
     - `QA_SCRIPT`: 툴 루트 폴더  
     - `QA_TOOLKIT`: 공통 모듈 폴더(예: `common.py` 위치)

6. **환경 설정기 실행 (필수)**  
   - `00_install/QA Tools 환경 설정기.exe` 실행  
   - 자동 수행 항목(구성에 따라 일부 생략될 수 있음):
     - 필수 Python 패키지 설치
     - ADB / scrcpy 점검(탐색)
     - 환경 변수 설정(또는 설정 마법사 실행)
   - 오류 발생 시: 환경 변수 → 사용자 변수 → Path의 상단에 Python 3.11.x 경로 등록(필수) 확인 후 재 실행

7. **계정 풀 설정 (필수, 사용하는 경우)**  
   - `qa_common/_accounts/{PACKAGE}_accounts.json` 하위의 계정 JSON 파일에 테스트 계정 입력
     ```json
      {
        "accounts": ["id1", "id2", "id3"],
        "secrets": {"id1": "pw1", "id2": "pw2", "id3": "pw3"},
        "leased": {}
      }
     ```
   - 예) 문해력의 경우, `com.kyowon.literacy_accounts.json` - 사용하는 문해력 계정 입력

8. **디바이스 연결 (필수)**  
   - Android 개발자 옵션 활성화 → **USB 디버깅 ON**  
   - 연결 확인:
     ```bat
     adb devices
     ```

9. **자동화 실행 (GUI)**  
   - `QA Control Center.exe` 실행  
   - 스크립트 선택 예시: `99_scripts/.../basic_test.py`  
   - 실행 모드: **모든 단말 실행 / 선택 단말 실행**

---

## 🧩 도구 구성 및 역할

### **🧭 QA Control Center**
QA 실행과 도구 접근을 하나로 묶은 중앙 허브

- **역할**
  - QA 스크립트 실행, 단말 선택, scrcpy 및 리소스 모니터 실행을 한 화면에서 제어하는 통합 런처

- **주요 기능**
  - ADB 기반 단말 자동 탐지 및 선택
  - Python / Airtest 스크립트 실행 (단일·다중 단말)
  - 컬러 콘솔 출력(color_pipe 연동)
  - scrcpy, Resource Monitor GUI 즉시 실행

- **장점**
  - QA 실행 흐름의 표준화
  - 반복 테스트 및 멀티 단말 테스트 효율 극대화
  - CLI 기반 도구의 GUI 통합으로 진입 장벽 감소

- **개선 방향**
  - 실행 이력 관리, 스크립트 프리셋, 결과 요약 표시

---
### **📊 Resource Monitor GUI**
리소스와 로그를 함께 관찰하는 통합 모니터링 도구

- **역할**
  - 테스트 실행 중 CPU·메모리 사용량과 logcat 로그를 동시에 관찰하는 QA 전용 모니터

- **주요 기능**
  - CPU / 메모리(PSS) 실시간 수집
  - 패키지·PID 기준 리소스 추적
  - logcat 실시간 뷰어 내장
  - STEP / ANR / CRASH / GC 이벤트 강조 표시

- **장점**
  - 리소스 변화와 로그 이벤트를 하나의 흐름으로 파악 가능
  - 테스트 단계(STEP) 기준 성능 분석 가능
  - 성능 이슈를 정량 데이터로 설명 가능

- **개선 방향**
  - 리소스 그래프–로그 타임라인 연계 강화, 구간 선택 분석

---
### **📜 Logfile Viewer GUI**
대용량 로그를 빠르게 분석하기 위한 전용 뷰어

- **역할**
  - logcat 로그를 QA 관점에서 읽기 쉽고 분석 가능하게 제공하는 로그 분석 도구

- **주요 기능**
  - 대용량 로그 파일 안정적 로딩
  - 로그 레벨 / STEP / ANR / CRASH / GC 필터
  - 태그별 고정 색상, 키워드 검색 및 강조
  - 실시간 tail 모드 지원

- **장점**
  - 로그 분석 시간 대폭 단축
  - QA 인력이 로그 구조를 깊이 알지 않아도 분석 가능
  - Resource Monitor와 동일한 이벤트 기준 유지

- **개선 방향**
  - 이벤트 요약 자동화, 리포트/이슈 템플릿 연계

---
### **🔗 한 줄 정리**
- QA Control Center: 실행
- Resource Monitor GUI: 관찰
- Logfile Viewer GUI: 분석

이 세 도구가 합쳐져 QA 실행 → 성능 관찰 → 원인 분석 흐름을 완성

---

## 🧪 테스트 스크립트 작성 가이드 (요약)

- 모든 테스트 스크립트는 **공통 모듈(`qa_common`)을 통해 실행 환경을 통일**합니다.
- 단말 정보, 결과 저장 경로 등은 **환경 변수 기반으로 자동 처리**합니다.
- 테스트 로직은 다음 흐름을 권장합니다:
  1. 테스트 환경 초기화
  2. 앱 실행 및 준비 상태 확인
  3. 기능 단위 테스트 수행
  4. 실패 시 증적(스크린샷 / 로그) 확보
  5. 테스트 종료 및 리포트 생성

- 권장 사항:
  - 하나의 스크립트는 **하나의 테스트 목적**에 집중
  - 반복 가능한 구조로 작성하여 재실행 비용 최소화
  - UI 요소 탐색 실패, 네트워크 지연 등 **실무 환경 예외 상황을 고려한 방어 코드 작성**

---

## 🎯 설계 의도

- QA 업무 흐름을 **실행 → 모니터링 → 분석 → 리포트**로 단순화
- 자동화 스크립트와 GUI 도구를 함께 제공하여 **진입 장벽 최소화**
- 반복 테스트 환경에서 **재현성·안정성·가시성**을 동시에 확보
- “데모용 자동화”가 아닌 **실무에서 실제로 쓰이는 QA 도구**를 목표로 설계

---

## 👤 제작자

- **Eden Kim**
- QA Automation / Tooling
- Android 앱 테스트 자동화 및 QA 도구 설계·개발
