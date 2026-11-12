"""Configuração central do transcritor: pastas, modelo, extensões aceitas e logs.

Rodar direto (`venv/bin/python config.py`) cria as pastas, configura os logs e
registra a configuração atual. Pode ser executado quantas vezes quiser.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

PROJETO_DIR = Path(__file__).resolve().parent
load_dotenv(PROJETO_DIR / ".env")

# --- Pastas (PRD, seção 6) ---------------------------------------------------
# TRANSCRICOES_DIR no .env permite trocar a base (ex.: testes numa pasta temporária).
BASE_DIR = Path(os.getenv("TRANSCRICOES_DIR") or "~/Transcricoes").expanduser()
ENTRADA = BASE_DIR / "Entrada"          # arquivos aguardando processamento
BRUTAS = BASE_DIR / "Brutas"            # transcrições brutas
NOTAS = BASE_DIR / "Notas"              # notas finais em Markdown
PROCESSADOS = BASE_DIR / "Processados"  # arquivos originais já tratados
LOGS = BASE_DIR / "logs"                # logs do serviço
PASTAS = (ENTRADA, BRUTAS, NOTAS, PROCESSADOS, LOGS)

# --- WhisperX (PRD, seção 5) -------------------------------------------------
MODELO = "large-v3"
COMPUTE_TYPE = "float16"
IDIOMA = "pt"
DEVICE = "cuda"

# --- Extensões aceitas em Entrada --------------------------------------------
EXTENSOES_AUDIO = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".aac", ".wma"})
EXTENSOES_VIDEO = frozenset({".mp4", ".mkv", ".webm", ".mov", ".avi"})
EXTENSOES_ACEITAS = EXTENSOES_AUDIO | EXTENSOES_VIDEO

# --- Credenciais (somente via .env; nunca escrever valores aqui) -------------
HF_TOKEN = (os.getenv("HF_TOKEN") or "").strip()

# --- Logs --------------------------------------------------------------------
ARQUIVO_LOG = LOGS / "transcritor.log"
FORMATO_LOG = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"
_NOME_HANDLER_ARQUIVO = "transcritor-arquivo"
_NOME_HANDLER_TELA = "transcritor-tela"


def criar_pastas() -> None:
    """Cria as cinco pastas de trabalho (e a base). Não falha se já existirem."""
    for pasta in PASTAS:
        pasta.mkdir(parents=True, exist_ok=True)


def configurar_logs(nivel: int = logging.INFO) -> None:
    """Envia os logs para ~/Transcricoes/logs/transcritor.log (com rotação) e para a tela.

    Pode ser chamada várias vezes: os handlers só são adicionados uma vez.
    """
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    nomes = {h.name for h in raiz.handlers}
    formatador = logging.Formatter(FORMATO_LOG, FORMATO_DATA)

    if _NOME_HANDLER_ARQUIVO not in nomes:
        LOGS.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            ARQUIVO_LOG, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        arquivo.set_name(_NOME_HANDLER_ARQUIVO)
        arquivo.setFormatter(formatador)
        raiz.addHandler(arquivo)

    if _NOME_HANDLER_TELA not in nomes:
        tela = logging.StreamHandler(sys.stderr)  # no systemd, vai para o journalctl
        tela.set_name(_NOME_HANDLER_TELA)
        tela.setFormatter(formatador)
        raiz.addHandler(tela)


def _registrar_configuracao() -> None:
    log = logging.getLogger("config")
    log.info("Pastas prontas em %s", BASE_DIR)
    for pasta in PASTAS:
        log.info("  %-12s %s", pasta.name, pasta)
    log.info("WhisperX: modelo=%s compute_type=%s idioma=%s device=%s",
             MODELO, COMPUTE_TYPE, IDIOMA, DEVICE)
    log.info("Extensões aceitas: %s", " ".join(sorted(EXTENSOES_ACEITAS)))
    if HF_TOKEN:
        log.info("HF_TOKEN: presente no .env (valor não exibido)")
    else:
        log.warning("HF_TOKEN ausente no .env: a diarização não vai funcionar")


if __name__ == "__main__":
    criar_pastas()
    configurar_logs()
    _registrar_configuracao()
