"""teste-iara — confere se uma máquina Windows consegue rodar a Iara.

Só biblioteca padrão. Não pede nem guarda senha, não envia nada a lugar
nenhum: os acessos de rede só verificam se o endereço responde. Grava apenas
um relatório em texto (ao lado do executável ou na pasta temporária) e uma
cópia de si mesmo em %LOCALAPPDATA%\\teste-iara, apagada no fim.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import platform
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSAO = "1.0"
ENDERECOS = [
    ("GitHub", "https://github.com"),
    ("GitHub (arquivos das releases)", "https://objects.githubusercontent.com"),
    ("Anthropic (API do Claude)", "https://api.anthropic.com"),
    ("Claude", "https://claude.ai"),
    ("Super Sapiens", "https://supersapiensbackend.agu.gov.br"),
]

resultados: list[tuple[str, bool | None, str]] = []  # (item, ok, detalhe); ok None = informativo


def registrar(item: str, ok: bool | None, detalhe: str) -> None:
    resultados.append((item, ok, detalhe))
    marca = {True: "OK   ", False: "FALHA", None: "info "}[ok]
    print(f"[{marca}] {item}: {detalhe}", flush=True)


def esconder_usuario(texto: str) -> str:
    casa = str(Path.home())
    return texto.replace(casa, "~") if casa else texto


# ---------------------------------------------------------------- checagens

def checar_ambiente() -> None:
    exe = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    registrar("Executável rodou", True, esconder_usuario(str(exe)))
    registrar("Windows", None, f"{platform.release()} (build {platform.version()})")


def checar_copia_em_appdata() -> None:
    """O AppLocker costuma barrar executável em AppData; a Iara instala ali."""
    if not getattr(sys, "frozen", False):
        registrar("Rodar a partir de %LOCALAPPDATA%", None, "pulado (não é o .exe)")
        return
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "teste-iara"
    try:
        base.mkdir(parents=True, exist_ok=True)
        copia = base / "teste-iara-copia.exe"
        shutil.copy2(sys.executable, copia)
        r = subprocess.run([str(copia), "--filho"], capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0 and "filho-ok" in r.stdout
        registrar("Rodar a partir de %LOCALAPPDATA%", ok,
                  "rodou" if ok else f"não rodou (código {r.returncode}) {r.stderr.strip()[:200]}")
    except Exception as exc:  # bloqueio costuma vir como PermissionError/OSError
        registrar("Rodar a partir de %LOCALAPPDATA%", False, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(base, ignore_errors=True)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def checar_dpapi() -> None:
    try:
        dado = secrets.token_bytes(32)
        buf = ctypes.create_string_buffer(dado, len(dado))
        entrada = _Blob(len(dado), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        cifrado = _Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), None, None, None, None,
                                                       0, ctypes.byref(cifrado)):
            raise OSError(ctypes.GetLastError(), "CryptProtectData falhou")
        claro = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(cifrado), None, None, None, None,
                                                         0, ctypes.byref(claro)):
            raise OSError(ctypes.GetLastError(), "CryptUnprotectData falhou")
        volta = ctypes.string_at(claro.pbData, claro.cbData)
        ctypes.windll.kernel32.LocalFree(cifrado.pbData)
        ctypes.windll.kernel32.LocalFree(claro.pbData)
        registrar("Cofre do Windows (DPAPI)", volta == dado, "grava e lê" if volta == dado else "leu diferente")
    except Exception as exc:
        registrar("Cofre do Windows (DPAPI)", False, f"{type(exc).__name__}: {exc}")


def checar_rede() -> None:
    proxies = urllib.request.getproxies()
    registrar("Proxy do sistema", None, ", ".join(f"{k}={v}" for k, v in proxies.items()) or "nenhum configurado")
    ctx = ssl.create_default_context()
    for nome, url in ENDERECOS:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "teste-iara"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                registrar(f"Rede: {nome}", True, f"respondeu {resp.status}")
        except urllib.error.HTTPError as exc:  # respondeu, mesmo com erro: o caminho existe
            registrar(f"Rede: {nome}", True, f"respondeu {exc.code}")
        except ssl.SSLError as exc:
            registrar(f"Rede: {nome}", False, f"certificado/inspeção TLS: {exc}")
        except Exception as exc:
            registrar(f"Rede: {nome}", False, f"{type(exc).__name__}: {exc}")


def checar_ferramentas() -> None:
    for prog in ("git", "python", "py"):
        caminho = shutil.which(prog)
        registrar(f"Programa '{prog}'", None, esconder_usuario(caminho) if caminho else "não encontrado")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-ExecutionPolicy -List | ForEach-Object { \"$($_.Scope)=$($_.ExecutionPolicy)\" };"
                            "\"Modo=$($ExecutionContext.SessionState.LanguageMode)\""],
                           capture_output=True, text=True, timeout=60)
        registrar("PowerShell", r.returncode == 0, " ".join(r.stdout.split()) or r.stderr.strip()[:200])
    except Exception as exc:
        registrar("PowerShell", False, f"{type(exc).__name__}: {exc}")


def checar_pagina_local() -> None:
    """Sobe uma página em 127.0.0.1 (como o login da Iara) e espera o navegador chegar."""
    token = secrets.token_urlsafe(16)
    chegou = threading.Event()

    class Tratador(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencioso
            pass

        def do_GET(self):
            if self.path == f"/?t={token}":
                corpo = PAGINA_ESPERA.encode("utf-8")
            elif self.path == f"/ok?t={token}":
                chegou.set()
                corpo = b"ok"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)

    try:
        srv = HTTPServer(("127.0.0.1", 0), Tratador)
    except Exception as exc:
        registrar("Página local (127.0.0.1)", False, f"não abriu a porta: {exc}")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={token}"
    print(f"\nAbrindo {url} no navegador (se não abrir, copie o endereço)...", flush=True)
    webbrowser.open(url)
    ok = chegou.wait(120)
    srv.shutdown()
    registrar("Página local (127.0.0.1)", ok, "o navegador abriu a página" if ok else "o navegador não chegou em 2 min")


PAGINA_ESPERA = """<!doctype html><meta charset="utf-8"><title>teste-iara</title>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto">
<h1>teste-iara</h1><p id="m">Conferindo…</p>
<script>fetch('/ok'+location.search).then(()=>{document.getElementById('m').textContent=
'Página local funcionou. Pode fechar esta aba e voltar à janela preta.'})</script></body>"""


# ---------------------------------------------------------------- relatório

def gravar_relatorio() -> Path:
    linhas = [f"teste-iara {VERSAO} — {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for item, ok, detalhe in resultados:
        linhas.append(f"[{ {True: 'OK', False: 'FALHA', None: 'info'}[ok] }] {item}: {detalhe}")
    texto = "\n".join(linhas) + "\n"
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    for pasta in (exe_dir, Path(tempfile.gettempdir())):
        try:
            destino = pasta / "relatorio-teste-iara.txt"
            destino.write_text(texto, encoding="utf-8")
            return destino
        except Exception:
            continue
    return Path("(não gravado)")


def main() -> int:
    if "--filho" in sys.argv:
        print("filho-ok")
        return 0
    print(f"teste-iara {VERSAO}: confere se esta máquina roda a Iara. Leva 1 a 3 minutos.\n", flush=True)
    for passo in (checar_ambiente, checar_copia_em_appdata, checar_dpapi, checar_ferramentas,
                  checar_rede, checar_pagina_local):
        try:
            passo()
        except Exception as exc:
            registrar(passo.__name__, False, f"erro inesperado: {type(exc).__name__}: {exc}")
    destino = gravar_relatorio()
    falhas = sum(1 for _, ok, _ in resultados if ok is False)
    print(f"\n{'Nenhuma falha.' if not falhas else f'{falhas} falha(s).'} "
          f"Relatório: {esconder_usuario(str(destino))}")
    input("\nAperte Enter para fechar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
