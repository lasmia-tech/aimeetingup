"""화면(view) 여러 곳에서 공통으로 쓰는 UI 컴포넌트.

'회의록 생성'과 '요구사항정의서 생성' 화면 모두 "회의 음성 업로드 -> STT ->
Claude 요약" 단계를 똑같이 필요로 한다. session_state.transcript/summary는
앱 전체가 공유하므로, 한 화면에서 변환을 실행하면 다른 화면에서도 그 결과가
바로 이어서 보인다.
"""

from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from services.audio_meta import default_meeting_date
from services.audio_prep import AudioPrepError
from services.stt import transcribe_audio
from services.summarize import SummarizeError, summarize_meeting


def _format_elapsed(seconds: float) -> str:
    """초 단위 실수를 "1시간 3분 7초"처럼 읽기 쉬운 문자열로 바꾼다.

    분/시간 단위는 값이 0일 때 아예 생략해서, 짧은 변환은 "42초"처럼
    간결하게 보이도록 한다.
    """
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    parts.append(f"{secs}초")
    return " ".join(parts)


def _render_timing(slot, timing: dict | None) -> None:
    """실행 버튼 옆 칸에 시작/종료 시각과 총 소요시간을 그린다.

    Args:
        slot: 내용을 갈아끼울 st.empty() 컨테이너. 변환이 진행되는 동안 같은
              자리를 "진행 중" -> "완료" 로 덮어쓰기 위해 사용한다.
        timing: {"start": datetime, "end": datetime | None} 형태. None이면
                아직 한 번도 실행하지 않은 것이므로 아무것도 그리지 않는다.
    """
    if not timing:
        return

    started = timing["start"].strftime("%H:%M:%S")
    finished = timing.get("end")
    if finished is None:
        # 아직 실행 중: 종료 시각과 소요시간은 확정되지 않았다.
        slot.caption(f"시작 {started} · 진행 중...")
        return

    elapsed = _format_elapsed((finished - timing["start"]).total_seconds())
    slot.caption(f"시작 {started} · 종료 {finished.strftime('%H:%M:%S')} · 총 소요 {elapsed}")


