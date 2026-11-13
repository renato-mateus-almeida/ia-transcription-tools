"""Configuração central do transcritor: pastas, modelo, extensões aceitas e logs.

Rodar direto (`venv/bin/python config.py`) cria as pastas, configura os logs e
registra a configuração atual. Pode ser executado quantas vezes quiser.
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
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
BATCH_SIZE = 16  # reduzir (ex.: 8) se faltar memória na GPU

# --- Extensões aceitas em Entrada --------------------------------------------
EXTENSOES_AUDIO = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".aac", ".wma"})
EXTENSOES_VIDEO = frozenset({".mp4", ".mkv", ".webm", ".mov", ".avi"})
EXTENSOES_ACEITAS = EXTENSOES_AUDIO | EXTENSOES_VIDEO

# --- Claude Code (T7) --------------------------------------------------------
# Caminho fixo: o serviço systemd não tem ~/.local/bin no PATH.
CLAUDE_BIN = Path(os.getenv("CLAUDE_BIN") or "~/.local/bin/claude").expanduser()
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT") or 900)  # segundos (15 min)
PROMPT_ARQUIVO = PROJETO_DIR / "prompt.md"

# --- Credenciais (somente via .env; nunca escrever valores aqui) -------------
HF_TOKEN = (os.getenv("HF_TOKEN") or "").strip()

# --- Logs --------------------------------------------------------------------
ARQUIVO_LOG = LOGS / "transcritor.log"
FORMATO_LOG = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
FORMATO_DATA = "%Y-%m-%d %H:%M:%S"
_NOME_HANDLER_ARQUIVO = "transcritor-arquivo"
_NOME_HANDLER_TELA = "transcritor-tela"


class _FormatadorColorido(logging.Formatter):
    """Pinta só o nome do nível (INFO, WARNING, ERROR) com códigos de cor ANSI."""

    CORES = {
        logging.INFO: "\033[94m",      # azul claro
        logging.WARNING: "\033[93m",   # amarelo
        logging.ERROR: "\033[91m",     # vermelho
        logging.CRITICAL: "\033[91m",  # vermelho
    }
    NORMAL = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        cor = self.CORES.get(record.levelno)
        if cor is None:
            return super().format(record)
        original = record.levelname
        record.levelname = f"{cor}{original}{self.NORMAL}"
        try:
            return super().format(record)
        finally:
            record.levelname = original  # o mesmo registro vai sem cor para o arquivo


def _terminal_aceita_cores(fluxo) -> bool:
    """Só colore num terminal de verdade (não em arquivo, pipe ou journalctl)."""
    return (
        getattr(fluxo, "isatty", lambda: False)()
        and os.getenv("NO_COLOR") is None
        and os.getenv("TERM") != "dumb"
    )


# Bibliotecas que só devem aparecer no log com avisos e erros (as nossas linhas já narram as etapas).
# O Lightning força INFO nos loggers de pacote quando é importado (no meio da transcrição, depois
# deste ajuste); os subpacotes "utilities", de onde saem as mensagens, não são tocados e prevalecem.
_BIBLIOTECAS_SO_AVISOS = (
    "whisperx",
    "lightning", "pytorch_lightning", "lightning_fabric",
    "lightning.pytorch.utilities", "lightning.fabric.utilities",
    "pytorch_lightning.utilities", "lightning_fabric.utilities",
)

# Avisos conhecidos e inofensivos (início da mensagem, como regex).
_AVISOS_IGNORADOS = (
    r"TensorFloat-32 \(TF32\) has been disabled",  # pyannote, a cada diarização
    r"std\(\): degrees of freedom is <= 0",        # PyTorch, em trechos curtos de fala
)


class _IgnorarMensagem(logging.Filter):
    """Descarta registros cuja mensagem contém um trecho específico."""

    def __init__(self, trecho: str) -> None:
        super().__init__()
        self.trecho = trecho

    def filter(self, record: logging.LogRecord) -> bool:
        return self.trecho not in record.getMessage()


def _ajustar_bibliotecas() -> None:
    """Faz as bibliotecas usarem o nosso log (formato, cor e arquivo), só com avisos e erros."""
    for nome in _BIBLIOTECAS_SO_AVISOS:
        logger = logging.getLogger(nome)
        logger.setLevel(logging.WARNING)
        logger.propagate = True
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        # Um handler "vazio" impede o WhisperX de instalar o próprio formato ao ser importado.
        logger.addHandler(logging.NullHandler())

    # Corrida interna do watchdog ao encerrar o observador (inofensiva, mas sai como ERROR).
    inotify = logging.getLogger("watchdog.observers.inotify")
    if not any(isinstance(f, _IgnorarMensagem) for f in inotify.filters):
        inotify.addFilter(_IgnorarMensagem("called when the thread is inactive"))

    for padrao in _AVISOS_IGNORADOS:
        warnings.filterwarnings("ignore", message=padrao)
    # Demais avisos do Python viram uma linha só no log: "WARNING [py.warnings] Categoria: msg".
    warnings.formatwarning = lambda mensagem, categoria, *_args, **_kw: f"{categoria.__name__}: {mensagem}"
    logging.captureWarnings(True)


def relativo(caminho: Path) -> str:
    """Caminho relativo a ~/Transcricoes para mensagens de log (ex.: Brutas/reuniao.txt)."""
    try:
        return str(Path(caminho).relative_to(BASE_DIR))
    except ValueError:
        return str(caminho)


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
        if _terminal_aceita_cores(sys.stderr):
            tela.setFormatter(_FormatadorColorido(FORMATO_LOG, FORMATO_DATA))
        else:
            tela.setFormatter(formatador)
        raiz.addHandler(tela)

    _ajustar_bibliotecas()


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
