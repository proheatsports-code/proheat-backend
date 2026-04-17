import json
import re
import sys
from datetime import time, datetime
from pathlib import Path
from typing import Any

import pandas as pd


# =========================================================
# CONFIG
# =========================================================
DEFAULT_FILE_PATH = Path(
    r"C:\Users\Usuario\Documents\Data Insights Enterprise\Sporstats\Picks por IA\Futbol\Fut 160426.xlsx"
)

DEFAULT_OUTPUT_DIR = Path(
    r"C:\Users\Usuario\Documents\Data Insights Enterprise\Sporstats\Web Proheat Sports\proheat-backend\proheat_data"
)

SHEETS = {
    "general": "Hoja1",
    "ultra": "Hoja2",
    "stakes": "Hoja3",
    "combinadas": "Hoja4",
    "goles": "Hoja5",
    "top": "Hoja6",
    "alta_confianza": "Hoja7",
    "public": "Hoja8",
    "inferno": "Hoja9",
}

COLUMN_ALIASES = {
    # base
    "hora": "hora",
    "liga": "liga",
    "sem": "sem",
    "partido": "partido",

    # predicciones
    "prediccion_1": "prediccion_1",
    "predicción_1": "prediccion_1",
    "prediccion 1": "prediccion_1",
    "predicción 1": "prediccion_1",
    "prediccion_2": "prediccion_2",
    "predicción_2": "prediccion_2",
    "prediccion 2": "prediccion_2",
    "predicción 2": "prediccion_2",

    # ml / goles
    "ml_(prob)": "ml_prob",
    "ml (prob)": "ml_prob",
    "ml": "ml_prob",
    "goles_local": "goles_local",
    "goles local": "goles_local",
    "goles_visitante": "goles_visitante",
    "goles visitante": "goles_visitante",
    "marcador global": "marcador_global",
    "mitades": "mitades",

    # otros mercados
    "sot": "sot",
    "corners": "corners",
    "tarjetas": "tarjetas",

    # otras hojas
    "stake": "stake",
    "combinada": "combinada",
    "probabilidad": "probabilidad",
    "prob.": "probabilidad",
    "pick": "pick",
    "pick_1": "pick_1",
    "pick_2": "pick_2",

    # hoja 7
    "rank": "rank",
    "equipo": "equipo",
    "goles": "goles",
    "confiabilidad final": "confiabilidad_final",
}

TEXT_REPLACEMENTS = {
    "Agropecualrio": "Agropecuario",
    "Empata": "Empate",
    "Gana o Empata": "Gana o Empate",
    "Union": "Unión",
    "Millonarios 1 Gol": "Millonarios Goles: +0.5",
}


# =========================================================
# HELPERS
# =========================================================
def get_input_file() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return DEFAULT_FILE_PATH


def ensure_dirs(base_output_dir: Path, history_dir: Path) -> None:
    base_output_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)


def extract_date_from_filename(file_path: Path) -> str:
    name = file_path.stem
    match = re.search(r"(\d{2})(\d{2})(\d{2})$", name)
    if not match:
        raise ValueError(
            f"No pude extraer fecha del nombre del archivo: {file_path.name}. "
            "Usa formato tipo 'Fut 080426.xlsx'."
        )
    dd, mm, yy = match.groups()
    year = 2000 + int(yy)
    date_obj = datetime(year, int(mm), int(dd))
    return date_obj.strftime("%Y-%m-%d")


def normalize_column_name(col: Any) -> str:
    value = str(col).strip().lower()
    value = re.sub(r"\s+", " ", value)
    return COLUMN_ALIASES.get(value, value.replace(" ", "_"))


