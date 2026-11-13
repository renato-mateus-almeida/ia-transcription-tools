"""Observador da pasta Entrada: transcreve, gera a nota e move o original para Processados.

É o programa que o serviço systemd executa (T10).
Rodar:  venv/bin/python observador.py      (Ctrl+C para parar)

- Detecta arquivos novos via inotify (watchdog), sem polling da pasta.
- Processa um arquivo por vez, em ordem de chegada; ao iniciar, trata os pendentes.
- Só move para Processados depois de transcrição e nota prontas. Em falha, o arquivo
  fica em Entrada e é tentado de novo no próximo início (reaproveitando a transcrição
  bruta, se ela já existir).
"""

from __future__ import annotations

import fcntl
import logging
import os
import queue
import shutil
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import config
from analise import ErroAnalise, gerar_nota
from transcricao import transcrever

log = logging.getLogger("observador")

SUFIXOS_TEMPORARIOS = (".part", ".crdownload", ".download", ".tmp")
ESTAVEL_POR = 3.0         # segundos com tamanho parado para considerar a cópia concluída
INTERVALO_COPIA = 1.0     # intervalo entre conferências do tamanho do arquivo que chegou
LIMITE_ARQUIVO_VAZIO = 60.0


def eh_aceito(caminho: Path) -> bool:
    """Arquivo direto em Entrada, com extensão aceita e que não seja oculto/temporário."""
    nome = caminho.name.lower()
    return (
        caminho.parent.resolve() == config.ENTRADA.resolve()
        and not nome.startswith(".")
        and not nome.endswith(SUFIXOS_TEMPORARIOS)
        and caminho.suffix.lower() in config.EXTENSOES_ACEITAS
    )


def esperar_copia(caminho: Path) -> bool:
    """Espera o tamanho do arquivo parar de mudar. Retorna False se ele sumir ou ficar vazio."""
    ultimo = None
    parado_desde = time.monotonic()
    while True:
        try:
            st = caminho.stat()
        except FileNotFoundError:
            return False
        atual = (st.st_size, st.st_mtime_ns)
        if atual != ultimo:
            ultimo, parado_desde = atual, time.monotonic()
        else:
            parado = time.monotonic() - parado_desde
            if st.st_size > 0 and parado >= ESTAVEL_POR:
                return True
            if st.st_size == 0 and parado >= LIMITE_ARQUIVO_VAZIO:
                log.warning("%s continua vazio após %.0fs; ignorado", caminho.name, parado)
                return False
        time.sleep(INTERVALO_COPIA)


def transcricao_reaproveitavel(arquivo: Path) -> Path | None:
    """Transcrição bruta de uma tentativa anterior (só se for mais nova que o áudio)."""
    txt = config.BRUTAS / f"{arquivo.stem}.txt"
    if txt.is_file() and txt.stat().st_size > 0 and txt.stat().st_mtime > arquivo.stat().st_mtime:
        return txt
    return None


def destino_livre(pasta: Path, nome: str) -> Path:
    """pasta/nome, ou pasta/nome_1, nome_2... se já existir (nunca sobrescreve)."""
    destino = pasta / nome
    n = 1
    while destino.exists():
        destino = pasta / f"{Path(nome).stem}_{n}{Path(nome).suffix}"
        n += 1
    return destino


def processar(arquivo: Path) -> bool:
    """Transcreve, gera a nota e move para Processados. Retorna True em caso de sucesso."""
    if not esperar_copia(arquivo):
        log.info("%s não está mais disponível; ignorado", arquivo.name)
        return False
    inicio = time.monotonic()
    data = datetime.fromtimestamp(arquivo.stat().st_mtime)  # hora da gravação
    log.info("Processando %s", arquivo.name)
    try:
        txt = transcricao_reaproveitavel(arquivo)
        if txt:
            log.info("Reaproveitando transcrição existente: %s", config.relativo(txt))
        else:
            txt = transcrever(arquivo)
        nota = gerar_nota(txt, data=data)
    except ErroAnalise:
        log.error("%s fica em Entrada; a transcrição será reaproveitada na próxima tentativa", arquivo.name)
        return False
    except Exception:
        log.exception("Falha ao processar %s; o arquivo fica em Entrada", arquivo.name)
        return False
    destino = destino_livre(config.PROCESSADOS, arquivo.name)
    shutil.move(arquivo, destino)
    renomeado = f" | original renomeado: {config.relativo(destino)}" if destino.name != arquivo.name else ""
    log.info("Concluído %s em %.0fs | nota: %s%s",
             arquivo.name, time.monotonic() - inicio, config.relativo(nota), renomeado)
    return True


