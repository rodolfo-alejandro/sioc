import sys
import argparse
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from werkzeug.datastructures import FileStorage

# Asegurar imports del paquete `app/` al ejecutar desde `scripts/`
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.extensions import db
from app.models.unidad import Unidad
from app.models.user import User
from app.models.sabana_llamadas import CargaLlamada, ResultadoTraficoGPRS, ResultadoTraficoVOZ, DatoTecnico
from app.blueprints.sabana_llamadas.services import procesar_archivo_gprs, procesar_archivo_voz


def _expected_nonempty_rows(xlsx_path: Path, sheet_name: str, header_row: int) -> int:
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=header_row)
    if df.empty:
        return 0
    # una fila cuenta si tiene al menos un valor no vacío/no-NaN
    return int(df.notna().any(axis=1).sum())


def _expected_cols(xlsx_path: Path, sheet_name: str, header_row: int) -> list[str]:
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=header_row, nrows=1)
    return [str(c) for c in df.columns]


def _load_first_extras(model, carga_id: int):
    row = model.query.filter_by(carga_id=carga_id).order_by(model.id.asc()).first()
    if not row:
        return None, None
    raw = getattr(row, "extras", None)
    if not raw:
        return row, {}
    try:
        return row, json.loads(raw)
    except Exception:
        return row, None


def _ensure_seed_user():
    unidad = Unidad.query.filter_by(nombre="Central").first()
    if not unidad:
        unidad = Unidad(nombre="Central", activo=True)
        db.session.add(unidad)
        db.session.commit()

    user = User.query.filter_by(username="admin").first()
    if not user:
        user = User(
            username="admin",
            email="admin@sioc.local",
            unidad_id=unidad.id,
            active=True,
            must_change_password=False,
        )
        user.set_password("Admin123!")
        db.session.add(user)
        db.session.commit()
    return unidad, user


def _ensure_sabana_schema():
    # Reutilizar la función idempotente del blueprint (agrega columnas/índices faltantes).
    from app.blueprints.sabana_llamadas.routes import _ensure_sabana_schema as ensure  # noqa

    ensure()


def _cleanup_carga(carga_id: int):
    ResultadoTraficoGPRS.query.filter_by(carga_id=carga_id).delete(synchronize_session=False)
    ResultadoTraficoVOZ.query.filter_by(carga_id=carga_id).delete(synchronize_session=False)
    DatoTecnico.query.filter_by(carga_id=carga_id).delete(synchronize_session=False)
    CargaLlamada.query.filter_by(id=carga_id).delete(synchronize_session=False)
    db.session.commit()


