import shutil
import subprocess
from pathlib import Path

# ===== RUTAS =====
futbol_dir = Path(r"C:\Users\Usuario\Documents\Data Insights Enterprise\Sporstats\Picks por IA\Futbol")
backend_dir = Path(r"C:\Users\Usuario\Documents\Data Insights Enterprise\Sporstats\Web Proheat Sports\proheat-backend")

# Ajusta según el Excel del día
excel_file = futbol_dir / "Fut 080426.xlsx"

# Script que genera latest.json e histórico
daily_script = futbol_dir / "test_excel_reader_daily.py"

# Archivos generados
source_latest = futbol_dir / "proheat_data" / "latest.json"
source_history_dir = futbol_dir / "proheat_data" / "history"

# Destino en backend
dest_latest = backend_dir / "proheat_data" / "latest.json"
dest_history_dir = backend_dir / "proheat_data" / "history"


def run(cmd, cwd=None):
    print(f"\n[RUN] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Falló comando: {' '.join(cmd)}")


def main():
    if not excel_file.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_file}")

    if not daily_script.exists():
        raise FileNotFoundError(f"No existe el script diario: {daily_script}")

    # 1) Generar latest.json e histórico
    run(["python", str(daily_script), str(excel_file)], cwd=str(futbol_dir))

    if not source_latest.exists():
        raise FileNotFoundError(f"No se generó latest.json en: {source_latest}")

    dest_latest.parent.mkdir(parents=True, exist_ok=True)
    dest_history_dir.mkdir(parents=True, exist_ok=True)

    # 2) Copiar latest.json
    shutil.copy2(source_latest, dest_latest)
    print(f"[OK] Copiado latest.json a {dest_latest}")

    # 3) Copiar todos los históricos
    if source_history_dir.exists():
        for f in source_history_dir.glob("predictions_*.json"):
            shutil.copy2(f, dest_history_dir / f.name)
            print(f"[OK] Copiado histórico: {f.name}")

    # 4) Subir cambios a GitHub
    run(["git", "add", "."], cwd=str(backend_dir))
    run(["git", "commit", "-m", "Update ProHeat daily data"], cwd=str(backend_dir))
    run(["git", "push"], cwd=str(backend_dir))

    print("\n✅ ProHeat actualizado correctamente")


if __name__ == "__main__":
    main()