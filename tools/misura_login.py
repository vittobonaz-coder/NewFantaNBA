"""
Misura dell'accesso dopo la Fase 2: richieste, tempi e byte, senza interfaccia e SOLO letture.

  python tools/misura_login.py            # get_snapshot (chiave pubblicabile, nessun accesso)
  python tools/misura_login.py --token    # token_bundle con il token in FANTANBA_TOKEN_MISURE (.env o ambiente)

Per ogni prova: processo già avviato, cache vuota ("freddo": tutte le parti, come dopo un cron che le cambia
tutte) oppure già aggiornata ("caldo": nessuna parte). La cache si scrive in una cartella temporanea,
non in data/. Il token non si stampa mai. Nessuna scrittura sul database: token_bundle e get_snapshot
al massimo rigenerano lo snapshot se è rimasto indietro, come farebbe l'app.
"""
import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

t0 = time.perf_counter()
import supabase_rest as rest  # noqa: E402
import league_cache  # noqa: E402
IMPORT_MS = (time.perf_counter() - t0) * 1000


def token_from_env() -> str:
    token = os.environ.get("FANTANBA_TOKEN_MISURE")
    if not token:
        env = ROOT / ".env"
        for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
            if line.strip().startswith("FANTANBA_TOKEN_MISURE="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("Manca FANTANBA_TOKEN_MISURE (token \"Ricordami\" di un utente, nel file .env non versionato)")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", action="store_true", help="misura token_bundle invece di get_snapshot")
    parser.add_argument("--prove", type=int, default=5)
    args = parser.parse_args()
    token = token_from_env() if args.token else None

    counted = {"n": 0, "bytes": 0, "wire": 0, "enc": set()}

    def on_response(response):
        response.read()
        counted["n"] += 1
        counted["bytes"] += len(response.content)
        counted["wire"] += response.num_bytes_downloaded  # byte arrivati in rete (compressi)
        counted["enc"].add(response.headers.get("content-encoding", "nessuna"))

    rest.get_http_client().event_hooks["response"].append(on_response)

    os.chdir(tempfile.mkdtemp(prefix="fantanba_misure_"))  # la cache va qui, non in data/
    results: dict[str, list] = {"freddo": [], "caldo": []}
    for _ in range(args.prove):
        for scenario in ("freddo", "caldo"):
            versions = {} if scenario == "freddo" else league_cache.local_versions()
            counted.update(n=0, bytes=0, wire=0)
            t = time.perf_counter()
            if token:
                bundle = rest.token_bundle(token, versions)
                if bundle is None:
                    sys.exit("Token scaduto o revocato")
            else:
                bundle = rest.get_snapshot(versions)
            t_net = (time.perf_counter() - t) * 1000
            league_cache.apply_snapshot(bundle)
            t_tot = (time.perf_counter() - t) * 1000
            results[scenario].append((t_net, t_tot, counted["n"], counted["bytes"], counted["wire"],
                                      sorted(bundle.get("parts") or {})))

    print(f"RPC: {'token_bundle' if token else 'get_snapshot'}; import supabase_rest + league_cache: {IMPORT_MS:.0f} ms")
    print(f"compressione delle risposte: {', '.join(sorted(counted['enc']))}")
    for scenario, rows in results.items():
        net = [r[0] for r in rows]
        tot = [r[1] for r in rows]
        print(f"{scenario}: richieste {rows[0][2]}, rete {statistics.median(net):.0f} ms ({min(net):.0f}-{max(net):.0f}), "
              f"con scrittura della cache {statistics.median(tot):.0f} ms; {rows[0][3]} byte JSON, "
              f"{rows[0][4]} byte trasferiti; parti: {rows[0][5] or 'nessuna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
