# =================================================
# QA 자동화 스크립트 - 퍼펙트 문해 베이직 TC
# 👤 Author: Eden Kim
# 📅 Date: 2026-02-11 - v1.0.6
#   - 게임 가이드 체크 선택형으로 수정
#   - 주차 찾기 함수 추가 배치
#   - E-Book 기능 사용 여부 체크 변수 추가
#   - 탄탄 독해 훈련 플로우에 공통 기능함수 추가
#   - 스위트 명칭 변경: basic_test → basic_tc_suite
#   - 한 눈에 보는 문해 탐험 코스 개선: subflow 기능 적용
#   - 공통 유틸 변수 생성, Flow 정의 추가
# =================================================
#   - 퍼펙트 문해 베이직 Test(BAT)용 자동화 스크립트
#   - 목표 주차 및 E-Book 기능 사용 여부 설정
# =================================================
# -*- encoding=utf8 -*-
__author__ = "Eden Kim"

import os, sys
# 실행 범용성을 위한 Import 경로 사전 설정
CUR_DIR = os.path.dirname(os.path.abspath(__file__)) # 이 스크립트가 있는 .air 폴더 경로
if CUR_DIR not in sys.path:                          # 여기를 파이썬 모듈 탐색 경로에 강제로 올린다
    sys.path.insert(0, CUR_DIR)
TOOLKIT = os.getenv("QA_TOOLKIT")                    # QA_TOOLKIT도 있으면 같이 올린다
if TOOLKIT and TOOLKIT not in sys.path:
    sys.path.insert(0, TOOLKIT)
from airtest.core.api import *
import literacy_runner as lt
from literacy_runner import *
from content_actions import *
from common import *
from common import _get_resolution, _get_region_from_poco

# ========== 공통 유틸 변수 ==========
SUITE_NAME = "basic_tc_suite"     # 스위트 명칭
SUITE_MAX_REPEAT = 1              # 최대 RUN 반복 횟수
NEED_RESTART_APP = True           # 최초 앱 재시작 필요 여부
NEED_APP_READY = True             # 앱 준비 완료 체크 필요 여부
NEED_RESOURCE_MONITOR = True      # 리소스 모니터링 필요 여부(logcat_log, resource_log 저장 주체)
NEED_ON_CLOSE = False             # 종료 시 처리 필요 여부
STOP_ON_FAIL = False              # 실패 시 중단 여부

# =========== 앱별 변수 ===========
TARGET_WEEK = "10주차"             # 목표 주차
EBOOK_ENABLED = False              # E-Book 기능 사용 여부

# ====== Flow 정의 (미실행 flow는 주석처리) ======
# 형식: ("표시명", "함수명")
FLOWS = [
    # ("나의 보상", "flow_my_reward"),
    # ("학습리포트", "flow_study_report"),
    # ("교과서 어휘 게임", "flow_voca_game"),
    # ("오늘의 어휘", "flow_today_voca"),
    ("술술 읽기 훈련", "flow_main_first"),
    # ("탄탄 독해 훈련", "flow_main_second"),
    # ("오늘의 책", "flow_today_book"),
    # ("문해 탐험 도서관", "flow_literacy_library"),
    # ("문해 탐험 모아보기", "flow_all_contents"),
    ("차곡차곡 어휘 상자", "flow_voca_box"),
    # ("한 눈에 보는 문해 탐험 코스", "flow_literacy_course"),
    ("메뉴", "flow_main_menu"),
]

# ========== 공통 함수 ==========
# ----- def: 주차 찾기
def find_target_week(target_week: str=TARGET_WEEK):
    target_element = poco("com.kyowon.literacy:id/week_scroll_view").offspring("android.widget.TextView", text=target_week)
    scroll_view = poco("com.kyowon.literacy:id/week_scroll_view")
    step(f"타겟 주차({target_week})를 찾습니다...")
    find_ok = try_find_click(
        target_element=target_element,
        direction="left", step_ratio=0.25, duration=0.6,                 # 필수 요소: 스크롤 방향/단계/시간
        methods_order=["poco"],
        scroll_view=scroll_view,                                        # poco 요소: poco 객체
        max_cycles=4,
        debug=False
    )
    if not find_ok:
        find_ok = try_find_click(
            target_element=target_element,
            direction="right", step_ratio=0.25, duration=0.6,                 # 필수 요소: 스크롤 방향/단계/시간
            methods_order=["poco"],
            scroll_view=scroll_view,                                        # poco 요소: poco 객체
            max_cycles=4,
            debug=False
        )

        if not find_ok:
            soft_fail(f"{target_week} 탐색: FAIL ❌")
            raise RuntimeError(f"[ERR] {target_week} 탐색 실패")
    time.sleep(1.0)
    must_click(target_element, f"{TARGET_WEEK} 다시 클릭(안정성 확보)")
    return target_element

# ----- def: 지정 e-Book 찾기 및 오픈
def open_target_ebook(target_title: str, 
                      scroll_view, 
                      anchor_img=r"library_anchor.png"):
    target_element = poco("com.kyowon.literacy:id/item_book_titile", text=target_title).parent().child("com.kyowon.literacy:id/item_book_thumbnail")
    # 타겟 도서 찾기
    for attempt in range(1, MAX_COUNT + 1):
        step(f"타겟 도서({target_title}) 찾기를 시작합니다... {attempt}회")
        ok = try_find_click(
            target_element=target_element,
            direction="down", step_ratio=0.5, duration=0.5,                 # 필수 요소: 스크롤 방향/단계/시간
            methods_order=["poco", "global", "adb", "image", "coord"],
            scroll_view=scroll_view,                                        # poco 요소: poco 객체
            anchor_key="ebook_list", anchor_img=anchor_img, # image 요소: 기준 앵커 이미지
            coord_start=(365, 1108), coord_end=(365, 754),                  # coord 요소: 스크롤 좌표
            debug=False
        )
        time.sleep(1.0)
        if target_element.offspring("com.kyowon.literacy:id/circle_book_thumbnail_prgs").exists():
            target_element.offspring("com.kyowon.literacy:id/circle_book_thumbnail_prgs").wait_for_disappearance(timeout=30.0)
            time.sleep(1.0)

        if target_element.exists():
            ebook_open = try_click(target_element, "타겟 도서 클릭")
            if not ebook_open:
                ok = False
        if ok:
            break  # 성공 → 루프 탈출

        if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
            must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
        elif poco("com.kyowon.literacy:id/btnScrollToTop").exists():
            must_click(poco("com.kyowon.literacy:id/btnScrollToTop"), "맨 위로 이동 클릭")

        time.sleep(0.5)

    else:
        # for 루프가 break 없이 끝났으면 실패가 연속된 것
        soft_fail(f"{target_title} 탐색: FAIL ❌ - {MAX_COUNT}회 탐색 실패")
        raise RuntimeError(
            f"[ERR] {target_title} 탐색 실패 - {MAX_COUNT}회 탐색 실패"
        )
        
# ----- step_block: e-Book 뷰어 기능
def ebook_func():
    time.sleep(2.0)
    if poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress").exists():
        step("로딩 대기")
        poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress").wait_for_disappearance(timeout=60.0)
        time.sleep(1.0)
    if poco(text="ebook은 다운로드 후에 볼 수 있어요.\n다운로드 할까요?").exists():
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "ebook 다운로드 확인")
        sleep(1.0)
    if poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress").exists():
        step("로딩 대기")
        poco("com.kyowon.literacy:id/layout_progress").child("com.kyowon.literacy:id/img_main_boo_k_tower_progress").wait_for_disappearance(timeout=60.0)
        time.sleep(1.0)
    if poco(text="전에 읽던 책이에요. 이어서 볼까요?").exists():
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "이어 읽기")
        sleep(3.0)
    handle_exceptions()
    if poco("뒤로가기").exists():
        try_click(poco("뒤로가기"), "뒤로 가기")
        try_check(poco("com.kyowon.literacy:id/dialog_btn_right"), "종료 팝업 체크")
        sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/dialog_btn_right"), "뷰어 종료")
    elif poco("com.android.systemui:id/back").exists():
        try_click(poco("com.android.systemui:id/back"), "뒤로가기")
        try_check(poco("com.kyowon.literacy:id/dialog_btn_right"), "종료 팝업 체크")
        sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/dialog_btn_right"), "뷰어 종료")
    else:
        keyevent("BACK")
        try_check(poco("com.kyowon.literacy:id/dialog_btn_right"), "종료 팝업 체크")
        sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/dialog_btn_right"), "뷰어 종료")

