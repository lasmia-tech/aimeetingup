"""Whisper API 업로드 전에 오디오 파일을 크기 제한에 맞게 손질하는 모듈.

OpenAI Whisper API는 요청 하나당 파일 크기를 25MiB(26,214,400 bytes)로
제한한다. 1시간짜리 회의 녹음은 이 한도를 쉽게 넘기 때문에, 넘는 파일은
그대로 올리면 413(Maximum content size limit exceeded) 오류가 난다.

그래서 여기서 두 단계로 처리한다.

1. 재인코딩: 16kHz / 모노 / 32kbps MP3로 변환한다. Whisper는 내부적으로
   어차피 16kHz 모노로 다운샘플링하므로 이 정도로 낮춰도 인식 품질에
   사실상 영향이 없고, 용량은 보통 원본의 1/5~1/10로 줄어든다.
2. 분할: 재인코딩 후에도 한도를 넘는 아주 긴 녹음이면, 청크당 크기가
   한도 아래로 떨어지도록 시간 기준으로 잘라 여러 조각을 만든다.

한도 이내인 파일은 아무것도 하지 않고 원본 경로를 그대로 돌려준다
(불필요한 변환으로 품질을 떨어뜨리지 않기 위함).

ffmpeg 바이너리는 시스템 PATH에 있으면 그것을 쓰고, 없으면 pip 패키지
imageio-ffmpeg가 함께 설치하는 정적 바이너리를 사용한다. 덕분에 사용자가
ffmpeg을 따로 설치하지 않아도 되고, Render 등 배포 환경에서도 requirements.txt
설치만으로 동작한다.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# Whisper API의 공식 업로드 한도(25MiB).
WHISPER_MAX_BYTES = 25 * 1024 * 1024

# 실제 판단에 쓰는 한도. multipart/form-data 오버헤드와 인코더의 비트레이트
# 오차를 감안해 한도보다 조금 낮게 잡는다. (이번 오류도 26,422,634 bytes로
# 한도를 겨우 0.8% 넘겨서 발생했다.)
_SAFE_MAX_BYTES = 24 * 1024 * 1024

# 재인코딩 규격. Whisper가 내부적으로 사용하는 16kHz 모노에 맞춘다.
_TARGET_SAMPLE_RATE = 16000
_TARGET_BITRATE_KBPS = 32
# 32kbps = 4,000 bytes/sec. 여기에 MP3 헤더/태그 오버헤드를 감안해 넉넉히 잡는다.
_BYTES_PER_SECOND = _TARGET_BITRATE_KBPS * 1000 // 8


class AudioPrepError(RuntimeError):
    """오디오 변환/분할에 실패했을 때 발생. 화면에서 사용자용 문구로 보여준다."""


def find_ffmpeg() -> str:
    """사용할 ffmpeg 실행 파일 경로를 찾는다.

    시스템에 설치된 ffmpeg을 우선 사용하고(사용자가 의도적으로 특정 버전을
    깔아둔 경우를 존중), 없으면 imageio-ffmpeg가 내장한 정적 바이너리로
    폴백한다.

    Raises:
        AudioPrepError: 둘 다 없어서 변환을 진행할 수 없을 때.
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise AudioPrepError(
            "25MB가 넘는 음성 파일을 처리하려면 ffmpeg이 필요합니다. "
            "`pip install imageio-ffmpeg`를 실행하거나 시스템에 ffmpeg을 설치해 주세요."
        ) from exc

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run_ffmpeg(args: list[str]) -> None:
    """ffmpeg을 실행하고, 실패하면 stderr 끝부분을 담아 예외를 던진다."""
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # ffmpeg은 로그를 stderr로 흘리는데, 인코딩이 환경마다 달라
        # 깨진 바이트가 섞일 수 있으므로 errors="replace"로 안전하게 디코딩한다.
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        # ffmpeg의 stderr는 매우 길기 때문에 원인이 담긴 마지막 부분만 보여준다.
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise AudioPrepError(f"오디오 변환에 실패했습니다 (ffmpeg 종료 코드 {result.returncode}).\n{tail}")


def prepare_audio_for_whisper(file_path: str | Path) -> tuple[list[Path], Path | None]:
    """Whisper에 올릴 수 있는 크기의 오디오 조각 목록을 만든다.

    Args:
        file_path: 원본 오디오 파일 경로.

    Returns:
        (chunks, workdir) 튜플.
        - chunks: 업로드할 파일 경로 목록. 원본이 한도 이내면 원본 하나만 들어있고,
          그렇지 않으면 시간 순서대로 정렬된 변환/분할 결과가 들어있다.
        - workdir: 변환 결과를 담아둔 임시 디렉터리. 호출자가 전사를 마친 뒤
          삭제해야 한다. 변환이 필요 없었으면 None(지울 것이 없다는 뜻).

    Raises:
        AudioPrepError: ffmpeg을 찾지 못했거나 변환에 실패했을 때.
    """
    source = Path(file_path)
    if source.stat().st_size <= _SAFE_MAX_BYTES:
        # 한도 이내면 원본을 그대로 올린다. 불필요한 재인코딩은 인식 품질만 떨어뜨린다.
        return [source], None

    ffmpeg = find_ffmpeg()
    workdir = Path(tempfile.mkdtemp(prefix="whisper_chunks_"))

    try:
        # 1단계: 16kHz 모노 32kbps MP3로 재인코딩해 용량을 크게 줄인다.
        compressed = workdir / "compressed.mp3"
        _run_ffmpeg(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-y",
                "-i", str(source),
                "-vn",  # mp4/webm처럼 영상 트랙이 섞여 있을 수 있으므로 오디오만 뽑는다.
                "-ac", "1",
                "-ar", str(_TARGET_SAMPLE_RATE),
                "-b:a", f"{_TARGET_BITRATE_KBPS}k",
                str(compressed),
            ]
        )

        if compressed.stat().st_size <= _SAFE_MAX_BYTES:
            # 대부분의 회의 녹음은 이 단계에서 한도 아래로 내려가 분할이 필요 없다.
            return [compressed], workdir

        # 2단계: 재인코딩으로도 부족할 만큼 긴 녹음이면 시간 기준으로 자른다.
        # 청크 하나가 한도 아래가 되도록 초 단위 길이를 계산한다.
        # max(1, ...): 계산 결과가 0이 되면 ffmpeg이 무한히 조각을 만들므로 최소 1초를 보장한다.
        segment_seconds = max(1, _SAFE_MAX_BYTES // _BYTES_PER_SECOND)
        _run_ffmpeg(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-y",
                "-i", str(compressed),
                # 이미 목표 규격으로 인코딩된 상태이므로 재인코딩 없이 복사만 해서 빠르게 자른다.
                "-c", "copy",
                "-f", "segment",
                "-segment_time", str(segment_seconds),
                str(workdir / "chunk_%03d.mp3"),
            ]
        )

        # %03d 패턴 덕분에 파일명 정렬 순서 = 녹음 시간 순서가 보장된다.
        chunks = sorted(workdir.glob("chunk_*.mp3"))
        if not chunks:
            raise AudioPrepError("오디오 분할 결과가 비어 있습니다. 파일이 손상되었을 수 있습니다.")
        return chunks, workdir
    except Exception:
        # 중간에 실패하면 임시 디렉터리를 남기지 않는다(호출자가 정리할 기회가 없으므로).
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def cleanup(workdir: Path | None) -> None:
    """prepare_audio_for_whisper가 만든 임시 디렉터리를 정리한다."""
    if workdir is not None:
        shutil.rmtree(workdir, ignore_errors=True)
