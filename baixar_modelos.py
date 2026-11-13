"""Baixa (ou confere) os modelos usados na transcrição. Executado pelo install.sh.

Depois de instalado, o transcritor roda sem acesso à rede (HF_HUB_OFFLINE=1, ver config.py).
Este script é a exceção: libera a rede só para baixar o que faltar e carrega cada modelo uma
vez na GPU, do mesmo jeito que a transcrição faz, garantindo que o cache esteja completo.

Uso:  venv/bin/python baixar_modelos.py
"""

from __future__ import annotations

import os

os.environ["HF_HUB_OFFLINE"] = "0"  # antes de importar o config (que só define se estiver vazio)

import gc  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import config  # noqa: E402

log = logging.getLogger("modelos")

URL_TERMOS = "https://huggingface.co/pyannote/speaker-diarization-community-1"


def _liberar_gpu() -> None:
    import torch

    gc.collect()
    torch.cuda.empty_cache()


def main() -> int:
    config.configurar_logs()
    if not config.HF_TOKEN:
        log.error("HF_TOKEN ausente no .env. Crie um token 'Read' em "
                  "https://huggingface.co/settings/tokens e aceite os termos em %s", URL_TERMOS)
        return 1

    import torch

    if not torch.cuda.is_available():
        log.error("CUDA indisponível: verifique o driver da NVIDIA com 'nvidia-smi'")
        return 1

    import whisperx
    from whisperx.diarize import DiarizationPipeline

    etapas = (
        (f"Transcrição: Whisper {config.MODELO}",
         lambda: whisperx.load_model(config.MODELO, config.DEVICE,
                                     compute_type=config.COMPUTE_TYPE, language=config.IDIOMA)),
        (f"Alinhamento de palavras ({config.IDIOMA})",
         lambda: whisperx.load_align_model(language_code=config.IDIOMA, device=config.DEVICE)),
        ("Separação de falantes: pyannote",
         lambda: DiarizationPipeline(token=config.HF_TOKEN, device=config.DEVICE)),
    )
    for nome, carregar in etapas:
        inicio = time.monotonic()
        log.info("%s: baixando/conferindo...", nome)
        try:
            modelo = carregar()
        except Exception as e:  # noqa: BLE001 - mostrar a causa e a dica certa
            log.error("%s: falhou (%s)", nome, e)
            if any(t in str(e).lower() for t in ("gated", "restricted", "authorized", "401", "403")):
                log.error("Aceite os termos do modelo (logado na mesma conta do token): %s", URL_TERMOS)
            return 1
        del modelo
        _liberar_gpu()
        log.info("%s: ok (%.0fs)", nome, time.monotonic() - inicio)

    log.info("Modelos prontos em ~/.cache/huggingface. A transcrição passa a rodar sem rede.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
