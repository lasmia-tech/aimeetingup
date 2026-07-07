"""음성 파일을 텍스트로 변환하는 STT(Speech-To-Text) 서비스.

OpenAI의 Whisper API를 사용한다. 파이프라인 전체에서 "귀" 역할을 담당하며,
여기서 나온 텍스트가 이후 Claude 요약 단계(services/summarize.py)의 입력이 된다.
"""

from pathlib import Path

from openai import OpenAI


def transcribe_audio(file_path: str | Path, api_key: str, language: str = "ko") -> str:
    """오디오 파일 경로를 받아 전체 스크립트(텍스트)를 반환한다.

    Args:
        file_path: 변환할 음성 파일의 로컬 경로 (mp3/wav/m4a 등).
        api_key: OpenAI API 키.
        language: 발화 언어 힌트 (ISO 639-1 코드). 한국어 회의를 기본값으로 가정해 "ko".
                  올바른 언어를 지정하면 Whisper의 인식 정확도가 올라간다.

    Returns:
        인식된 전체 스크립트 텍스트 한 덩어리(문단 구분 없이 이어진 문자열).
    """
    client = OpenAI(api_key=api_key)

    # Whisper API는 파일을 multipart/form-data로 업로드해야 하므로
    # 바이너리 읽기 모드("rb")로 열어서 그대로 전달한다.
    with open(file_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
        )
    # transcript는 OpenAI SDK가 반환하는 응답 객체이며, .text 속성에
    # 최종 인식된 문자열이 들어있다.
    return transcript.text