# ----- step_block: 영상 기능
def video_func():
    handle_exceptions()
    if poco("com.kyowon.literacy:id/img_center_replay").exists():
        try_check(poco("com.kyowon.literacy:id/img_center_replay"), "리플레이 버튼 감지 → 재생")
        must_click(poco("com.kyowon.literacy:id/img_center_replay"), "리플레이 버튼 클릭")
        time.sleep(1.0)
        handle_exceptions()
    if poco("com.kyowon.literacy:id/img_bottom_play_pause").exists():
        try_click(poco("com.kyowon.literacy:id/img_bottom_play_pause"), "재생/일시정지 버튼 클릭", fast=True)
        time.sleep(1.0)
      
    time.sleep(3.0)
    MAX_RETRY = 3
    ok = False

    for attempt in range(1, MAX_RETRY + 1):
        step(f"영상 컨트롤러 감지 시도 {attempt}/{MAX_RETRY}")

        # 1) 반드시 눌러야 하는 뷰
        step(f"화면 영역 클릭 ({attempt}회차)")
        obj = poco("com.kyowon.literacy:id/player_view")
        obj_W, obj_H = _get_resolution()
        obj_x1, obj_y1, obj_x2, obj_y2 = _get_region_from_poco(obj, screen_w=obj_W, screen_h=obj_H, debug=False)

        # 우측 끝(너무 끝이면 클릭 미스/화면 밖 방지용으로 2~8px 안쪽 권장)
        obj_x = int((obj_x1 + obj_x2) / 2)
        obj_y = int(obj_y2 - 70)

        # 필요하면 추가 오프셋 적용(예: (510,0) 같은 방식)
        obj_x += 0
        obj_y += 0

        step("영상 하단 부 2회 터치")
        touch((obj_x, obj_y))
        touch((obj_x, obj_y))

        # 2) 성공 여부가 중요한 체크
        ok = try_check(
            poco("com.kyowon.literacy:id/custom_seekbar"),
            f"영상 컨트롤러 감지 ({attempt}회차)"
        )

        if ok:
            poco_obj = poco("com.kyowon.literacy:id/custom_seekbar")
            W, H = _get_resolution()
            x1, y1, x2, y2 = _get_region_from_poco(poco_obj, screen_w=W, screen_h=H, debug=False)

            # 우측 끝(너무 끝이면 클릭 미스/화면 밖 방지용으로 2~8px 안쪽 권장)
            x = int(x2) - 6
            y = int((y1 + y2) / 2)

            # 필요하면 추가 오프셋 적용(예: (510,0) 같은 방식)
            x += 0
            y += 0
            touch((x, y))
            step(f"⚠️ 영상 컨트롤러 감지 성공 → 영상 시청 완료 시도")
            try_check(poco("com.kyowon.literacy:id/img_center_replay"), "리플레이 버튼 확인", timeout=10)

            break

        step(f"⚠️ 영상 컨트롤러 감지 실패 → 재시도")

    # 3) 최종 실패 처리 (Airtest 리포트 Failed)
    if not ok:
        soft_fail("영상 컨트롤러 감지: FAIL ❌(3회 시도 모두 실패)")
        raise AssertionError(
            "영상 컨트롤러 감지 실패 (3회 시도 모두 실패)"
        )

# ----- def: 단계, 주차 선택 함수
def select_level_week(level: str=None, week: str=None):
    if level:
        must_click(poco("com.kyowon.literacy:id/dropdown_level"), "단계 선택 클릭")
        must_click(poco("android:id/text1", text=level), f"{level} 선택")
    if week:
        must_click(poco("com.kyowon.literacy:id/dropdown_week"), "주차 선택 클릭")
        must_click(poco("android:id/text1", text=week), f"{week} 선택")
    time.sleep(1.0)

# ----- def: 메인으로 돌아가기
def back_main():
    time.sleep(1.0)
    if poco("com.kyowon.literacy:id/btn_exit").exists():
        must_click(poco("com.kyowon.literacy:id/btn_exit"), "나가기")
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"))
    elif poco("com.kyowon.literacy:id/btnOpen").exists():
        must_click(poco("com.kyowon.literacy:id/btnOpen"), "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/btn_exit"), "나가기")
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"))
    elif poco("com.kyowon.literacy:id/btnBack").exists():
        must_click(poco("com.kyowon.literacy:id/btnBack"), "뒤로 가기")
    elif poco("com.kyowon.literacy:id/box_middle_back_btn").exists():
        must_click(poco("com.kyowon.literacy:id/box_middle_back_btn"), "박스(중) 뒤로 가기")
    elif poco("com.kyowon.literacy:id/btn_book_list_back").exists():
        must_click(poco("com.kyowon.literacy:id/btn_book_list_back"), "북리스트 뒤로 가기")
    else:
        keyevent("BACK")
    time.sleep(1.0)
    try_check(poco("com.kyowon.literacy:id/item_weekly_move_bar"), "메인 복귀 확인")

# ========== 플로우 함수 ==========
# 📘 나의 보상
def flow_my_reward():
    # ---------- 나의 보상
    if must_check(poco("com.kyowon.literacy:id/myinfo_layout"), "📋 [Basic Test / 노출] 나의 학습 정보"):
        must_click(poco("com.kyowon.literacy:id/myinfo_layout"), "📋 [Basic Test / 기능] 나의 학습 정보")
        must_click(poco("com.kyowon.literacy:id/btnBack"))
    
    if must_check(poco("com.kyowon.literacy:id/view_go_my_reward"), "📋 [Basic Test / 노출] 나의 학습 정보 > 나의 보상"):
        must_click(poco("com.kyowon.literacy:id/view_go_my_reward"), "📋 [Basic Test / 기능] 나의 학습 정보 > 나의 보상")

        must_click(poco("com.kyowon.literacy:id/btn_my_league"), "나의 리그 클릭")
        if must_check(poco("com.kyowon.literacy:id/txt_my_ranking_name"), "📋 [Basic Test / 노출] 나의 학습 정보 > 나의 보상 > 나의 리그"):
            # ----- step_block: 내부 리그 기능 함수
            def my_league_func():
                must_click(poco("com.kyowon.literacy:id/btn_league_info"), "리그 정보 클릭")
                must_click(poco("android.widget.ImageButton"), "리그 정보 닫기")
                must_click(poco("android.widget.Button"), "최근 리그 이력 더보기")
                must_click(poco("android.widget.ImageButton"), "최근 리그 이력 닫기")
            # 내부 리그 기능 함수 실행
            step_block(my_league_func, "📋 [Basic Test / 기능] 나의 학습 정보 > 나의 보상 > 나의 리그")
        
        must_click(poco("com.kyowon.literacy:id/btn_reward_management"), "나의 보상 클릭")
        if must_check(poco(text="포인트 이력"), "📋 [Basic Test / 노출] 나의 학습 정보 > 나의 보상 > 보상 관리"):
            # ----- step_block: 내부 보상 기능 함수
            def my_reward_func():
                must_click(poco("android.widget.Button"), "포인트 도움말 클릭")
                must_click(poco("android.widget.ImageButton"), "포인트 도움말 닫기")
                must_click(poco(text="포인트 이력"), "포인트 이력 클릭")
                must_click(poco("android.widget.ImageButton"), "포인트 이력 닫기")
            # 내부 보상 기능 함수 실행
            step_block(my_reward_func, "📋 [Basic Test / 기능] 나의 학습 정보 > 나의 보상 > 보상 관리")
        must_click(poco("com.kyowon.literacy:id/btnBack"), "메인 복귀")


