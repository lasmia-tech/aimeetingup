"""음성 파일을 텍스트로 변환하는 STT(Speech-To-Text) 서비스.

OpenAI의 Whisper API를 사용한다. 파이프라인 전체에서 "귀" 역할을 담당하며,
여기서 나온 텍스트가 이후 Claude 요약 단계(services/summarize.py)의 입력이 된다.

Whisper API에는 요청당 25MiB 업로드 제한이 있어서, 긴 회의 녹음은 그대로
올리면 413 오류가 난다. 크기 손질(압축/분할)은 services/audio_prep.py가
담당하고, 이 모듈은 손질된 조각들을 순서대로 전사해 하나로 합친다.
"""

from collections.abc import Callable
from pathlib import Path

from openai import OpenAI

from services.audio_prep import cleanup, prepare_audio_for_whisper


def transcribe_audio(
    file_path: str | Path,
    api_key: str,
    language: str = "ko",
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """오디오 파일 경로를 받아 전체 스크립트(텍스트)를 반환한다.

    Args:
        file_path: 변환할 음성 파일의 로컬 경로 (mp3/wav/m4a 등).
        api_key: OpenAI API 키.
        language: 발화 언어 힌트 (ISO 639-1 코드). 한국어 회의를 기본값으로 가정해 "ko".
                  올바른 언어를 지정하면 Whisper의 인식 정확도가 올라간다.
        progress: 조각 단위 진행 상황을 알려줄 콜백. (현재 조각 번호, 전체 조각 수)로
                  호출된다. 긴 파일은 분할 전사에 수 분이 걸릴 수 있어 화면에
                  진행률을 표시하기 위한 것이며, 없으면 조용히 진행한다.

    Returns:
        인식된 전체 스크립트 텍스트. 파일이 분할된 경우 조각별 결과를 녹음
        시간 순서대로 공백으로 이어 붙인 문자열.
    """
    client = OpenAI(api_key=api_key)

    # 25MiB를 넘는 파일은 여기서 16kHz 모노 MP3로 압축되고, 그래도 크면 분할된다.
    # 한도 이내면 원본 경로 하나만 그대로 돌아온다.
    chunks, workdir = prepare_audio_for_whisper(file_path)

    try:
        texts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            if progress:
                progress(index, len(chunks))
            # Whisper API는 파일을 multipart/form-data로 업로드해야 하므로
            # 바이너리 읽기 모드("rb")로 열어서 그대로 전달한다.
            with open(chunk, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=language,
                )
            # transcript는 OpenAI SDK가 반환하는 응답 객체이며, .text 속성에
            # 최종 인식된 문자열이 들어있다.
            texts.append(transcript.text.strip())

        # 조각 경계에서 문장이 붙어버리지 않도록 공백으로 이어 붙인다.
        return " ".join(t for t in texts if t)
    finally:
        # 성공/실패와 무관하게 압축·분할로 만든 임시 파일을 정리한다.
        cleanup(workdir)
