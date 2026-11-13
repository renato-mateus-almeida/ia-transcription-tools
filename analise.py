"""Análise com o Claude: transforma uma transcrição bruta numa nota em Markdown.

Chama `claude -p` sem ferramentas, com o prompt.md como system prompt, a partir de
~/Transcricoes (fora do repositório, para não carregar o CLAUDE.md do projeto).
Em caso de falha, registra no log, mantém a transcrição bruta e lança ErroAnalise.

Teste avulso:  venv/bin/python analise.py <transcrição .txt>
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger("analise")

SECOES = ("Resumo executivo", "Decisões tomadas", "Tarefas", "Pontos técnicos", "Dúvidas em aberto")


class ErroAnalise(RuntimeError):
    """Falha ao gerar a nota (a transcrição bruta é mantida)."""


def nome_da_nota(transcricao: Path, data: datetime) -> str:
    """AAAA-MM-DD_HHMM_nome.md (PRD, seção 7)."""
    return f"{data:%Y-%m-%d_%H%M}_{transcricao.stem}.md"


def _ambiente_limpo() -> dict[str, str]:
    """Remove variáveis herdadas de uma sessão do Claude Code (armadilha da T7 no CLAUDE.md)."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")}


def _chamar_claude(texto: str) -> str:
    comando = [
        str(config.CLAUDE_BIN), "-p",
        "--system-prompt-file", str(config.PROMPT_ARQUIVO),
        "--tools", "",                # nenhuma ferramenta: só lê o texto e responde
        "--strict-mcp-config",        # não carrega conectores MCP do usuário
        "--no-session-persistence",   # não grava a conversa (dados sensíveis) em disco
        "--output-format", "json",
    ]
    # Transcrição via stdin: um argumento no Linux é limitado a 128 KB.
    entrada = f"<transcricao>\n{texto}\n</transcricao>\n"
    try:
        proc = subprocess.run(
            comando, input=entrada, capture_output=True, text=True,
            timeout=config.CLAUDE_TIMEOUT, cwd=config.BASE_DIR, env=_ambiente_limpo(),
        )
    except subprocess.TimeoutExpired:
        raise ErroAnalise(f"claude -p excedeu o timeout de {config.CLAUDE_TIMEOUT}s") from None
    except OSError as e:
        raise ErroAnalise(f"não foi possível executar {config.CLAUDE_BIN}: {e}") from e

    try:
        resposta = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detalhe = (proc.stderr or proc.stdout).strip()[:500]
        raise ErroAnalise(f"claude -p falhou (código {proc.returncode}): {detalhe}") from None
    if proc.returncode != 0 or resposta.get("is_error") or resposta.get("subtype") != "success":
        raise ErroAnalise(
            f"claude -p retornou erro (código {proc.returncode}, {resposta.get('subtype')}): "
            f"{str(resposta.get('result'))[:500]}"
        )
    nota = (resposta.get("result") or "").strip()
    if not nota:
        raise ErroAnalise("claude -p retornou resposta vazia")
    return nota


def gerar_nota(transcricao: Path, data: datetime | None = None) -> Path:
    """Gera Notas/AAAA-MM-DD_HHMM_nome.md a partir da transcrição. Retorna o caminho da nota.

    `data` é a data da reunião (na T8, a hora da gravação); por padrão, a data do .txt.
    """
    transcricao = Path(transcricao)
    data = data or datetime.fromtimestamp(transcricao.stat().st_mtime)
    config.criar_pastas()
    destino = config.NOTAS / nome_da_nota(transcricao, data)
    inicio = time.monotonic()
    log.info("Gerando nota de %s com claude -p", transcricao.name)
    try:
        texto = transcricao.read_text(encoding="utf-8").strip()
        if not texto:
            raise ErroAnalise("transcrição vazia")
        corpo = _chamar_claude(texto)
    except ErroAnalise as e:
        log.error("Falha ao gerar a nota de %s: %s (transcrição mantida em %s)",
                  transcricao.name, e, config.relativo(transcricao))
        raise

    faltando = [s for s in SECOES if not re.search(rf"^##\s+{re.escape(s)}\s*$", corpo, re.MULTILINE | re.IGNORECASE)]
    if faltando:
        log.warning("Nota de %s sem as seções: %s", transcricao.name, ", ".join(faltando))

    nota = f"# Reunião {data:%d/%m/%Y %H:%M} — {transcricao.stem}\n\n{corpo}\n"
    temporario = destino.with_suffix(".md.tmp")
    temporario.write_text(nota, encoding="utf-8")
    temporario.replace(destino)  # grava inteira ou nada
    log.info("Nota salva em %s (%.0fs)", config.relativo(destino), time.monotonic() - inicio)
    return destino


if __name__ == "__main__":
    config.configurar_logs()
    if len(sys.argv) != 2:
        sys.exit("Uso: venv/bin/python analise.py <transcrição .txt>")
    entrada = Path(sys.argv[1]).expanduser()
    if not entrada.is_file():
        sys.exit(f"Arquivo não encontrado: {entrada}")
    try:
        print(gerar_nota(entrada))
    except ErroAnalise:
        sys.exit(1)