# 📘 학습 리포트
def flow_study_report():
    find_target_week()
    # --------- 학습 리포트
    if must_check(poco("com.kyowon.literacy:id/left_bottom_layout"), "📋 [Basic Test / 노출] 나의 학습 정보 > 학습리포트"):
        must_click(poco("com.kyowon.literacy:id/txt_report_name"), "학습리포트 클릭")
        time.sleep(3.0)
        try_check(poco(text="학습 리포트"), "📋 [Basic Test / 기능] 나의 학습 정보 > 학습리포트")
        time.sleep(3.0)
        # 월별 리포트
        must_click(poco("com.kyowon.literacy:id/ctv_month"), "월별 리포트 클릭")
        try_check(poco(text="출석 일수"), "📋 [Basic Test / 노출] 나의 학습 정보 > 학습리포트 > 월별 리포트")
        # ----- step_block: 월별 리포트 기능
        def month_report_func():
            if must_click(poco("com.kyowon.literacy:id/dropdown_second"), "주차 드롭다운 클릭"):
                try_click(poco("android:id/text1", text="14~17주차"))
            if must_click(poco("com.kyowon.literacy:id/dropdown_second"), "주차 드롭다운 클릭"):
                try_click(poco("android:id/text1"))
        # 월별 리포트 기능함수 실행
        step_block(month_report_func, "📋 [Basic Test / 기능] 나의 학습 정보 > 학습리포트 > 월별 리포트")
        # 누적 리포트
        must_click(poco("com.kyowon.literacy:id/ctv_cumulative"), "📋 [Basic Test / 노출] 나의 학습 정보 > 학습리포트 > 누적 리포트")
        # 실전 평가 리포트
        must_click(poco("com.kyowon.literacy:id/ctv_practice_test"), "📋 [Basic Test / 노출] 나의 학습 정보 > 학습리포트 > 실전평가리포트")
        
        must_click(poco("com.kyowon.literacy:id/btn_book_list_back"), "메인 복귀")


# 📘 교과서 어휘 게임
def flow_voca_game():
    must_click(poco("com.kyowon.literacy:id/vocabulary_game"), "교과서 어휘 게임 클릭")
    if try_check(poco("com.kyowon.literacy:id/txt_explain"), "게임 가이드 확인"):
        must_click(poco("com.kyowon.literacy:id/btn_popup_close"), "팝업 닫기")
    # ----- step_block: 어휘 게임 기능
    def voca_game_func():
        must_click(poco("com.kyowon.literacy:id/btn_start"), "게임 시작")
        time.sleep(3.0)
        must_click(poco("com.kyowon.literacy:id/ui_exit"), "나가기")
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "나가기 확인")
        must_click(poco("com.kyowon.literacy:id/btn_alert_exit"), "그만하기")
    step_block(voca_game_func, "📋 [Basic Test / 기능] 교과서 어휘 게임")


# 📘 오늘의 어휘
def flow_today_voca():
    if must_check(poco("com.kyowon.literacy:id/txt_today_vocabulary"), "📋 [Basic Test / 노출] 교과서 어휘 게임 > 오늘의 어휘"):
        # ----- step_block: 오늘의 어휘 기능
        def today_voca_func():
            for _ in range(3):
                must_check(poco("com.kyowon.literacy:id/question_txt"), "어휘 확인")
                must_click(poco("com.kyowon.literacy:id/btn_quiz_option"), "보기 클릭")
                sleep(1.0)
            must_check(poco("com.kyowon.literacy:id/lottieView"), "결과 확인")
        step_block(today_voca_func, "📋 [Basic Test / 기능] 교과서 어휘 게임 > 오늘의 어휘")

# ========== 훈련 서브 함수 ==========
# ----- def: 훈련 메뉴 오픈 
def training_menu_open():
    if poco("com.kyowon.literacy:id/btn_alert_positive").exists():
        must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "어휘놀이 알림 닫기")
        time.sleep(5.0)
    must_click(poco("com.kyowon.literacy:id/btnOpen"), "메뉴 오픈")
    time.sleep(1.0)

# ----- def: 술술 읽기 훈련 재진입
def restart_first_training():
    restart_app()
    app_ready()
    find_target_week()

    must_click(poco("com.kyowon.literacy:id/btn_main_first"), "술술 읽기 훈련 재진입")

# ----- def: 탄탄 독해 훈련 재진입
def restart_second_training():
    restart_app()
    app_ready()
    find_target_week()

    must_click(poco("com.kyowon.literacy:id/btn_main_second"), "탄탄 독해 훈련 재진입")

# ----- step_block: 술술 읽기 훈련 공통 함수
# content_actions.py로 이관 후 유형별 감지 및 기능 수행은 해당 스크립트에서 처리

# ----- step_block: 탄탄 독해 훈련 공통 함수
def second_training_func():
    if poco(text="학습 가이드").exists():
        must_click(poco("com.kyowon.literacy:id/btn_popup_close"), "학습 가이드 닫기")
    if poco(text="오늘의 독해 훈련").exists():
        step("탄탄 독해 훈련 노출: PASS ✅")
        must_click(poco("com.kyowon.literacy:id/btn_guide"), "학습 가이드 클릭")
        must_click(poco("com.kyowon.literacy:id/btn_popup_close"), "학습 가이드 닫기")
    elif poco("com.kyowon.literacy:id/txt_direct").exists():
        step("탄탄 독해 훈련 노출: PASS ✅")
        must_click(poco("com.kyowon.literacy:id/btn_guide"), "학습 가이드 클릭")
        must_click(poco("com.kyowon.literacy:id/btn_popup_close"), "학습 가이드 닫기")
    elif poco("com.kyowon.literacy:id/player_view").exists():
        step("탄탄 독해 훈련(영상) 노출: PASS ✅")
        step_block(video_func, "탄탄 독해 훈련(영상) 기능")
    else:
        step("탄탄 독해 훈련 노출: WARN ⚠️(해당 유형 없음 → SKIP 처리)")
        raise Exception("탄탄 독해 훈련: 해당 유형 없음 → 스킵")

