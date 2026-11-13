"""Transcrição com WhisperX: transcreve, alinha palavras, separa falantes e salva em Brutas.

Cada modelo é carregado, usado e liberado antes do próximo; a memória da GPU é
liberada ao final mesmo se ocorrer erro no meio.

Teste avulso:  venv/bin/python transcricao.py <arquivo de áudio ou vídeo>
"""

from __future__ import annotations

import gc
import logging
import sys
import time
from pathlib import Path

import config

log = logging.getLogger("transcricao")

SAMPLE_RATE = 16_000  # taxa usada por whisperx.load_audio


def _hhmmss(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _liberar_gpu() -> None:
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _vram_mib() -> int:
    import torch

    return round(torch.cuda.memory_allocated() / 2**20) if torch.cuda.is_available() else 0


def formatar(segmentos: list[dict]) -> str:
    """Gera linhas `[00:01:23] Falante 1: texto`.

    Falas seguidas do mesmo falante viram uma linha só (com o horário do início).
    SPEAKER_00, SPEAKER_01... viram Falante 1, 2... na ordem em que aparecem.
    """
    nomes: dict[str, str] = {}
    falas: list[tuple[float, str, list[str]]] = []
    for seg in segmentos:
        texto = (seg.get("text") or "").strip()
        if not texto:
            continue
        rotulo = seg.get("speaker")
        if rotulo is None:
            falante = "Falante ?"
        else:
            falante = nomes.setdefault(rotulo, f"Falante {len(nomes) + 1}")
        if falas and falas[-1][1] == falante:
            falas[-1][2].append(texto)
        else:
            falas.append((seg.get("start", 0.0), falante, [texto]))
    return "".join(f"[{_hhmmss(ini)}] {falante}: {' '.join(textos)}\n" for ini, falante, textos in falas)


def transcrever(arquivo: Path) -> Path:
    """Transcreve `arquivo` e salva `Brutas/<nome>.txt`. Retorna o caminho do .txt."""
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    arquivo = Path(arquivo)
    if not config.HF_TOKEN:
        raise RuntimeError("HF_TOKEN ausente no .env: a diarização precisa dele")
    config.criar_pastas()
    destino = config.BRUTAS / f"{arquivo.stem}.txt"
    inicio = time.monotonic()
    modelo = alinhador = diarizador = None
    log.info("Transcrevendo %s", arquivo.name)
    try:
        # Sempre via whisperx.load_audio (ffmpeg): lê vídeo também e evita a armadilha do av 19.
        audio = whisperx.load_audio(str(arquivo))
        log.info("Áudio carregado: duração %s", _hhmmss(len(audio) / SAMPLE_RATE))

        t = time.monotonic()
        modelo = whisperx.load_model(
            config.MODELO, config.DEVICE, compute_type=config.COMPUTE_TYPE, language=config.IDIOMA
        )
        resultado = modelo.transcribe(audio, batch_size=config.BATCH_SIZE, language=config.IDIOMA)
        modelo = None
        _liberar_gpu()
        log.info("1/3 Transcrição: %d segmentos em %.0fs", len(resultado["segments"]), time.monotonic() - t)

        t = time.monotonic()
        alinhador, metadados = whisperx.load_align_model(language_code=config.IDIOMA, device=config.DEVICE)
        resultado = whisperx.align(
            resultado["segments"], alinhador, metadados, audio, config.DEVICE, return_char_alignments=False
        )
        alinhador = None
        _liberar_gpu()
        log.info("2/3 Alinhamento de palavras em %.0fs", time.monotonic() - t)

        t = time.monotonic()
        diarizador = DiarizationPipeline(token=config.HF_TOKEN, device=config.DEVICE)
        falantes = diarizador(audio)
        resultado = whisperx.assign_word_speakers(falantes, resultado)
        diarizador = None
        _liberar_gpu()
        log.info("3/3 Diarização: %d falante(s) em %.0fs", falantes["speaker"].nunique(), time.monotonic() - t)

        destino.write_text(formatar(resultado["segments"]), encoding="utf-8")
        log.info("Transcrição salva em %s (%.0fs no total)", config.relativo(destino), time.monotonic() - inicio)
        return destino
    finally:
        modelo = alinhador = diarizador = None
        _liberar_gpu()
        log.info("Memória da GPU liberada (alocada agora: %d MiB)", _vram_mib())


if __name__ == "__main__":
    config.configurar_logs()
    if len(sys.argv) != 2:
        sys.exit("Uso: venv/bin/python transcricao.py <arquivo de áudio ou vídeo>")
    entrada = Path(sys.argv[1]).expanduser()
    if not entrada.is_file():
        sys.exit(f"Arquivo não encontrado: {entrada}")
    print(transcrever(entrada))
