"""
Esegue uno o più comandi in fila su GitHub Actions e, se uno fallisce, ne rende leggibile l'errore anche senza
accesso ai log (Fase 6, app Mac): le ultime righe vanno nel riepilogo dell'esecuzione ($GITHUB_STEP_SUMMARY) e in
un'annotazione ::error::, ripulite da colori e caratteri di controllo (GitHub scarta le annotazioni che li hanno).

  python tools/esegui_con_log.py "python tools/prepara_build.py --tag v1.0.0" "flet build macos --yes"

Ogni argomento è un comando (diviso come farebbe la shell, con shlex). Esce con il codice del primo che fallisce.
Solo libreria standard. Usato da .github/workflows/release.yml (job macos).
"""
import os
import re
import shlex
import subprocess
import sys

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean(lines: list[str]) -> list[str]:
    """Righe senza colori, caratteri non stampabili e righe vuote."""
    out = []
    for line in lines:
        text = "".join(ch for ch in ANSI.sub("", line).rstrip() if ch.isprintable())
        if text.strip():
            out.append(text)
    return out


SPINNER = re.compile(r"^\(\s*●\s*\)")  # Righe dell'animazione di flet ("( ●   ) Running Flutter doctor...")
FLET_ERROR = "Error building Flet app"


def interesting(lines: list[str]) -> list[str]:
    """
    Le righe utili: senza animazioni; con flet, quelle PRIMA del primo riquadro "Error building Flet app"
    (l'errore vero è lì, dopo flet ripete il riquadro e lancia flutter doctor).
    """
    rows = [line for line in clean(lines) if not SPINNER.match(line)]
    first = next((i for i, line in enumerate(rows) if FLET_ERROR in line), None)
    return rows[:first] if first else rows


def report(command: str, code: int, lines: list[str]) -> None:
    tail = interesting(lines)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Comando fallito (codice {code}): `{command}`\n\n```\n" + "\n".join(tail[-150:]) + "\n```\n")
    message = command + "\n" + "\n".join(line[:200] for line in tail[-40:])[-3800:]
    message = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A").replace("::", ": :")
    # A capo prima: flet lascia sulla riga codici del terminale (es. "\x1b[?25h") e GitHub riconosce il comando
    # solo a inizio riga
    print(f"\n::error title=Comando fallito ({code})::{message}", flush=True)


def main() -> int:
    for command in sys.argv[1:]:
        print(f"$ {command}", flush=True)
        lines: list[str] = []
        proc = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
            del lines[:-3000]  # Basta la coda (abbondante: l'errore di flet sta prima delle sue ripetizioni)
        code = proc.wait()
        if code:
            report(command, code, lines)
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