def main():
    parser = argparse.ArgumentParser(description="Importa los Excel ejemplo y valida columnas/extras en MySQL.")
    parser.add_argument("--gprs", default="A0151254_A0151254_GPRS_Parte_1_de_1.xlsx")
    parser.add_argument("--voz", default="A0151254_A0151254_VOZ_Parte_1_de_1.xlsx")
    parser.add_argument("--header-row", type=int, default=4, help="Fila de encabezados (0-based) detectada en ejemplos.")
    parser.add_argument("--cleanup", action="store_true", help="Borrar lo importado al finalizar.")
    args = parser.parse_args()

    load_dotenv()
    app = create_app()

    gprs_path = Path(args.gprs).resolve()
    voz_path = Path(args.voz).resolve()
    if not gprs_path.exists():
        raise SystemExit(f"No existe: {gprs_path}")
    if not voz_path.exists():
        raise SystemExit(f"No existe: {voz_path}")

    with app.app_context():
        # asegurar tablas y schema sabana
        db.create_all()
        _ensure_sabana_schema()

        unidad, user = _ensure_seed_user()

        print("DB:", app.config.get("SQLALCHEMY_DATABASE_URI"))
        print("Unidad:", unidad.id, unidad.nombre)
        print("User:", user.id, user.username)

        # Importar GPRS
        with open(gprs_path, "rb") as f:
            fs = FileStorage(stream=f, filename=gprs_path.name, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            carga, ct, cd, err = procesar_archivo_gprs(fs, unidad.id, user.id, sujeto_id=None)
        if err:
            raise SystemExit(f"Error importando GPRS: {err}")
        print("\n[GPRS] carga_id:", carga.id, "trafico:", ct, "tecnicos:", cd)

        # Importar VOZ
        with open(voz_path, "rb") as f:
            fs = FileStorage(stream=f, filename=voz_path.name, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            carga_v, ct_v, cd_v, err_v = procesar_archivo_voz(fs, unidad.id, user.id, sujeto_id=None)
        if err_v:
            raise SystemExit(f"Error importando VOZ: {err_v}")
        print("\n[VOZ]  carga_id:", carga_v.id, "trafico:", ct_v, "tecnicos:", cd_v)

        # Validaciones contra Excel (conteos)
        exp_g_ct = _expected_nonempty_rows(gprs_path, "Resultado de Trafico", args.header_row)
        exp_g_cd = _expected_nonempty_rows(gprs_path, "Datos Tecnicos", args.header_row)
        exp_v_ct = _expected_nonempty_rows(voz_path, "Resultado de Trafico", args.header_row)
        exp_v_cd = _expected_nonempty_rows(voz_path, "Datos Tecnicos", args.header_row)
        print("\nEsperados (por Excel, filas no vacías):")
        print("  GPRS trafico:", exp_g_ct, "tecnicos:", exp_g_cd)
        print("  VOZ  trafico:", exp_v_ct, "tecnicos:", exp_v_cd)

        db_g_ct = ResultadoTraficoGPRS.query.filter_by(carga_id=carga.id).count()
        db_g_cd = DatoTecnico.query.filter_by(carga_id=carga.id, tipo="gprs").count()
        db_v_ct = ResultadoTraficoVOZ.query.filter_by(carga_id=carga_v.id).count()
        db_v_cd = DatoTecnico.query.filter_by(carga_id=carga_v.id, tipo="voz").count()
        print("\nInsertados (por DB):")
        print("  GPRS trafico:", db_g_ct, "tecnicos:", db_g_cd)
        print("  VOZ  trafico:", db_v_ct, "tecnicos:", db_v_cd)

        # Validaciones de columnas en extras (solo primera fila como smoke test)
        g_cols = _expected_cols(gprs_path, "Resultado de Trafico", args.header_row)
        g_dt_cols = _expected_cols(gprs_path, "Datos Tecnicos", args.header_row)
        v_cols = _expected_cols(voz_path, "Resultado de Trafico", args.header_row)
        v_dt_cols = _expected_cols(voz_path, "Datos Tecnicos", args.header_row)

        row_g, ex_g = _load_first_extras(ResultadoTraficoGPRS, carga.id)
        row_gdt, ex_gdt = _load_first_extras(DatoTecnico, carga.id)
        row_v, ex_v = _load_first_extras(ResultadoTraficoVOZ, carga_v.id)
        row_vdt, ex_vdt = _load_first_extras(DatoTecnico, carga_v.id)

        def chk(label, expected_cols, extras_obj):
            if extras_obj is None:
                print(f"  [WARN] {label}: extras no es JSON parseable")
                return
            if not isinstance(extras_obj, dict):
                print(f"  [WARN] {label}: extras no es dict")
                return
            missing = [c for c in expected_cols if c not in extras_obj]
            extra = [k for k in extras_obj.keys() if k not in expected_cols]
            ok = (len(missing) == 0)
            print(f"  {label}: extras_keys={len(extras_obj)} expected_cols={len(expected_cols)} missing={len(missing)} extra_keys={len(extra)} ok={ok}")
            if missing:
                print("    faltan:", missing[:10], ("..." if len(missing) > 10 else ""))
            if extra:
                # en teoría debería ser 0; si hay, suele ser por columnas duplicadas desambiguadas
                print("    adicionales:", extra[:10], ("..." if len(extra) > 10 else ""))

        print("\nValidación de columnas en extras (smoke test primera fila):")
        chk("GPRS trafico", g_cols, ex_g)
        chk("GPRS datos_tecnicos", g_dt_cols, ex_gdt)
        chk("VOZ trafico", v_cols, ex_v)
        chk("VOZ datos_tecnicos", v_dt_cols, ex_vdt)

        if args.cleanup:
            print("\nCleanup: borrando cargas importadas…")
            _cleanup_carga(carga.id)
            _cleanup_carga(carga_v.id)
            print("Cleanup OK.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