def render_transcript_section(settings) -> bool:
    """음성 업로드+변환+요약 실행 버튼과 스크립트 확인/재요약 UI를 그린다.

    호출하는 화면이 미리 session_state.transcript("")/summary({})를
    초기화해뒀다고 가정한다.

    Returns:
        이번 실행(rerun)에서 요약이 새로 갱신됐으면 True, 아니면 False.
        호출하는 화면이 이 값을 보고 "요약이 막 끝났을 때만" 해야 하는 후속
        작업(예: 요구사항 자동 추출)을 트리거할 수 있다.
    """
    summary_updated = False

    st.header("1. 음성 업로드 → 텍스트 변환 + 요약")
    audio_file = st.file_uploader("회의 음성 파일", type=["mp3", "wav", "m4a", "mp4", "webm"])

    # 소요시간은 버튼 클릭으로 인한 rerun 뒤에도 계속 보여야 하므로 session_state에 보관한다.
    if "run_timing" not in st.session_state:
        st.session_state.run_timing = None

    # 버튼과 소요시간 표시를 같은 행에 나란히 놓는다.
    col_run, col_timing = st.columns([1, 3], vertical_alignment="center")
    # 파일이 없으면 버튼 자체를 비활성화해서 오작동을 방지한다.
    run_clicked = col_run.button("텍스트 변환 + 요약 실행", disabled=audio_file is None)
    timing_slot = col_timing.empty()
    # 직전 실행 결과를 먼저 그려둔다(이번에 새로 실행하면 아래에서 덮어쓴다).
    _render_timing(timing_slot, st.session_state.run_timing)

    if run_clicked:
        if not settings.openai_api_key or not settings.anthropic_api_key:
            st.error("OPENAI_API_KEY / ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
        else:
            # OpenAI Whisper API는 파일 "경로"가 아니라 실제 바이트를 필요로 하므로,
            # 업로드된 바이트를 임시 파일로 한 번 디스크에 써서 그 경로를 넘긴다.
            with NamedTemporaryFile(delete=False, suffix=Path(audio_file.name).suffix) as tmp:
                tmp.write(audio_file.getvalue())
                tmp_path = tmp.name

            # 회의일시 기본값 후보: 음성 파일 자체에 녹음일 메타데이터가 있으면 그 값,
            # 없으면 지금(업로드/처리 시각)을 사용한다. Claude가 스크립트 내용에서
            # 날짜를 이미 추출했다면 아래에서 그 값을 더 우선시한다.
            recorded_date = default_meeting_date(tmp_path)

            # 변환+요약 전체 구간의 시작 시각. 실패하더라도 "언제 시작해서 얼마나
            # 걸리다 멈췄는지"를 보여줄 수 있도록 여기서 바로 기록한다.
            st.session_state.run_timing = {"start": datetime.now(), "end": None}
            _render_timing(timing_slot, st.session_state.run_timing)

            def _finish_timing() -> None:
                """종료 시각을 확정하고 버튼 옆 표시를 갱신한다."""
                st.session_state.run_timing["end"] = datetime.now()
                _render_timing(timing_slot, st.session_state.run_timing)

            # 25MB가 넘는 파일은 transcribe_audio 내부에서 자동으로 압축/분할되며,
            # 조각별 전사는 수 분이 걸릴 수 있어 진행 상황을 문구로 갱신해 보여준다.
            status = st.empty()

            def _report_progress(index: int, total: int) -> None:
                if total > 1:
                    status.info(f"음성을 텍스트로 변환하는 중... ({index}/{total} 구간)")

            try:
                with st.spinner("음성을 텍스트로 변환하는 중..."):
                    st.session_state.transcript = transcribe_audio(
                        tmp_path, settings.openai_api_key, progress=_report_progress
                    )
            except AudioPrepError as exc:
                # ffmpeg 부재 등 사용자가 조치할 수 있는 문제이므로 원인을 그대로 안내한다.
                status.empty()
                _finish_timing()
                st.error(str(exc))
                return summary_updated
            except Exception as exc:
                # API 오류(용량 초과, 인증 실패, 네트워크 등)로 화면 전체가
                # 트레이스백으로 덮이지 않도록 여기서 잡아 메시지만 보여준다.
                status.empty()
                _finish_timing()
                st.error(f"음성 변환에 실패했습니다: {exc}")
                return summary_updated
            finally:
                # 업로드 바이트를 담아둔 임시 파일은 전사 성공 여부와 무관하게 지운다.
                Path(tmp_path).unlink(missing_ok=True)

            status.empty()

            try:
                with st.spinner("회의 내용을 요약하는 중..."):
                    st.session_state.summary = summarize_meeting(
                        st.session_state.transcript, settings.anthropic_api_key, settings.anthropic_model
                    )
            except SummarizeError as exc:
                # 크레딧 부족/인증 실패 등 원인과 조치 방법이 이미 담긴 문구다.
                # 요약에 실패해도 STT 결과는 session_state에 남아 있으므로,
                # 사용자는 조치 후 아래 "이 텍스트로 다시 요약"으로 재시도할 수 있다.
                _finish_timing()
                st.error(str(exc))
                return summary_updated
            except Exception as exc:
                # 응답 형식 오류 등 예상치 못한 실패.
                _finish_timing()
                st.error(f"회의 요약에 실패했습니다: {exc}")
                return summary_updated

            # 변환 + 요약이 모두 끝난 시점 = 총 소요시간 확정.
            _finish_timing()

            # Claude가 스크립트에서 명시적 날짜를 찾지 못해 meeting_date가 빈 값일 때만
            # 파일 메타데이터/업로드 시각으로 채운다(내용 기반 값이 있으면 그게 더 정확하므로 유지).
            if not st.session_state.summary.get("meeting_date"):
                st.session_state.summary["meeting_date"] = recorded_date

            st.success("변환 및 요약이 완료되었습니다.")
            summary_updated = True

    # 스크립트 확인/수정 영역은 STT 결과가 없어도(빈 텍스트로) 항상 보여준다.
    with st.expander("전체 스크립트 보기 / 직접 수정", expanded=True):
        # 이 text_area는 읽기 전용이 아니라 편집 가능하며, 반환값을 다시
        # session_state.transcript에 대입해서 사용자의 수정 내용이 즉시 반영되게 한다.
        st.session_state.transcript = st.text_area(
            "스크립트", st.session_state.transcript, height=200, label_visibility="collapsed"
        )
        # 음성을 다시 변환하지 않고, 수정된 텍스트만으로 Claude 요약만 다시 돌리고 싶을 때 사용.
        # 스크립트가 비어 있으면 요약할 대상이 없으므로 버튼을 비활성화한다.
        if st.button("이 텍스트로 다시 요약", disabled=not st.session_state.transcript.strip()):
            if not settings.anthropic_api_key:
                st.error("ANTHROPIC_API_KEY가 .env에 설정되어 있어야 합니다.")
            else:
                # 첫 요약과 동일하게, 실패 시 화면이 트레이스백으로 덮이지 않도록 잡아준다.
                try:
                    with st.spinner("회의 내용을 요약하는 중..."):
                        st.session_state.summary = summarize_meeting(
                            st.session_state.transcript, settings.anthropic_api_key, settings.anthropic_model
                        )
                except SummarizeError as exc:
                    st.error(str(exc))
                    return summary_updated
                except Exception as exc:
                    st.error(f"회의 요약에 실패했습니다: {exc}")
                    return summary_updated

                st.success("수정한 텍스트로 다시 요약했습니다.")
                summary_updated = True

    return summary_updated