# 📘 1일차 술술 읽기 훈련
def flow_main_first():

    # ========== 술술 읽기 훈련 진입 플로우 ==========
    def flow_main_first_entry():
        find_target_week()
        must_check(poco("com.kyowon.literacy:id/btn_main_first"), "📋 [Basic Test / 노출] 술술 읽기 훈련")
        must_click(poco("com.kyowon.literacy:id/btn_main_first"), "📋 [Basic Test / 기능] 술술 읽기 훈련")

    # ========== 술술 읽기 훈련 서브 플로우 ==========
    # 〰️ 독서 탐험
    def flow_first_leading_adv():
        training_menu_open()
        must_click(poco(text="독서 탐험"), "독서 탐험 진입")
        time.sleep(2.0)
        # 독서 탐험
        if poco("com.kyowon.literacy:id/txt_timer").exists():
            step("이미 독서 중인 상태, 재시작 진행")
            must_click(poco("com.kyowon.literacy:id/btnRetry"), "독서 재시작 클릭")
        if try_check(poco(text="독서 시작"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 독서 탐험"):
            # ----- step_block: 독서 탐험 기능
            def leading_adv_func():
                must_click(poco(text="독서 시작"), "독서 시작 클릭")
                must_click(poco(text="독서 끝"), "독서 끝 클릭") 
                must_check(poco("com.kyowon.literacy:id/txt_timer"), "독서 시간 확인")
            step_block(leading_adv_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 독서 탐험")
            
        # 독서 탐험 > e-Book 뷰어
        if try_check(poco("com.kyowon.literacy:id/btn_ebook"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 독서 탐험 > e-Book 뷰어"):
            if EBOOK_ENABLED:
                must_click(poco("com.kyowon.literacy:id/btn_ebook"), "뷰어 클릭")
                step_block(ebook_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 독서 탐험 > e-Book 뷰어")
    
    # 〰️ 술술 읽기 훈련 1
    def flow_first_training_1():
        training_menu_open()
        must_click(poco(text="술술 읽기 훈련1"), "술술 읽기 훈련1 진입")
        time.sleep(2.0)
        if try_check(poco(text="오늘의 읽기 훈련"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ①"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ①")
        elif try_check(poco("com.kyowon.literacy:id/txt_direct"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ①"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ②")
    
    # 〰️ 술술 읽기 훈련 2
    def flow_first_training_2():
        training_menu_open()
        must_click(poco(text="술술 읽기 훈련2"), "술술 읽기 훈련2 진입")
        time.sleep(2.0)
        if try_check(poco(text="오늘의 읽기 훈련"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ②"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ②")
        elif try_check(poco("com.kyowon.literacy:id/txt_direct"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ②"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ②")

    # 〰️ 술술 읽기 훈련 3
    def flow_first_training_3():
        training_menu_open()
        must_click(poco(text="술술 읽기 훈련3"), "술술 읽기 훈련3 진입")
        time.sleep(2.0)
        if try_check(poco(text="오늘의 읽기 훈련"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ③"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ③")
        elif try_check(poco("com.kyowon.literacy:id/txt_direct"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 술술 읽기 훈련 ③"):
            step_block(first_training_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 술술 읽기 훈련 ③")

    # 〰️ 독서 활동
    def flow_first_reading_act():
        training_menu_open()
        must_click(poco(text="독서 활동"), "독서 활동 진입")
        time.sleep(2.0)
        try_check(poco("com.kyowon.literacy:id/progressBarLayout"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 독서활동")
        step_block(reading_act_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 독서활동")

    # 〰️ 어휘 탐험
    def flow_first_voca_adv():
        training_menu_open()
        must_click(poco(text="어휘 탐험"), "어휘 탐험 진입")
        time.sleep(2.0)
        step_block(voca_adv_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 어휘 탐험")

    # 〰️ 어휘 놀이
    def flow_first_voca_play():
        training_menu_open()
        must_click(poco(text="어휘 놀이"), "어휘 놀이 진입")
        time.sleep(2.0)
        if poco("com.kyowon.literacy:id/btn_alert_positive").exists():
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "알림 닫기")
            time.sleep(5.0)
        try_check(poco("com.kyowon.literacy:id/vocaplay_progress_bar"), "📋 [Basic Test / 노출] 술술 읽기 훈련 > 어휘 놀이")
        step_block(voca_play_func, "📋 [Basic Test / 기능] 술술 읽기 훈련 > 어휘 놀이")

    # ========== 술술 읽기 훈련 서브 플로우 실행 ==========
    run_subflows(
        (flow_main_first_entry, "술술 읽기 훈련 진입"),
        (flow_first_leading_adv, "독서 탐험"),
        (flow_first_training_1,    "술술 읽기 훈련1"),
        (flow_first_training_2,    "술술 읽기 훈련2"),
        (flow_first_training_3,    "술술 읽기 훈련3"),
        (flow_first_reading_act,   "독서 활동"),
        (flow_first_voca_adv,    "어휘 탐험"),
        (flow_first_voca_play,     "어휘 놀이"),
        restart_sub=restart_first_training,
        group_desc="술술 읽기 훈련",
    )
    
    # 메인 복귀
    back_main()


# 📘 2일차 탄탄 독해 훈련
def flow_main_second():
    # ========== 탄탄 독해 훈련 진입 플로우 ==========
    def flow_main_second_entry():
        find_target_week()
        must_check(poco("com.kyowon.literacy:id/btn_main_second"), "📋 [Basic Test / 노출] 탄탄 독해 훈련")
        must_click(poco("com.kyowon.literacy:id/btn_main_second"), "📋 [Basic Test / 기능] 탄탄 독해 훈련")
    
    # ========== 탄탄 독해 훈련 서브 플로우 ==========
    # 〰️ 탄탄 독해 훈련 1
    def flow_second_training_1():
        training_menu_open()
        must_click(poco(text="탄탄 독해 훈련1"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 탄탄 독해 훈련 ①")
        time.sleep(0.5)
        step_block(second_training_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 탄탄 독해 훈련 ①")

    # 〰️ 독해 활동 1
    def flow_second_reading_act_1():
        training_menu_open()
        must_click(poco(text="독해 활동1"), "독해 활동1 진입")
        time.sleep(2.0)
        try_check(poco("com.kyowon.literacy:id/progressBarLayout"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 독해 활동 ①")
        step_block(reading_act_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 독해 활동 ①")

    # 〰️ 탄탄 독해 훈련 2
    def flow_second_training_2():
        training_menu_open()
        must_click(poco(text="탄탄 독해 훈련2"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 탄탄 독해 훈련 ②")
        time.sleep(2.0)
        step_block(second_training_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 탄탄 독해 훈련 ②")

    # 〰️ 독해 활동 2
    def flow_second_reading_act_2():
        training_menu_open()
        must_click(poco(text="독해 활동2"), "독해 활동2 진입")
        time.sleep(2.0)
        try_check(poco("com.kyowon.literacy:id/progressBarLayout"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 독해 활동 ②")
        step_block(reading_act_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 독해 활동 ②")

    # 〰️ 탄탄 독해 훈련 3
    def flow_second_training_3():
        training_menu_open()
        must_click(poco(text="탄탄 독해 훈련3"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 탄탄 독해 훈련 ③")
        time.sleep(2.0)
        step_block(second_training_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 탄탄 독해 훈련 ③")

    # 〰️ 독해 활동 3
    def flow_second_reading_act_3():
        training_menu_open()
        must_click(poco(text="독해 활동3"), "독해 활동3 진입")
        time.sleep(2.0)
        try_check(poco("com.kyowon.literacy:id/progressBarLayout"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 독해 활동 ③")
        step_block(reading_act_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 독해 활동 ③")

    # 〰️ 어휘 탐험
    def flow_second_voca_adv():
        training_menu_open()
        must_click(poco(text="어휘 탐험"), "어휘 탐험 진입")
        time.sleep(2.0)
        step_block(voca_adv_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 어휘 탐험")

    # 〰️ 어휘 놀이
    def flow_second_voca_play():
        training_menu_open()
        must_click(poco(text="어휘 놀이"), "어휘 놀이 진입")
        time.sleep(2.0)
        if poco("com.kyowon.literacy:id/btn_alert_positive").exists():
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "알림 닫기")
            time.sleep(5.0)
        if must_check(poco("com.kyowon.literacy:id/vocaplay_progress_bar"), "📋 [Basic Test / 노출] 탄탄 독해 훈련 > 어휘 놀이"):
            step_block(voca_play_func, "📋 [Basic Test / 기능] 탄탄 독해 훈련 > 어휘 놀이")

    # ========== 탄탄 독해 훈련 서브 플로우 실행 ==========
    run_subflows(
        (flow_main_second_entry, "탄탄 독해 훈련 진입"),
        (flow_second_training_1,    "탄탄 독해 훈련1"),
        (flow_second_reading_act_1,   "독해 활동1"),
        (flow_second_training_2,    "탄탄 독해 훈련2"),
        (flow_second_reading_act_2,   "독해 활동2"),
        (flow_second_training_3,    "탄탄 독해 훈련3"),
        (flow_second_reading_act_3,   "독해 활동3"),
        (flow_second_voca_adv,    "어휘 탐험"),
        (flow_second_voca_play,     "어휘 놀이"),
        restart_sub=restart_second_training,
        group_desc="탄탄 독해 훈련",
    )
    
    # 메인 복귀
    back_main()


# 📘 오늘의 책
def flow_today_book():
    must_check(poco("com.kyowon.literacy:id/txt_today_book_name"), "📋 [Basic Test / 노출] 오늘의 책")
    if EBOOK_ENABLED:
        must_click(poco("com.kyowon.literacy:id/img_today_book"), "📋 [Basic Test / 기능] 오늘의 책")
        step_block(ebook_func, "📋 [Basic Test / 노출] 오늘의 책 > E-book 뷰어")


# 📘 문해 탐험 도서관
def flow_literacy_library():
    must_check(poco("com.kyowon.literacy:id/right_center_layout").child("android.widget.Button"), "📋 [Basic Test / 노출] 문해 탐험 도서관")
    must_click(poco("com.kyowon.literacy:id/right_center_layout").child("android.widget.Button"), "📋 [Basic Test / 기능] 문해 탐험 도서관")

    # ----- def: 문해 탐험 도서관 재진입
    def restart_literacy_library():
        restart_app()
        app_ready()
        must_click(poco("com.kyowon.literacy:id/right_center_layout").child("android.widget.Button"), "문해 탐험 도서관 재진입")

    # 〰️ 문학
    def flow_library_subject_1():
        must_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_1"), "문학 진입")
        if try_check(poco(text="동아시아 신화 이야기"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 문학"):

            if EBOOK_ENABLED:
                open_target_ebook("지혜를 얻은 오딘", poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 도서관 > 문학")
            if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
                must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
                time.sleep(1.0)

    # 〰️ 사회
    def flow_library_subject_2():
        must_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_2"), "사회 진입")
        if try_check(poco(text="신하로 보는 역사 이야기"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 사회"):
            if EBOOK_ENABLED:
                open_target_ebook("섬세한 나라 백제", poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 도서관 > 사회")
            if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
                must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
                time.sleep(1.0)

    # 〰️ 수과학
    def flow_library_subject_3():
        must_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_3"), "수과학 진입")
        if try_check(poco(text="동화로 읽는 스토리텔링 수학 1"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 수과학"):
            if EBOOK_ENABLED:
                open_target_ebook("도와줘요! 배트보이", poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 도서관 > 수과학")
            if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
                must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
                time.sleep(1.0)

    # 〰️ 통합
    def flow_library_subject_4():
        must_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_4"), "통합 진입")
        if try_check(poco(text="상상토이 1"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 통합"):
            if EBOOK_ENABLED:
                open_target_ebook("또또 랜드로 놀러 오세요", poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 도서관 > 통합")
            if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
                must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
                time.sleep(1.0)

    # 〰️ 검색
    def flow_library_search():
        target_text = "물웅덩이에 빠진 장화"
        must_click(poco("com.kyowon.literacy:id/btn_book_search"), "검색 진입")
        if try_check(poco("com.kyowon.literacy:id/et_ebook_search"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 검색"):
            try_type(poco("com.kyowon.literacy:id/et_ebook_search"), target_text, "검색어 입력")
            try_click(poco("com.kyowon.literacy:id/btn_search"), "검색 실행")
            if EBOOK_ENABLED:
                open_target_ebook(target_text, poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 도서관 > 검색")
            time.sleep(1.0)
            must_click(poco("com.kyowon.literacy:id/btn_book_list_back"), "도서관 메인 복귀")

    # 〰️ 나의 도서
    def flow_library_favorite():
        if try_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_1"), "문학 진입"):
            must_click(poco("com.kyowon.literacy:id/item_book_view_1").offspring("com.kyowon.literacy:id/imb_book_like"), "좋아하는 책 추가")
        if try_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_2"), "사회 진입"):
            must_click(poco("com.kyowon.literacy:id/item_book_view_2").offspring("com.kyowon.literacy:id/imb_book_like"), "좋아하는 책 추가")
        if try_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_3"), "수과학 진입"):
            must_click(poco("com.kyowon.literacy:id/item_book_view_3").offspring("com.kyowon.literacy:id/imb_book_like"), "좋아하는 책 추가")
        if try_click(poco("com.kyowon.literacy:id/ctv_library_subject_tab_4"), "통합 진입"):
            must_click(poco("com.kyowon.literacy:id/item_book_view_4").offspring("com.kyowon.literacy:id/imb_book_like"), "좋아하는 책 추가")

        must_click(poco("com.kyowon.literacy:id/btn_book_favorite"), "나의 도서 진입")
        try_check(poco("com.kyowon.literacy:id/btn_favorite_book_ilike"), "📋 [Basic Test / 노출] 문해 탐험 도서관 > 나의 도서")
        must_click(poco("com.kyowon.literacy:id/btn_favorite_book_ilike"), "나의 도서 > 내가 좋아하는 책 진입")
        if poco(text="슬이의 옛날 여행").exists():
            if EBOOK_ENABLED:
                open_target_ebook("슬이의 옛날 여행", poco("com.kyowon.literacy:id/recycler_ebook_list"))
                step_block(ebook_func, "ebook 기능 체크 및 닫기")
            must_click(poco(text="슬이의 옛날 여행").parent().child("com.kyowon.literacy:id/imb_book_like"), "즐겨찾기 삭제")
        if poco(text="도깨비를 만난 도담이").exists():
            must_click(poco(text="도깨비를 만난 도담이").parent().child("com.kyowon.literacy:id/imb_book_like"), "즐겨찾기 삭제")
        if poco(text="백제를 지켜 낸 계백").exists():
            must_click(poco(text="백제를 지켜 낸 계백").parent().child("com.kyowon.literacy:id/imb_book_like"), "즐겨찾기 삭제")
        if poco(text="북두칠성이 된 일곱 쌍둥이").exists():
            must_click(poco(text="북두칠성이 된 일곱 쌍둥이").parent().child("com.kyowon.literacy:id/imb_book_like"), "즐겨찾기 삭제")
        must_click(poco("com.kyowon.literacy:id/btn_trash"), "휴지통 클릭")
        must_click(poco("com.kyowon.literacy:id/imv_select_all"), "전체 선택 클릭")
        must_click(poco("com.kyowon.literacy:id/btn_delete_submit"), "선택 도서 삭제 클릭")
        if poco("com.kyowon.literacy:id/btn_alert_positive").exists():
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "알림 닫기")
        must_click(poco("com.kyowon.literacy:id/btn_favorite_book_ilike"), "내가 좋아하는 책 새로고침")
        must_check(poco("com.kyowon.literacy:id/tv_lib_no_result"), "📋 [Basic Test / 기능] 문해 탐험 도서관 > 나의 도서")
        time.sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/btn_book_list_back"), "도서관 메인 복귀")

    # ========== 문해 탐험 도서관 서브 플로우 실행 ==========
    run_subflows(
        (flow_library_subject_1,    "문학"),
        (flow_library_subject_2,    "사회"),
        (flow_library_subject_3,    "수과학"),
        (flow_library_subject_4,    "통합"),
        (flow_library_search,       "검색"),
        (flow_library_favorite,    "나의 도서"),
        restart_sub=restart_literacy_library,
        group_desc="문해 탐험 도서관",
    )

    # 메인 복귀
    back_main()


# 📘 문해 탐험 모아보기
def flow_all_contents():
    must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[1], "문해 탐험 모아보기 진입")
    must_check(poco("com.kyowon.literacy:id/titleText", text="문해 탐험 모아 보기"), "📋 [Basic Test / 노출] 문해 탐험 모아보기")
    time.sleep(3.0)
    
    # ----- def: 문해 탐험 모아보기 재진입
    def restart_all_contents():
        restart_app()
        app_ready()
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[1], "문해 탐험 모아보기 재진입")
        time.sleep(3.0)

    # ----- step_block: 문해 탐험 모아보기 공통 기능
    def flow_all_contents_func():
        select_level_week("2단계")
        select_level_week("1단계")
    step_block(flow_all_contents_func, "📋 [Basic Test / 기능] 문해 탐험 모아보기")

    # 〰️ 문해 탐험 모아보기 > 독서 탐험
    def flow_all_cont_reading_adv():
        must_click(poco("com.kyowon.literacy:id/btnReadingAdventure"), "문해 탐험 모아보기 > 독서 탐험 진입")
        time.sleep(1.0)
        if try_check(poco("com.kyowon.literacy:id/item_book_titile", text="게와 원숭이의 떡 다툼"), "📋 [Basic Test / 노출] 문해 탐험 모아보기 > 독서 탐험"):
            if EBOOK_ENABLED:
                open_target_ebook("룸펠슈틸츠헨", poco("com.kyowon.literacy:id/recyclerAllContentsList"))
                step_block(ebook_func, "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 독서 탐험")

    # 〰️ 문해 탐험 모아보기 > 술술 읽기 훈련
    def flow_all_cont_reading_pract():
        must_click(poco("com.kyowon.literacy:id/btnReadingPractice"), "문해 탐험 모아보기 > 술술 읽기 훈련 진입")
        time.sleep(1.0)
        select_level_week("1단계", "1~4주차")
        if try_check(poco("com.kyowon.literacy:id/item_book_titile", text="소리 내어 읽기_색깔 읽기"), "📋 [Basic Test / 노출] 문해 탐험 모아보기 > 독서 탐험"):
            open_target_ebook("속으로 읽기_짚으며 읽기", poco("com.kyowon.literacy:id/recyclerAllContentsList"))
            step_block(first_training_func, "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 술술 읽기 훈련")
            if must_click(poco("com.kyowon.literacy:id/btn_close"), "훈련 닫기"):
                must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "닫기 확인")

    # 〰️ 문해 탐험 모아보기 > 독서 활동
    def flow_all_cont_reading_act():
        must_click(poco("com.kyowon.literacy:id/btnReadingActivity"), "문해 탐험 모아보기 > 독서 활동 진입")
        select_level_week("1단계")
        must_check(poco("com.kyowon.literacy:id/allContentsReadingActivityTitle", text="게와 원숭이의 떡 다툼"),
                   "📋 [Basic Test / 노출] 문해 탐험 모아보기 > 독서 활동")
        time.sleep(1.0)
        target_name="가족이 생긴 검붕어"
        for attempt in range(1, MAX_COUNT + 1):
            step(f"타겟 도서({target_name}) 찾기를 시작합니다... {attempt}회")
            ok = try_find_click(
                target_element=poco("com.kyowon.literacy:id/allContentsReadingActivityTitle", text=target_name)
                                .parent().offspring("com.kyowon.literacy:id/allContentsReadingActivityStart"),
                direction="down", step_ratio=0.5, duration=0.5,                 # 필수 요소: 스크롤 방향/단계/시간
                scroll_view=poco("com.kyowon.literacy:id/recyclerAllContentsList"),
                debug=False
            )
            if ok:
                break  # 성공 → 루프 탈출
            if poco("com.kyowon.literacy:id/btnScrollToTop").exists():
                must_click(poco("com.kyowon.literacy:id/btnScrollToTop"), "맨 위로 이동 클릭")
            time.sleep(0.5)
        else:
            # for 루프가 break 없이 끝났으면 실패가 연속된 것
            soft_fail(f"{target_name} 탐색: FAIL ❌ - {MAX_COUNT}회 탐색 실패")
            raise RuntimeError(
                f"[ERR] {target_name} 탐색 실패 - {MAX_COUNT}회 탐색 실패"
            )
        if try_check(poco("com.kyowon.literacy:id/progressBarLayout"), "문해 탐험 모아보기 > 독서 활동 - 세부 학습 진입"):
            if poco("com.kyowon.literacy:id/particleLottie").exists():
                must_click(poco("com.kyowon.literacy:id/particleLottie"), "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 독서 활동")
            elif poco("com.kyowon.literacy:id/oParticle").exists():
                must_click(poco("com.kyowon.literacy:id/oParticle"), "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 독서 활동")

            must_click(poco("com.kyowon.literacy:id/btn_close"), "닫기 버튼 클릭")
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "닫기 확인")
            time.sleep(1.0)

    # 〰️ 문해 탐험 모아보기 > 탄탄 독해 훈련+
    def flow_all_cont_comprehension_training():
        must_click(poco("com.kyowon.literacy:id/btnComprehensionTraining"), "문해 탐험 모아보기 > 탄탄 독해 훈련+ 진입")
        time.sleep(1.0)
        select_level_week("1단계", "1~4주차")
        if try_check(poco("com.kyowon.literacy:id/item_book_titile", text="글의 소재 찾아보기"), "📋 [Basic Test / 노출] 문해 탐험 모아보기 > 탄탄 독해 훈련+"):
            must_click(poco(text="전략순"), "정렬순 변경 클릭")
            time.sleep(1.0)
            open_target_ebook("글의 소재 찾아보기", poco("com.kyowon.literacy:id/recyclerAllContentsList"))
            step_block(second_training_func, "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 탄탄 독해 훈련+")
            if must_click(poco("com.kyowon.literacy:id/btn_close"), "훈련 닫기"):
                must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "닫기 확인")

    # 〰️ 문해 탐험 모아보기 > 어휘 탐험+
    def flow_all_cont_voca_adv():
        must_click(poco("com.kyowon.literacy:id/btnVocabularyAdventure"), "문해 탐험 모아보기 > 어휘 탐험+ 진입")
        time.sleep(1.0)
        select_level_week("1단계", "1~4주차")
        if try_check(poco("com.kyowon.literacy:id/item_book_titile", text="차곡차곡 어휘 착착(한참, 요란하다 외)"), 
                     "📋 [Basic Test / 노출] 문해 탐험 모아보기 > 어휘 탐험+"):
            open_target_ebook("말랑 톡톡 그림일기(이별하다 외)", poco("com.kyowon.literacy:id/recyclerAllContentsList"))
            if poco("com.kyowon.literacy:id/view_pager").exists():
                must_click(poco("com.kyowon.literacy:id/btn_next"), "📋 [Basic Test / 기능] 문해 탐험 모아보기 > 어휘 탐험+")
                if must_click(poco("com.kyowon.literacy:id/btn_close"), "훈련 닫기"):
                    must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "닫기 확인")

    # ========== 문해 탐험 모아보기 서브 플로우 실행 ==========
    run_subflows(
        (flow_all_cont_reading_adv, "독서 탐험"),
        (flow_all_cont_reading_pract, "술술 읽기 훈련"),
        (flow_all_cont_reading_act, "독서 활동"),
        (flow_all_cont_comprehension_training, "탄탄 독해 훈련+"),
        (flow_all_cont_voca_adv, "어휘 탐험+"),
        restart_sub=restart_all_contents,
        group_desc="문해 탐험 모아보기",
    )
    # 메인 복귀
    back_main()


# 📘 차곡차곡 어휘 상자
def flow_voca_box():
    must_click(poco("com.kyowon.literacy:id/vocabulary_box"), "차곡차곡 어휘 상자 진입")
    must_check(poco("com.kyowon.literacy:id/titleText", text="차곡차곡 어휘 상자"), "📋 [Basic Test / 노출] 차곡차곡 어휘 상자")
    time.sleep(2.0)

    # ----- def: 어휘 상자 재진입
    def restart_voca_box():
        restart_app()
        app_ready()
        must_click(poco("com.kyowon.literacy:id/vocabulary_box"), "차곡차곡 어휘 상자 재진입")

    # ----- def: 어휘 상자 카테고리 선택
    def select_voca_category(category_name):
        scroll_view = poco("com.kyowon.literacy:id/jaumScroll")
        for attempt in range(1, MAX_COUNT + 1):
            step(f"타겟 카테고리({category_name}) 찾기를 시작합니다... {attempt}회")
            ok = try_find_click(target_element=poco("com.kyowon.literacy:id/btnJaum", text=category_name),
                    direction="right", scroll_view=scroll_view)
            if not poco("com.kyowon.literacy:id/headerText", text=category_name).exists():
                must_click(poco("com.kyowon.literacy:id/btnJaum", text=category_name), f"어휘 상자 카테고리 선택 재시도: {category_name}")
            
            if ok and poco("com.kyowon.literacy:id/headerText", text=category_name).exists():
                break  # 성공 → 루프 탈출
            must_find_click(target_element=poco("com.kyowon.literacy:id/btnJaum", text="ㄱ, ㄲ"),
                    direction="left", scroll_view=scroll_view)
        else:
            soft_fail(f"{category_name} 카테고리 선택: FAIL ❌ - {MAX_COUNT}회 탐색 실패")
            raise

    # ----- def: 어휘 상자 찾기 및 선택
    def select_voca_box(target_el):
        label = get_label(target_el)
        for attempt in range(1, MAX_COUNT + 1):
            step(f"타겟({label}) 찾기를 시작합니다... {attempt}회")
            ok = try_find_click(
                target_element=target_el,
                direction="down", step_ratio=0.5, duration=0.4,
                scroll_view=poco("com.kyowon.literacy:id/recycler_vocabulary_list"),
                debug=False
            )
            if ok:
                break  # 성공 → 루프 탈출

            if poco("com.kyowon.literacy:id/btn_scroll_to_top").exists():
                must_click(poco("com.kyowon.literacy:id/btn_scroll_to_top"), "맨 위로 이동 클릭")
            elif poco("com.kyowon.literacy:id/btnScrollToTop").exists():
                must_click(poco("com.kyowon.literacy:id/btnScrollToTop"), "맨 위로 이동 클릭")
            time.sleep(0.5)
        else:
            soft_fail(f"{label} 탐색: FAIL ❌ - {MAX_COUNT}회 탐색 실패")
            # for 루프가 break 없이 끝났으면 실패가 연속된 것
            raise RuntimeError(
                f"[ERR] {label} 탐색 실패 - {MAX_COUNT}회 탐색 실패"
            )

    # 〰️ 메인
    def flow_voca_box_basic_test():
        select_level_week("1단계")
        select_voca_category("ㅎ")
        time.sleep(0.5)
        select_voca_box(poco("com.kyowon.literacy:id/textFrontWord", text="훈련"))
        try_check(poco("com.kyowon.literacy:id/textMeaning"), "📋 [Basic Test / 기능] 차곡차곡 어휘 상자")

    # 〰️ 검색
    def flow_voca_box_search():
        target_text = "단어"
        must_click(poco("com.kyowon.literacy:id/btnSearch"), "어휘 상자 검색 진입")
        if try_check(poco("com.kyowon.literacy:id/et_ebook_search"), "📋 [Basic Test / 노출] 차곡차곡 어휘 상자 > 검색"):
            try_type(poco("com.kyowon.literacy:id/et_ebook_search"), target_text, "검색어 입력")
            try_click(poco("com.kyowon.literacy:id/btn_search"), "검색 실행")
            try_click(poco("com.kyowon.literacy:id/textFrontWord", text=target_text), "검색 결과 어휘 선택")
            try_check(poco("com.kyowon.literacy:id/textMeaning"), "📋 [Basic Test / 기능] 차곡차곡 어휘 상자 > 검색")
            time.sleep(1.0)
            must_click(poco("com.kyowon.literacy:id/btnBack"), "어휘 상자 메인 복귀")

    # 〰️ 저장한 단어
    def flow_voca_box_favorite():
        select_level_week("1단계")
        select_voca_category("ㄱ, ㄲ")
        select_voca_box(poco("com.kyowon.literacy:id/textFrontWord", text="가족회의")
                        .parent().child("com.kyowon.literacy:id/btnStarEmpty"))
        select_voca_category("ㅁ")
        select_voca_box(poco("com.kyowon.literacy:id/textFrontWord", text="매력")
                        .parent().child("com.kyowon.literacy:id/btnStarEmpty"))
        must_click(poco("com.kyowon.literacy:id/btnFavorite"), "저장한 단어 진입")
        must_check(poco("com.kyowon.literacy:id/titleText", text="내가 저장한 어휘"), "📋 [Basic Test / 노출] 차곡차곡 어휘 상자 > 저장한 단어")
        select_voca_box(poco("com.kyowon.literacy:id/textFrontWord", text="가족회의")
                        .parent().child("com.kyowon.literacy:id/btnStarEmpty"))
        select_voca_box(poco("com.kyowon.literacy:id/textFrontWord", text="매력")
                        .parent().child("com.kyowon.literacy:id/btnStarEmpty"))
        must_click(poco("com.kyowon.literacy:id/btnBack"), "어휘 상자 메인 복귀")
        must_click(poco("com.kyowon.literacy:id/btnFavorite"), "저장한 단어 재진입")
        must_check(poco("com.kyowon.literacy:id/noResultVocabularyFavoriteText"), "📋 [Basic Test / 기능] 차곡차곡 어휘 상자 > 저장한 단어")
        time.sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/btnBack"), "어휘 상자 메인 복귀")

    # ========== 어휘 상자 서브 플로우 실행 ==========
    run_subflows(
        (flow_voca_box_basic_test, "메인"),
        (flow_voca_box_search, "검색"),
        (flow_voca_box_favorite, "저장한 단어"),
        restart_sub=restart_voca_box,
        group_desc="차곡차곡 어휘 상자",
    )
    # 메인 복귀
    back_main()


# 📘 한 눈에 보는 문해 탐험 코스
def flow_literacy_course():
    # ----- def: 어휘 상자 재진입
    def restart_literacy_course():
        restart_app()
        app_ready()
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[0], "한 눈에 보는 문해 탐험 재진입")
        step(f"진행할 레벨을 선택합니다. {lt.TARGET_LEVEL}")
        time.sleep(1.0)
        select_level_week(lt.TARGET_LEVEL)
        time.sleep(1.0)

    must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[0], "한 눈에 보는 문해 탐험 진입")
    must_check(poco("com.kyowon.literacy:id/txt_title", text="한눈에 보는 문해 탐험 코스"), "📋 [Basic Test / 노출] 한 눈에 보는 문해 탐험 코스")
    step(f"진행할 레벨을 선택합니다. {lt.TARGET_LEVEL}")
    time.sleep(1.0)
    select_level_week(lt.TARGET_LEVEL)
    time.sleep(1.0)

    # 〰️ 술술 읽기 훈련 기능 확인
    def flow_literacy_course_first_training():
        if try_click(poco("com.kyowon.literacy:id/item_week1_01"), "첫 주차 1일차 진입"):
            training_menu_open()
            must_click(poco(text="술술 읽기 훈련1"), "술술 읽기 훈련1 진입")
            time.sleep(1.0)
            if try_check(poco(text="오늘의 읽기 훈련")):
                step_block(first_training_func, "술술 읽기 훈련 기능 확인")
            elif try_check(poco("com.kyowon.literacy:id/txt_direct")):
                step_block(first_training_func, "술술 읽기 훈련 기능 확인")
            if poco("com.kyowon.literacy:id/btnOpen").exists():
                must_click(poco("com.kyowon.literacy:id/btnOpen"), "메뉴 오픈")
                must_click(poco("com.kyowon.literacy:id/btn_exit"), "나가기")
                must_click(poco("com.kyowon.literacy:id/btn_alert_positive"))
            else:
                back_main()

    # 〰️ 탄탄 독해 훈련 기능 확인
    def flow_literacy_course_second_training():
        if try_click(poco("com.kyowon.literacy:id/item_week2_02"), "둘째 주차 2일차 진입"):
            time.sleep(0.5)
            handle_exceptions()
            training_menu_open()
            must_click(poco(text="탄탄 독해 훈련1"), "탄탄 독해 훈련1 진입")
        time.sleep(0.5)
        step_block(second_training_func, "탄탄 독해 훈련 기능 확인")
        if poco("com.kyowon.literacy:id/btnOpen").exists():
            must_click(poco("com.kyowon.literacy:id/btnOpen"), "메뉴 오픈")
            must_click(poco("com.kyowon.literacy:id/btn_exit"), "나가기")
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"))
        else:
            back_main()

    # 〰️ 커리큘럼 체크
    def flow_literacy_course_curriculum_check():
        must_click(poco("com.kyowon.literacy:id/btn_curriculum"), "커리큘럼 진입")
        must_check(poco("com.kyowon.literacy:id/img_content"), "📋 [Basic Test / 기능] 한 눈에 보는 문해 탐험 코스")
        time.sleep(1.0)
        must_click(poco("com.kyowon.literacy:id/btn_close"), "메뉴 닫기")

    # ========== 한 눈에 보는 문해 탐험 코스 서브 플로우 실행 ==========
    run_subflows(
        (flow_literacy_course_first_training, "첫 주차 술술 읽기 훈련"),
        (flow_literacy_course_second_training, "둘째 주차 탄탄 독해 훈련"),
        (flow_literacy_course_curriculum_check, "커리큘럼 체크"),
        restart_sub=restart_literacy_course,
        group_desc="한 눈에 보는 문해 탐험 코스",
    )

    # 메인 복귀
    back_main()


# 📘 메뉴
def flow_main_menu():
    # 〰️ 메뉴 기본 체크
    def flow_menu_check():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_check(poco("com.kyowon.literacy:id/top_right_sub_menu"), "📋 [Basic Test / 노출] 메뉴")
        must_click(poco("com.kyowon.literacy:id/btn_submenu_close"), "📋 [Basic Test / 기능] 메뉴")
    # 〰️ 메뉴 > 튜토리얼
    def flow_menu_tutorial():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="튜토리얼"), "메뉴 > 튜토리얼 진입")
        must_check(poco("com.kyowon.literacy:id/img_tuto"), "📋 [Basic Test / 노출] 메뉴 > 튜토리얼")
        must_click(poco("com.kyowon.literacy:id/btn_next"), "📋 [Basic Test / 기능] 메뉴 > 튜토리얼")
        must_click(poco("com.kyowon.literacy:id/btn_close"), "튜토리얼 닫기")
        time.sleep(1.0)
    # 〰️ 메뉴 > 나의 보상
    def flow_menu_my_reward():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="나의 보상"), "메뉴 > 나의 보상 진입")
        must_check(poco("com.kyowon.literacy:id/btn_reward_management"), "📋 [Basic Test / 노출] 메뉴 > 나의 보상")
        must_click(poco("com.kyowon.literacy:id/btn_date_picker"), "포인트 이력 열기")
        must_check(poco("android.widget.TextView", text="포인트 이력"), "📋 [Basic Test / 기능] 메뉴 > 나의 보상")
        must_click(poco("android.widget.TextView", text="포인트 이력")
                   .parent().child("android.widget.ImageButton"), "포인트 이력 닫기")
        back_main()
        time.sleep(1.0)
    # 〰️ 메뉴 > 학습 리포트
    def flow_menu_study_report():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="학습 리포트"), "메뉴 > 학습 리포트 진입")
        must_check(poco("android.widget.TextView", text="학습 리포트"), "📋 [Basic Test / 노출] 메뉴 > 학습 리포트")
        must_click(poco("com.kyowon.literacy:id/ctv_cumulative"), "📋 [Basic Test / 기능] 메뉴 > 학습 리포트")
        back_main()
        time.sleep(1.0)
    # 〰️ 메뉴 > 캐릭터 소개
    def flow_menu_character_intro():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="캐릭터 소개"), "메뉴 > 캐릭터 소개 진입")
        must_check(poco("com.kyowon.literacy:id/img_character"), "📋 [Basic Test / 노출] 메뉴 > 캐릭터 소개")
        must_click(poco("com.kyowon.literacy:id/btn_character1"), "📋 [Basic Test / 기능] 메뉴 > 캐릭터 소개")
        must_click(poco("android.widget.Button"), "캐릭터 소개 닫기")
        time.sleep(1.0)
    # 〰️ 메뉴 > 설정
    def flow_menu_settings():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="설정"), "메뉴 > 설정 진입")
        must_check(poco("com.kyowon.literacy:id/title", text="설정"), "📋 [Basic Test / 노출] 메뉴 > 설정")
        def toggle_bgm_setting():
            if is_bgm_playing():
                must_check(poco("com.kyowon.literacy:id/switch_bgm", checked=True), "배경음 설정 ON 확인")
                must_click(poco("com.kyowon.literacy:id/switch_bgm"), "배경음악 끄기")
                must_click(poco("com.kyowon.literacy:id/title", text="설정").parent().child("android.widget.Button"), "설정 닫기")
                time.sleep(1.0)
                if not is_bgm_playing():
                    step("배경음 OFF 확인 완료")
                else:
                    raise RuntimeError("[ERR] 배경음 설정 OFF 실패: 배경음악이 계속 재생되고 있습니다.")
            else:
                must_check(poco("com.kyowon.literacy:id/switch_bgm", checked=False), "배경음 설정 OFF 확인")
                must_click(poco("com.kyowon.literacy:id/switch_bgm"), "배경음악 켜기")
                must_click(poco("com.kyowon.literacy:id/title", text="설정").parent().child("android.widget.Button"), "설정 닫기")
                time.sleep(1.0)
                if is_bgm_playing():
                    step("배경음 ON 확인 완료")
                else:
                    raise RuntimeError("[ERR] 배경음 설정 ON 실패: 배경음악이 재생되지 않고 있습니다.")
        step_block(toggle_bgm_setting, "📋 [Basic Test / 기능] 메뉴 > 설정")
        # 이용약관 개인정보 처리방침 추가 고려
        time.sleep(1.0)
    # 〰️ 메뉴 > 앱 종료
    def flow_menu_app_exit():
        must_click(poco("com.kyowon.literacy:id/top_right_menu").child("android.widget.ImageButton")[2], "메뉴 오픈")
        must_click(poco("com.kyowon.literacy:id/top_right_sub_menu").offspring(text="앱 종료"), "메뉴 > 앱 종료 진입")
        if try_check(poco("com.kyowon.literacy:id/text_alert_message", text="초등 읽기 프로젝트 퍼펙트 문해를\n그만할까요?"),
                     "📋 [Basic Test / 노출] 메뉴 > 앱 종료"):
            must_click(poco("com.kyowon.literacy:id/btn_alert_positive"), "📋 [Basic Test / 기능] 메뉴 > 앱 종료")
            time.sleep(1.0)
            app_ready()

    # ========== 메뉴 서브 플로우 실행 ==========
    run_subflows(
        (flow_menu_check,          "메뉴 기본 체크"),
        (flow_menu_tutorial,       "튜토리얼"),
        (flow_menu_my_reward,      "나의 보상"),
        (flow_menu_study_report,   "학습 리포트"),
        (flow_menu_character_intro,"캐릭터 소개"),
        (flow_menu_settings,       "설정"),
        # (flow_menu_app_exit,      "앱 종료"),
        group_desc="메뉴",
    )

# ======== flow 등록 ============
def _build_flows(flows_decl):
    flows = []
    for title, fn_name in flows_decl:
        fn = globals().get(fn_name)
        if not callable(fn):
            raise ValueError(f"Flow function not found/callable: {fn_name}")
        flows.append((title, fn))
    return flows

# ========= 실행 함수 ============
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

