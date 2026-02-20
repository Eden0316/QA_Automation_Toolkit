# Common 함수 활용 가이드

이 문서는 자동화 스크립트 작성 시 사용하는 `common.py`의 공용 함수들의 활용법을 정리한 가이드입니다.

## 목차

1. [환경 설정 및 초기화](#환경-설정-및-초기화)
2. [앱 제어](#앱-제어)
3. [UI 상호작용](#ui-상호작용)
4. [탐색 및 스크롤](#탐색-및-스크롤)
5. [플로우 관리](#플로우-관리)
6. [이미지/템플릿 매칭](#이미지템플릿-매칭)
7. [유틸리티 함수](#유틸리티-함수)
8. [리소스 모니터링](#리소스-모니터링)
9. [계정 관리](#계정-관리)
10. [예외 처리](#예외-처리)

---

## 환경 설정 및 초기화

### QAEnv 클래스

테스트 실행 환경을 관리하는 핵심 클래스입니다.

```python
env = QAEnv(
    package="com.kyowon.literacy.store",      # 앱 패키지명
    script_dir=SCRIPT_DIR,                    # 스크립트 디렉토리
    out_dir_root=OUT_ROOT,                    # 결과 출력 루트 디렉토리
    serial=None,                              # 디바이스 시리얼 (None이면 자동 감지)
    per_device_dir=True,                      # 디바이스별 디렉토리 생성 여부
    restart_delay=3.0,                        # 앱 재시작 대기 시간
    ui_mode="native",                         # "native" 또는 "unity"
    app_start=literacy_start,                 # 앱 시작 콜백 함수
    on_ready=app_ready,                       # 앱 준비 완료 콜백
    on_close=logout,                          # 앱 종료 전 처리 콜백
    airtest_script=__file__,                 # Airtest 스크립트 경로
    suite="basic_tc_suite",                   # 테스트 스위트 명칭
    runner="literacy_runner",                  # 러너 명칭
    use_run=True,                             # Run 표준 디렉토리 구조 사용 여부
    mail_max_attach=20,                       # 메일 첨부 파일 최대 개수
    gdrive_enable=True,                       # Google Drive 업로드 활성화
    gdrive_folder_id="...",                   # Google Drive 폴더 ID
    gdrive_share_anyone=True                  # Google Drive 공유 설정
)

# 패키지 별칭 설정 (리소스 ID 자동 치환용)
env.package_aliases = ["com.kyowon.literacy", "com.kyowon.literacy.store"]

# 예외 처리기 등록
def _literacy_exc_handler(exc: Exception, e: QAEnv) -> int:
    return handle_exceptions()
env.handle_exceptions = _literacy_exc_handler

# 현재 환경 등록 (다른 함수에서 env 인자 없이 사용 가능)
set_current_env(env)
```

### set_current_env / use_env

현재 실행 환경을 전역으로 설정하고 사용합니다.

```python
# 환경 설정
set_current_env(env)

# 다른 함수에서 사용 (env 인자 없이 호출 가능)
def some_function(env: Optional[QAEnv] = None):
    env = use_env(env)  # 인자가 없으면 전역 env 사용
    # ...
```

### configure_account_pool

계정 풀 파일을 설정합니다.

```python
configure_account_pool(pool_name="com.kyowon.literacy.store_accounts")
# 결과: _accounts/com.kyowon.literacy.store_accounts.json
```

---

## 앱 제어

### restart_app

앱을 재시작합니다.

```python
restart_app(retries=3, app_start=literacy_start, env=None)
# retries: 재시도 횟수
# app_start: 앱 시작 콜백 함수 (선택)
```

**사용 예시:**
```python
restart_app()
permission_check()
```

### app_ready

앱이 준비될 때까지 대기하고, 로그인 화면이면 로그인을 수행합니다.

```python
def app_ready(timeout=15, interval=0.5):
    """
    주어진 timeout 동안:
      - 로그인 화면 보이면 → login 실행
      - 메인 화면 보이면 → 플로우 진행
    """
    # ...
    return True  # 준비 완료
```

**사용 예시:**
```python
if need_app_ready:
    app_ready()
```

### handle_exceptions

앱 실행 중 발생하는 예상 가능한 예외 상황을 처리합니다.

```python
def handle_exceptions(debug=False):
    rules = [
        {
            "name": "팝업 닫기",
            "condition": cond_exists(poco("com.kyowon.literacy:id/btn_popup_close")),
            "action": act_click(poco("com.kyowon.literacy:id/btn_popup_close")),
        },
        # ...
    ]
    handled = handle_expected_exceptions(
        rules=rules,
        handle_all=True,   # 여러 개 한 번에 처리
        stop_after=2,       # 무한루프 방지 상한
    )
    return handled
```

**사용 예시:**
```python
handle_exceptions()  # 플로우 중간에 호출하여 예외 상황 처리
```

---

## UI 상호작용

### must_click / try_click

요소를 클릭합니다.

```python
# 반드시 성공해야 하는 경우
must_click(poco("com.kyowon.literacy:id/btn_login"), "로그인 버튼 클릭")

# 실패해도 계속 진행하는 경우
try_click(poco("com.kyowon.literacy:id/btn_optional"), "선택 버튼 클릭", fast=True)
```

**파라미터:**
- `poco_obj`: Poco 요소
- `desc`: 설명 (로그에 기록)
- `timeout`: 타임아웃 (기본 5초)
- `fast`: 빠른 클릭 모드 (기본 False)

### must_type / try_type

텍스트를 입력합니다.

```python
# 반드시 성공해야 하는 경우
must_type(poco("com.kyowon.literacy:id/et_id"), "user@example.com", "아이디 입력")

# 실패해도 계속 진행하는 경우
try_type(poco("com.kyowon.literacy:id/et_optional"), "text", "선택 입력")
```

**파라미터:**
- `poco_obj`: Poco 요소
- `value`: 입력할 텍스트
- `desc`: 설명
- `enter`: 입력 후 Enter 키 전송 여부 (기본 True)

### must_check / try_check

요소의 존재 여부를 확인합니다.

```python
# 반드시 존재해야 하는 경우
must_check(poco("com.kyowon.literacy:id/top_right_menu"), "메뉴 버튼 확인")

# 존재 여부만 확인 (실패해도 계속 진행)
if try_check(poco("com.kyowon.literacy:id/popup"), "팝업 확인", timeout=5):
    must_click(poco("com.kyowon.literacy:id/btn_close"), "팝업 닫기")
```

**파라미터:**
- `poco_obj`: Poco 요소
- `desc`: 설명
- `timeout`: 타임아웃 (기본 5초)

### must_drag / try_drag_with_roi

요소를 드래그합니다.

```python
# 기본 드래그
must_drag(
    start_src=poco("com.kyowon.literacy:id/dragItem"),
    end_dst=poco("com.kyowon.literacy:id/dropTarget"),
    desc="항목 드래그"
)

# 오프셋 포함 드래그
must_drag(
    start_src=poco("com.kyowon.literacy:id/dragItem"),
    end_dst=poco("com.kyowon.literacy:id/dropTarget"),
    desc="항목 드래그",
    src_offset=(400, 0),  # 시작점 오프셋
    dst_offset=(0, 0)      # 끝점 오프셋
)

# ROI 변화로 성공 여부 판단하는 드래그
ok = try_drag_with_roi(
    start_src=poco("com.kyowon.literacy:id/left_dot"),
    end_dst=poco("com.kyowon.literacy:id/right_dot"),
    desc="선긋기 드래그",
    debug=False
)
```

---

## 탐색 및 스크롤

### try_find_click

스크롤하면서 요소를 찾아 클릭합니다.

```python
find_ok = try_find_click(
    target_element=poco("com.kyowon.literacy:id/week_scroll_view")
                     .offspring("android.widget.TextView", text="9주차"),
    direction="left",                    # 스크롤 방향: "left", "right", "up", "down"
    step_ratio=0.25,                     # 스크롤 단계 비율 (0.0~1.0)
    duration=0.6,                        # 스크롤 지속 시간
    methods_order=["poco", "global", "adb", "image", "coord"],  # 탐색 방법 순서
    scroll_view=poco("com.kyowon.literacy:id/week_scroll_view"),  # 스크롤 뷰
    max_cycles=4,                         # 최대 탐색 반복 횟수
    debug=False
)
```

**사용 예시:**
```python
# 주차 찾기
target_element = poco("com.kyowon.literacy:id/week_scroll_view").offspring("android.widget.TextView", text="9주차")
scroll_view = poco("com.kyowon.literacy:id/week_scroll_view")
find_ok = try_find_click(
    target_element=target_element,
    direction="left",
    step_ratio=0.25,
    duration=0.6,
    methods_order=["poco"],
    scroll_view=scroll_view,
    max_cycles=4,
    debug=False
)
if not find_ok:
    # 반대 방향으로 재시도
    find_ok = try_find_click(
        target_element=target_element,
        direction="right",
        step_ratio=0.25,
        duration=0.6,
        methods_order=["poco"],
        scroll_view=scroll_view,
        max_cycles=4,
        debug=False
    )
```

### scroll_until_visible

요소가 보일 때까지 스크롤합니다.

```python
scroll_until_visible(
    target_element=poco(text="초등 읽기 프로젝트 퍼펙트 문해"),
    direction="right",
    step_ratio=0.5,
    duration=0.5,
    scroll_view=poco("kr.co.kyowon.launcher:id/recycler_view"),
    debug=False,
)
```

### click_until_disappear

요소가 사라질 때까지 클릭합니다.

```python
click_until_disappear(
    target_poco=poco("com.android.permissioncontroller:id/permission_allow_foreground_only_button"),
    fallback_poco=None,  # 대체 클릭 대상
    desc="권한 허용 팝업 - 앱 사용 중에만 허용",
    interval=0.5,        # 클릭 간격
    max_loop=30          # 최대 반복 횟수
)
```

**사용 예시:**
```python
# 튜토리얼 닫기
click_until_disappear(
    target_poco=poco("com.kyowon.literacy:id/btn_next"),
    fallback_poco=poco("com.kyowon.literacy:id/btn_start"),
    desc="튜토리얼",
    interval=0.5
)
```

---

## 플로우 관리

### run_flows

여러 플로우를 순차적으로 실행합니다.

```python
run_flows(
    flows=[
        ("내 프로필 선택", flow_myprofile),
        ("학습 리포트", flow_study_report),
    ],
    env=env,
    repeat=2,                    # 반복 횟수
    send_success_mail_each=False,  # 각 플로우마다 성공 메일 전송 여부
    stop_on_fail=False,          # 실패 시 중단 여부
    mail_to=None,                # 메일 수신자
    mail_cc=None,                # 메일 참조
    mail_bcc=None                # 메일 숨은 참조
)
```

### run_subflows

서브 플로우들을 실행하고, 실패 시 재시작 함수를 호출합니다.

```python
run_subflows(
    (flow_main_first_entry, "술술 읽기 훈련 진입"),
    (flow_first_leading_adv, "독서 탐험"),
    (flow_first_training_1, "술술 읽기 훈련1"),
    restart_sub=restart_first_training,  # 실패 시 재시작 함수
    group_desc="술술 읽기 훈련",          # 그룹 설명
)
```

**사용 예시:**
```python
def restart_first_training():
    restart_app()
    app_ready()
    find_target_week()
    must_click(poco("com.kyowon.literacy:id/btn_main_first"), "술술 읽기 훈련 재진입")

run_subflows(
    (flow_first_leading_adv, "독서 탐험"),
    (flow_first_training_1, "술술 읽기 훈련1"),
    restart_sub=restart_first_training,
    group_desc="술술 읽기 훈련",
)
```

### step_block

함수를 실행하고 결과를 리포트에 기록합니다.

```python
def my_league_func():
    must_click(poco("com.kyowon.literacy:id/btn_league_info"), "리그 정보 클릭")
    must_click(poco("android.widget.ImageButton"), "리그 정보 닫기")

step_block(my_league_func, "📋 [Basic Test / 기능] 나의 학습 정보 > 나의 보상 > 나의 리그")
```

---

## 이미지/템플릿 매칭

### pick_best_template

여러 템플릿 중 가장 일치하는 것을 선택합니다.

```python
badge = poco("com.kyowon.literacy.store:id/left_top_layout").offspring("com.kyowon.literacy.store:id/img_step")
templates = {
    "1단계": "level1.png",
    "2단계": "level2.png",
    "3단계": "level3.png",
    "4단계": "level4.png",
}

label, score = pick_best_template(
    badge,
    templates=templates,
    accept_threshold=0.45,    # 최소 매칭 점수
    use_blob=False,           # blob 후보 탐지 사용 여부
    use_color_sig=False,      # 색상 점수 사용 여부
    debug=False
)

if label:
    TARGET_LEVEL = label
    step(f"{label} 감지(score={score:.3f}) → TARGET_LEVEL 설정")
```

**사용 예시:**
```python
# 포인트 템플릿 매칭
point_templates = {
    "핫도그": r"first_06_point_1.png",
    "지팡이": r"first_06_point_2.png",
    "당근":  r"first_06_point_3.png",
}

best_label, best_score = pick_best_template(
    None,
    templates=point_templates,
    accept_threshold=0.40,
    use_blob=False,
    use_color_sig=False,
    debug=True,
)

if not best_label:
    raise RuntimeError("포인트 템플릿 매칭 실패")
```

### tap_images

이미지 템플릿을 찾아 연속으로 터치합니다.

```python
layer = poco("com.kyowon.literacy:id/layout_content")
tap_images(
    img_path=r"first_07_point.png",
    layer_poco=layer,
    threshold=0.78,
    color_mean_abs_max=14,
    color_pixel_diff_max=18,
    color_ratio_min=0.92,
    debug=False,
)
```

**사용 예시:**
```python
# 포인트 이미지 연속 터치
img_path = point_templates[best_label]
tap_images(img_path=img_path, layer_poco=layer, debug=False)
```

### tap_color_words

색상이 다른 단어들을 찾아 터치합니다.

```python
layer = poco("com.kyowon.literacy:id/layout_content").offspring("com.kyowon.literacy:id/txt_content")

def close_popup():
    must_click(poco("com.kyowon.literacy:id/btn_popup_close"), "팝업 닫기 클릭")

tap_color_words(
    layer_poco=layer,
    verify_fn=lambda: poco("com.kyowon.literacy:id/btn_popup_close").exists(),
    popup_close_fn=close_popup,
    debug=False,
)
```

### drag_right_from_target

타겟 이미지에서 오른쪽으로 드래그합니다.

```python
target = r"first_12_point.png"
layer = poco("com.kyowon.literacy:id/layout_content").offspring("com.kyowon.literacy:id/scrollview")
drag_right_from_target(
    target=target,
    layer_poco=layer,
    done_poco=poco("com.kyowon.literacy:id/btnRetry"),  # 완료 확인 요소
    debug=False,
)
```

---

## 유틸리티 함수

### step

로그에 단계를 기록합니다.

```python
step("로그인 시도")
step("메인 화면 발견 → flow 진행", shot=True)  # 스냅샷 포함
```

### soft_fail

실패를 기록하지만 테스트를 계속 진행합니다.

```python
soft_fail(f"{target_week} 탐색: FAIL ❌")
soft_fail("영상 컨트롤러 감지: FAIL ❌(3회 시도 모두 실패)", shot=True)  # 스냅샷 포함
```

### note

참고 사항을 기록합니다.

```python
note("[RISK] 실패 증거 산출물 확보 중 오류(일부 첨부 누락 가능)")
```

### get_label

Poco 요소의 라벨(텍스트)을 가져옵니다.

```python
label = get_label(poco("com.kyowon.literacy:id/selectionText"))
step(f"보기 선택({label})")
```

**사용 예시:**
```python
# 드래그 항목의 라벨 가져오기
for answer in answers:
    label = get_label(answer.offspring("com.kyowon.literacy:id/selectionText"))
    must_drag(answer, target, f"보기 선택({label})")
```

### parse_progress

진행률 텍스트를 파싱합니다.

```python
done, num, den, raw = parse_progress(poco("com.kyowon.literacy:id/progressText"))
# done: 완료 여부 (bool)
# num: 현재 진행 수 (int)
# den: 전체 진행 수 (int)
# raw: 원본 텍스트 (str)

if done and not poco("com.kyowon.literacy:id/btnRetry").exists():
    step("마지막 문제 감지 → 풀이 진행")
```

**사용 예시:**
```python
# 진행률 체크
done, num, den, raw = parse_progress(poco("com.kyowon.literacy:id/progressText"))
if done and poco("com.kyowon.literacy:id/btnRetry").exists():
    step(f"진행률 도달: {raw or f'{num}/{den}'}")
    break
```

### repeat_action_until_exists

요소가 나타날 때까지 액션을 반복합니다.

```python
def first_03_func():
    if try_check(poco("com.kyowon.literacy:id/layout_attach_ui").offspring("com.kyowon.literacy:id/btn_complete", enabled=True), "다음 버튼 활성화 감지", timeout=60):
        must_click(poco("com.kyowon.literacy:id/layout_attach_ui").offspring("com.kyowon.literacy:id/btn_complete"), "다음 버튼 클릭")

repeat_action_until_exists(
    poco_obj=poco("com.kyowon.literacy:id/btnRetry"),
    action_fn=first_03_func,
    desc="다시 하기 버튼 대기",
    timeout_sec=120.0,
    interval_sec=0.3
)
```

### is_bgm_playing

배경음악이 재생 중인지 확인합니다.

```python
if is_bgm_playing():
    step("배경음 ON 확인 완료")
else:
    step("배경음 OFF 확인 완료")
```

**사용 예시:**
```python
# 배경음 설정 토글 확인
if is_bgm_playing():
    must_check(poco("com.kyowon.literacy:id/switch_bgm", checked=True), "배경음 설정 ON 확인")
    must_click(poco("com.kyowon.literacy:id/switch_bgm"), "배경음악 끄기")
    time.sleep(1.0)
    if not is_bgm_playing():
        step("배경음 OFF 확인 완료")
```

### _get_resolution / _get_region_from_poco

화면 해상도와 Poco 요소의 영역을 가져옵니다.

```python
from common import _get_resolution, _get_region_from_poco

# 화면 해상도 가져오기
W, H = _get_resolution()

# Poco 요소의 영역 가져오기
obj = poco("com.kyowon.literacy:id/player_view")
x1, y1, x2, y2 = _get_region_from_poco(obj, screen_w=W, screen_h=H, debug=False)

# 중심 좌표 계산
obj_x = int((x1 + x2) / 2)
obj_y = int((y1 + y2) / 2)
```

**사용 예시:**
```python
# 영상 컨트롤러 감지용 좌표 계산
obj = poco("com.kyowon.literacy:id/player_view")
obj_W, obj_H = _get_resolution()
obj_x1, obj_y1, obj_x2, obj_y2 = _get_region_from_poco(obj, screen_w=obj_W, screen_h=obj_H, debug=False)

# 우측 하단 좌표
obj_x = int((obj_x1 + obj_x2) / 2)
obj_y = int(obj_y2 - 70)
touch((obj_x, obj_y))
```

---

## 리소스 모니터링

### start_resource_monitor

리소스 모니터링을 시작합니다.

```python
proc = start_resource_monitor(env=env)
# proc: 프로세스 객체 (나중에 종료 시 사용)
```

**사용 예시:**
```python
if need_resource_monitor:
    proc = start_resource_monitor()
```

### stop_resource_monitor

리소스 모니터링을 종료합니다.

```python
stop_resource_monitor(env=env)
```

**사용 예시:**
```python
finally:
    if proc is not None:
        try:
            stop_resource_monitor()
            cleanup_rolling_logs(env.out_dir, env=env, keep_latest=False, max_wait=15)
        except Exception:
            pass
```

### save_log

로그를 저장합니다.

```python
slice_path = save_log(timeout=45, env=env)
# slice_path: 저장된 로그 파일 경로
```

### gen_report

리포트를 생성합니다.

```python
pdf_path = gen_report(timeout=60, env=env)
# pdf_path: 생성된 리포트 파일 경로
```

### cleanup_rolling_logs

롤링 로그 파일을 정리합니다.

```python
cleanup_rolling_logs(
    env.out_dir,
    env=env,
    keep_latest=False,  # 최신 로그 유지 여부
    max_wait=15         # 최대 대기 시간
)
```

---

## 계정 관리

### acquire_account

계정을 임대합니다.

```python
WORKER_ID, uid, pw = acquire_account()
env._acct = (uid, pw)
step(f"[ACCT] acquired: {uid}")
```

**사용 예시:**
```python
# 로그인 함수에서 사용
def login(env: Optional['QAEnv'] = None):
    env = use_env(env)
    if not hasattr(env, "_acct"):
        global WORKER_ID
        WORKER_ID, uid, pw = acquire_account()
        env._acct = (uid, pw)
        step(f"[ACCT] acquired (lazy): {uid}")
    else:
        uid, pw = env._acct
    
    must_type(poco("com.kyowon.literacy:id/et_id"), uid)
    must_type(poco("com.kyowon.literacy:id/et_pw"), pw)
    must_click(poco("com.kyowon.literacy:id/btn_login"), "로그인 버튼 클릭")
```

### release_account

계정을 반납합니다.

```python
if need_account and WORKER_ID:
    try:
        release_account(WORKER_ID)
        step("[ACCT] released")
    except Exception as e:
        step(f"[WARN] account release fail: {e}")
```

---

## 예외 처리

### handle_expected_exceptions

예상 가능한 예외 상황을 규칙 기반으로 처리합니다.

```python
rules = [
    {
        "name": "자세 확인 닫기(다시 보지 않기)",
        "condition": cond_exists(poco("com.kyowon.literacy:id/txt_check_fluency")),
        "action": multi_act(
            act_click(poco("com.kyowon.literacy:id/radio")),
            act_click(poco("android.widget.ImageButton"))
        ),
    },
    {
        "name": "가이드 팝업 닫기(다시 보지 않기)",
        "condition": cond_exists(poco("com.kyowon.literacy:id/txt_today_dont_show")),
        "action": act_click(poco("com.kyowon.literacy:id/btn_skip_today")),
    },
    {
        "name": "로딩 대기하기",
        "condition": cond_exists(poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress")),
        "action": (lambda: poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress").wait_for_disappearance(timeout=60.0)),
    },
]

handled = handle_expected_exceptions(
    rules=rules,
    handle_all=True,   # 여러 개 한 번에 처리하려면 True
    stop_after=2,      # 무한루프 방지 상한
)
```

### 조건 함수들

```python
# 요소 존재 여부 확인
cond_exists(poco("com.kyowon.literacy:id/btn_popup_close"))

# 요소 가시성 확인
cond_visible(poco("com.kyowon.literacy:id/btn_popup_close"))

# 여러 요소 중 하나라도 존재하는지 확인
cond_exists_any([
    poco("com.kyowon.literacy:id/btn1"),
    poco("com.kyowon.literacy:id/btn2"),
])

# 여러 요소 중 하나라도 보이는지 확인
cond_visible_any([
    poco("com.kyowon.literacy:id/btn1"),
    poco("com.kyowon.literacy:id/btn2"),
])
```

### 액션 함수들

```python
# 클릭 액션
act_click(poco("com.kyowon.literacy:id/btn_close"), env=None, wait=0.3)

# 뒤로가기 액션
act_back(env=None, wait=0.2)

# 비율 좌표 터치 액션
act_tap_ratio(xr=0.5, yr=0.5, env=None, wait=0.2)  # 화면 중앙

# 텍스트 입력 액션
act_send_text("text", env=None, wait=0.1)

# 대기 액션
act_sleep(3.0)

# 여러 액션을 순차 실행
multi_act(
    act_click(poco("com.kyowon.literacy:id/radio")),
    act_click(poco("android.widget.ImageButton")),
    act_sleep(0.5)
)
```

---

## 전체 예제

### 기본 TC 스위트 구조

```python
from common import *
from literacy_runner import *

# 설정
SUITE_NAME = "basic_tc_suite"
SUITE_MAX_REPEAT = 1
NEED_RESTART_APP = True
NEED_APP_READY = True
NEED_RESOURCE_MONITOR = True
NEED_ON_CLOSE = False
STOP_ON_FAIL = False

# 플로우 정의
FLOWS = [
    ("탄탄 독해 훈련", "flow_main_second"),
    ("차곡차곡 어휘 상자", "flow_voca_box"),
    ("메뉴", "flow_main_menu"),
]

# 플로우 함수
def flow_main_second():
    def flow_main_second_entry():
        find_target_week()
        must_check(poco("com.kyowon.literacy:id/btn_main_second"), "탄탄 독해 훈련")
        must_click(poco("com.kyowon.literacy:id/btn_main_second"), "탄탄 독해 훈련")
    
    def flow_second_training_1():
        training_menu_open()
        must_click(poco(text="탄탄 독해 훈련1"), "탄탄 독해 훈련1 진입")
        step_block(second_training_func, "탄탄 독해 훈련 기능")
    
    def restart_second_training():
        restart_app()
        app_ready()
        find_target_week()
        must_click(poco("com.kyowon.literacy:id/btn_main_second"), "탄탄 독해 훈련 재진입")
    
    run_subflows(
        (flow_main_second_entry, "탄탄 독해 훈련 진입"),
        (flow_second_training_1, "탄탄 독해 훈련1"),
        restart_sub=restart_second_training,
        group_desc="탄탄 독해 훈련",
    )
    back_main()

# 실행 함수
def run_basic_tc_suite(serial=None):
    flows = _build_flows(FLOWS)
    run_literacy_tc(
        flows, serial=serial,
        suite=SUITE_NAME,
        repeat=SUITE_MAX_REPEAT,
        need_restart_app=NEED_RESTART_APP,
        need_app_ready=NEED_APP_READY,
        need_resource_monitor=NEED_RESOURCE_MONITOR,
        need_on_close=NEED_ON_CLOSE,
        stop_on_fail=STOP_ON_FAIL,
    )

if __name__ == "__main__":
    run_basic_tc_suite(os.environ.get("ANDROID_SERIAL") or os.environ.get("ADB_SERIAL"))
```

---

## 주의사항

1. **env 인자**: 대부분의 함수는 `env` 인자를 선택적으로 받습니다. 전역 환경이 설정되어 있으면 생략 가능합니다.

2. **에러 처리**: `must_*` 함수는 실패 시 예외를 발생시키므로, 반드시 성공해야 하는 경우에만 사용하세요.

3. **타임아웃**: 기본 타임아웃은 5초입니다. 필요에 따라 조정하세요.

4. **스크롤**: `try_find_click`은 여러 방법을 순차적으로 시도하므로, 가장 확실한 방법을 `methods_order`의 앞에 배치하세요.

5. **리소스 모니터링**: `start_resource_monitor`로 시작한 모니터는 반드시 `finally` 블록에서 `stop_resource_monitor`로 종료하세요.

6. **계정 관리**: `acquire_account`로 임대한 계정은 반드시 `release_account`로 반납하세요.

---

## 참고

- 실제 사용 예시는 `literacy_runner.py`, `basic_tc_suite.py`, `content_actions.py`를 참고하세요.
- 더 자세한 함수 시그니처는 `common.py`의 함수 정의를 확인하세요.
