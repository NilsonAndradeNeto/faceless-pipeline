"""Utilidades compartilhadas: caminhos, config e logs."""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"
CONFIG = ROOT / "config"

load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(STORAGE / "logs" / "pipeline.log", encoding="utf-8"),
    ],
)


def config(nome: str) -> dict:
    return yaml.safe_load((CONFIG / f"{nome}.yaml").read_text(encoding="utf-8"))


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ler_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def salvar_json(path: Path, dados) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def anexar_jsonl(path: Path, dados: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dados, ensure_ascii=False) + "\n")
