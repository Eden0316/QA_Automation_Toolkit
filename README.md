# **🛠️ QA Automation Toolkit**

👤 Author: Eden Kim

📅 Date: 2025-12-24 - QA 자동화 도구 최초 배포

- QA 환경 설정기(00_install), QA Tools (Root), 자동화 스크립트(99_scripts, qa_common) 포함 통합 파일(scrcpy 포함)

---
## 🧰 설치 및 실행 가이드

1. **한글 경로가 포함되지 않은 위치에 압축 해제**  
   - 예: `D:\QA\Tools` (권장)

2. **Python 3.11.9 설치**  
   - 다운로드: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe  
   - 설치 시 파이썬 환경 변수 등록(Add Python to environment variables) 옵션 체크(필수)
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

## 📚 도구 소개

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