def format_time_value(value: Any) -> str:
    if pd.isna(value):
        return ""

    if isinstance(value, time):
        return value.strftime("%H:%M")

    if isinstance(value, datetime):
        return value.strftime("%H:%M")

    if isinstance(value, pd.Timestamp):
        return value.strftime("%H:%M")

    if isinstance(value, (int, float)):
        try:
            total_seconds = int(round(float(value) * 24 * 60 * 60))
            hours = (total_seconds // 3600) % 24
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"
        except Exception:
            return str(value)

    text = str(value).strip()
    match = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    return text


def clean_text(value: Any) -> Any:
    if pd.isna(value):
        return ""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value

    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)

    for wrong, right in TEXT_REPLACEMENTS.items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)

    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\(\s*", "(", text)
    text = re.sub(r"\s*\)", ")", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def row_is_empty(row: dict[str, Any]) -> bool:
    return all(str(v).strip() == "" for v in row.values())


def sort_by_hora(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key_func(item: dict[str, Any]) -> tuple[int, int]:
        hora = str(item.get("hora", "")).strip()
        match = re.match(r"^(\d{2}):(\d{2})$", hora)
        if not match:
            return (99, 99)
        return (int(match.group(1)), int(match.group(2)))

    return sorted(records, key=key_func)


def read_sheet(file_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    df.columns = [normalize_column_name(col) for col in df.columns]

    records = []
    for row in df.to_dict(orient="records"):
        clean_row = {}
        for key, value in row.items():
            clean_row[key] = format_time_value(value) if key == "hora" else clean_text(value)

        if not row_is_empty(clean_row):
            records.append(clean_row)

    return sort_by_hora(records)


def preview_records(title: str, records: list[dict[str, Any]], limit: int = 3) -> None:
    print(f"\n=== {title} ===")
    if not records:
        print("Sin datos")
        return

    for row in records[:limit]:
        print(row)


# =========================================================
# CORE LOGIC
# =========================================================
def build_daily_payload(file_path: Path) -> dict[str, Any]:
    prediction_date = extract_date_from_filename(file_path)

    payload: dict[str, Any] = {
        "date": prediction_date,
        "source_file": file_path.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    for key, sheet_name in SHEETS.items():
        try:
            payload[key] = read_sheet(file_path, sheet_name)
        except Exception as e:
            print(f"[ERROR] No se pudo leer {sheet_name}: {e}")
            payload[key] = []

    return payload


def save_daily_payload(
    payload: dict[str, Any],
    base_output_dir: Path,
    history_dir: Path
) -> tuple[Path, Path]:
    date_str = payload["date"]
    daily_path = history_dir / f"predictions_{date_str}.json"
    latest_path = base_output_dir / "latest.json"

    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return daily_path, latest_path


def process_excel_to_json(
    file_path: Path,
    base_output_dir: Path
) -> dict[str, Any]:
    """
    Función reutilizable para usar desde backend.py o desde cualquier otro script.
    Procesa el Excel, genera el payload y actualiza:
    - history/predictions_YYYY-MM-DD.json
    - latest.json
    """
    if not file_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo Excel: {file_path}")

    history_dir = base_output_dir / "history"
    ensure_dirs(base_output_dir, history_dir)

    payload = build_daily_payload(file_path)
    daily_path, latest_path = save_daily_payload(payload, base_output_dir, history_dir)

    return {
        "ok": True,
        "date": payload.get("date"),
        "source_file": payload.get("source_file"),
        "generated_at": payload.get("generated_at"),
        "daily_path": str(daily_path),
        "latest_path": str(latest_path),
        "counts": {key: len(payload.get(key, [])) for key in SHEETS.keys()},
        "payload": payload,
    }


# =========================================================
# CLI
# =========================================================
def main() -> None:
    file_path = get_input_file()
    base_output_dir = DEFAULT_OUTPUT_DIR

    if not file_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {file_path}")

    print(f"[OK] Excel usado: {file_path.name}")

    result = process_excel_to_json(file_path, base_output_dir)
    payload = result["payload"]

    preview_records("PUBLIC (Hoja8)", payload["public"], limit=5)
    preview_records("GENERAL (Hoja1)", payload["general"], limit=3)
    preview_records("ULTRA (Hoja2)", payload["ultra"], limit=3)
    preview_records("STAKES (Hoja3)", payload["stakes"], limit=3)
    preview_records("COMBINADAS (Hoja4)", payload["combinadas"], limit=3)
    preview_records("GOLES (Hoja5)", payload["goles"], limit=3)
    preview_records("TOP (Hoja6)", payload["top"], limit=3)
    preview_records("ALTA CONFIANZA (Hoja7)", payload["alta_confianza"], limit=3)
    preview_records("INFERNO (Hoja9)", payload["inferno"], limit=3)

    print("\nResumen:")
    for key, count in result["counts"].items():
        print(f"- {key}: {count} registros")

    print(f"\n[OK] Histórico diario guardado en: {result['daily_path']}")
    print(f"[OK] latest.json actualizado en: {result['latest_path']}")


if __name__ == "__main__":
    main()