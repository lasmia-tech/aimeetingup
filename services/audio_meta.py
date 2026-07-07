"""회의일시 기본값을 정하기 위해 음성 파일 자체의 메타데이터를 읽는 유틸.

Streamlit의 file_uploader는 브라우저에서 파일의 바이트와 파일명만 서버로
넘기고, OS의 "생성일시" 같은 메타데이터는 넘기지 않는다. 그래서 "파일이
생성된 일시"를 얻으려면 오디오 파일 내부에 녹음 앱 등이 직접 기록해 둔
태그(ID3 TDRC, MP4 ©day, Vorbis DATE 등)를 mutagen으로 읽는 수밖에 없다.
그런 태그가 없는 파일(우리 테스트용 TTS wav 등)도 많으므로, 못 찾으면
"업로드해서 처리한 시각(오늘 날짜)"으로 안전하게 폴백한다.
"""

import re
from datetime import datetime

import mutagen

# ID3(TDRC: "2026-07-02T10:30:00"), MP4(©day: "2026-07-02"),
# EXIF 스타일(2026:07:02 10:30:00) 등 포맷이 태그마다 조금씩 달라서,
# "YYYY-MM-DD" 또는 "YYYY:MM:DD" 패턴만 정규식으로 느슨하게 뽑아낸다.
_DATE_RE = re.compile(r"(\d{4})[:\-](\d{2})[:\-](\d{2})")


def extract_recorded_date(file_path: str) -> str | None:
    """오디오 파일 자체에 기록된 녹음/생성 일자 태그를 읽어본다.

    Args:
        file_path: 로컬에 저장된 오디오 파일 경로.

    Returns:
        "YYYY-MM-DD" 형식 문자열, 태그가 없거나 파싱할 수 없으면 None.
    """
    try:
        # easy=True: 포맷(mp3/mp4/flac/ogg 등)마다 다른 태그 이름을
        # mutagen이 "date", "title" 같은 공통 키로 정규화해서 돌려준다.
        audio = mutagen.File(file_path, easy=True)
    except Exception:
        # 손상된 파일, 지원하지 않는 포맷 등 어떤 이유로든 읽기에 실패하면
        # 그냥 "태그 없음"과 동일하게 취급한다.
        return None
    if not audio or not audio.tags:
        return None

    # 포맷/녹음 앱에 따라 날짜가 담기는 키 이름이 제각각이라 여러 후보를 순서대로 확인한다.
    for key in ("date", "originaldate", "creation_time", "year"):
        values = audio.tags.get(key)
        if not values:
            continue
        # mutagen easy 태그 값은 보통 리스트(예: ["2026-07-02"])로 온다.
        raw = str(values[0] if isinstance(values, list) else values)
        match = _DATE_RE.search(raw)
        if match:
            year, month, day = match.groups()
            return f"{year}-{month}-{day}"
    return None


def default_meeting_date(file_path: str) -> str:
    """회의일시 기본값을 결정한다: 파일 메타데이터의 녹음일 우선, 없으면 오늘 날짜.

    app.py에서 STT 실행 직후 호출되며, Claude 요약 결과에 meeting_date가
    비어있을 때만 이 값으로 채워 넣는다(스크립트 내용에서 명시적으로 날짜가
    언급되어 Claude가 이미 추출한 경우는 그 값을 그대로 우선한다).
    """
    return extract_recorded_date(file_path) or datetime.now().strftime("%Y-%m-%d")