class Fila:
    """Fila com um único processador; ignora arquivos que já estão na fila."""

    def __init__(self) -> None:
        self._fila: queue.Queue[Path] = queue.Queue()
        self._na_fila: set[Path] = set()
        self._trava = threading.Lock()

    def adicionar(self, caminho: Path) -> None:
        if not eh_aceito(caminho):
            return
        with self._trava:
            if caminho in self._na_fila:
                return
            self._na_fila.add(caminho)
        log.info("Na fila: %s", caminho.name)
        self._fila.put(caminho)

    def trabalhar(self) -> None:
        while True:
            caminho = self._fila.get()
            try:
                processar(caminho)
            finally:
                with self._trava:
                    self._na_fila.discard(caminho)


class Manipulador(FileSystemEventHandler):
    def __init__(self, fila: Fila) -> None:
        self.fila = fila

    def on_created(self, evento: FileSystemEvent) -> None:
        if not evento.is_directory:
            self.fila.adicionar(Path(evento.src_path))

    def on_moved(self, evento: FileSystemEvent) -> None:  # ex.: gravação da T9, .part -> .mp3
        if not evento.is_directory:
            self.fila.adicionar(Path(evento.dest_path))

    def on_closed(self, evento: FileSystemEvent) -> None:  # arquivo sobrescrito no lugar
        if not evento.is_directory:
            self.fila.adicionar(Path(evento.src_path))


def adquirir_trava():
    """Garante um único observador por vez (ex.: o serviço e um manual não processam em dobro).

    Usa flock: o sistema libera a trava sozinho se o processo morrer. Retorna o arquivo aberto
    (manter a referência viva enquanto o observador roda) ou None se outro já estiver rodando.
    """
    arquivo = open(config.BASE_DIR / ".observador.lock", "a+")
    try:
        fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        arquivo.seek(0)
        outro = arquivo.read().strip()
        arquivo.close()
        log.error("Já existe um observador rodando (PID %s). Se for o serviço, veja: "
                  "systemctl --user status transcritor", outro or "?")
        return None
    arquivo.truncate(0)
    arquivo.write(str(os.getpid()))
    arquivo.flush()
    return arquivo


def main() -> int:
    config.criar_pastas()
    config.configurar_logs()
    trava = adquirir_trava()
    if trava is None:
        return 1
    fila = Fila()
    threading.Thread(target=fila.trabalhar, name="processador", daemon=True).start()

    observador = Observer()
    observador.schedule(Manipulador(fila), str(config.ENTRADA), recursive=False)
    observador.start()  # antes de listar os pendentes, para não perder nada que chegue no meio
    log.info("Observando %s", config.ENTRADA)

    pendentes = sorted(
        (p for p in config.ENTRADA.iterdir() if p.is_file() and eh_aceito(p)),
        key=lambda p: p.stat().st_mtime,
    )
    log.info("%d arquivo(s) pendente(s) em Entrada", len(pendentes))
    for p in pendentes:
        fila.adicionar(p)

    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())  # systemctl stop
    signal.signal(signal.SIGINT, lambda *_: parar.set())   # Ctrl+C
    try:
        while not parar.is_set() and observador.is_alive():
            parar.wait(1)
    finally:
        observador.stop()
        observador.join(timeout=5)
        log.info("Observador encerrado")
    return 0 if parar.is_set() else 1  # observador morreu sozinho: código 1 (systemd reinicia)


if __name__ == "__main__":
    sys.exit(main())
