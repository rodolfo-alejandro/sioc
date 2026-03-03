import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv

# Asegurar imports del paquete `app/` al ejecutar desde `scripts/`
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.unidad import Unidad  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.sabana_llamadas import (  # noqa: E402
    CargaLlamada,
    CargaLlamadaCompartida,
    Sujeto,
    SujetoCompartido,
    ResultadoTraficoGPRS,
    ResultadoTraficoVOZ,
    DatoTecnico,
)


def _resolve_unidad_id(unidad_id: int | None, username: str | None) -> int:
    if unidad_id:
        return int(unidad_id)
    if username:
        u = User.query.filter_by(username=username).first()
        if u and u.unidad_id:
            return int(u.unidad_id)
    # Fallback “Central”
    uni = Unidad.query.filter_by(nombre="Central").first()
    if not uni:
        raise SystemExit("No se pudo resolver unidad_id (pasá --unidad-id o --username).")
    return int(uni.id)


def purge_unidad(unidad_id: int, delete_sujetos: bool) -> dict:
    # Cargas de esa unidad
    carga_ids = [cid for (cid,) in db.session.query(CargaLlamada.id).filter(CargaLlamada.unidad_id == unidad_id).all()]
    if not carga_ids:
        return {"unidad_id": unidad_id, "cargas": 0, "trafico_gprs": 0, "trafico_voz": 0, "datos_tecnicos": 0, "shares_carga": 0, "shares_sujeto": 0, "sujetos": 0}

    # Shares por carga (si existen)
    shares_carga = CargaLlamadaCompartida.query.filter(CargaLlamadaCompartida.carga_id.in_(carga_ids)).delete(synchronize_session=False)

    # Hijos por carga
    traf_g = ResultadoTraficoGPRS.query.filter(ResultadoTraficoGPRS.carga_id.in_(carga_ids)).delete(synchronize_session=False)
    traf_v = ResultadoTraficoVOZ.query.filter(ResultadoTraficoVOZ.carga_id.in_(carga_ids)).delete(synchronize_session=False)
    dt = DatoTecnico.query.filter(DatoTecnico.carga_id.in_(carga_ids)).delete(synchronize_session=False)

    # Cargas
    cargas = CargaLlamada.query.filter(CargaLlamada.id.in_(carga_ids)).delete(synchronize_session=False)

    sujetos = 0
    shares_sujeto = 0
    if delete_sujetos:
        sujeto_ids = [sid for (sid,) in db.session.query(Sujeto.id).filter(Sujeto.unidad_id == unidad_id).all()]
        if sujeto_ids:
            shares_sujeto = SujetoCompartido.query.filter(SujetoCompartido.sujeto_id.in_(sujeto_ids)).delete(synchronize_session=False)
            sujetos = Sujeto.query.filter(Sujeto.id.in_(sujeto_ids)).delete(synchronize_session=False)

    db.session.commit()
    return {
        "unidad_id": unidad_id,
        "cargas": int(cargas or 0),
        "trafico_gprs": int(traf_g or 0),
        "trafico_voz": int(traf_v or 0),
        "datos_tecnicos": int(dt or 0),
        "shares_carga": int(shares_carga or 0),
        "shares_sujeto": int(shares_sujeto or 0),
        "sujetos": int(sujetos or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Borra SOLO datos del módulo Sabana (sin tocar el resto de la DB).")
    parser.add_argument("--unidad-id", type=int, default=None, help="Unidad ID a purgar (recomendado).")
    parser.add_argument("--username", default=None, help="Resolver unidad_id por username (ej: admin).")
    parser.add_argument("--delete-sujetos", action="store_true", help="También borra sujetos de esa unidad (y shares).")
    parser.add_argument("--yes", action="store_true", help="No pedir confirmación.")
    args = parser.parse_args()

    load_dotenv()
    app = create_app()
    with app.app_context():
        db.create_all()
        # asegurar schema idempotente del módulo
        try:
            from app.blueprints.sabana_llamadas.routes import _ensure_sabana_schema as ensure  # noqa
            ensure()
        except Exception:
            pass

        unidad_id = _resolve_unidad_id(args.unidad_id, args.username)
        if not args.yes:
            print("ATENCIÓN: esto borra datos de Sabana de la unidad:", unidad_id)
            print("  - Cargas + Tráfico (GPRS/VOZ) + Datos Técnicos + Shares por carga")
            if args.delete_sujetos:
                print("  - También Sujetos + Shares por sujeto")
            resp = input("Escribí BORRAR para confirmar: ").strip()
            if resp != "BORRAR":
                print("Cancelado.")
                return 1

        out = purge_unidad(unidad_id, delete_sujetos=bool(args.delete_sujetos))
        print("OK:", out)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

