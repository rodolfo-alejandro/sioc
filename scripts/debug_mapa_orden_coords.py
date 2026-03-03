from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import and_, exists, func, literal, tuple_

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.extensions import db
from app.models.sabana_llamadas import CargaLlamada, DatoTecnico, ResultadoTraficoGPRS


def main():
    app = create_app()
    with app.app_context():
        carga = (
            db.session.query(CargaLlamada)
            .filter(CargaLlamada.tipo == "gprs")
            .order_by(CargaLlamada.id.desc())
            .first()
        )
        if not carga:
            print("No hay cargas GPRS.")
            return

        carga_id = int(carga.id)
        print(f"Carga GPRS id={carga_id}")

        # Universo "mapeable": impactos cuyo celda (tráfico) tiene coords en Datos Técnicos.
        coord_exists = exists().where(
            and_(
                DatoTecnico.carga_id == ResultadoTraficoGPRS.carga_id,
                DatoTecnico.tipo == "gprs",
                func.trim(DatoTecnico.celda_id) == func.trim(ResultadoTraficoGPRS.celda),
                DatoTecnico.lat.isnot(None),
                DatoTecnico.long.isnot(None),
            )
        )

        base = (
            db.session.query(
                literal("gprs").label("tipo"),
                ResultadoTraficoGPRS.id.label("impacto_id"),
                ResultadoTraficoGPRS.fecha.label("fecha"),
                func.coalesce(func.substr(ResultadoTraficoGPRS.hora, 1, 8), "00:00:00").label("hora"),
            )
            .filter(ResultadoTraficoGPRS.carga_id == carga_id)
            .filter(coord_exists)
        )

        # Para no recalcular ROW_NUMBER sobre miles de filas (puede ser pesado),
        # tomamos una ventana de candidatos inicial (por fecha/hora) y rankeamos sobre eso.
        u = (
            base.order_by(ResultadoTraficoGPRS.fecha, ResultadoTraficoGPRS.hora, ResultadoTraficoGPRS.id)
            .limit(2000)
            .subquery("u")
        )
        ranked = (
            db.session.query(
                u.c.tipo,
                u.c.impacto_id,
                func.row_number()
                .over(order_by=(u.c.fecha, u.c.hora, u.c.tipo, u.c.impacto_id))
                .label("ord"),
            )
        ).subquery("ranked")

        # Tomar los primeros 15 para inspección
        first = (
            db.session.query(ranked.c.ord, ranked.c.impacto_id)
            .order_by(ranked.c.ord)
            .limit(15)
            .all()
        )
        if not first:
            print("No hay impactos mapeables en esa carga.")
            return

        ids = [int(r.impacto_id) for r in first]
        regs = (
            db.session.query(ResultadoTraficoGPRS)
            .filter(ResultadoTraficoGPRS.id.in_(ids))
            .all()
        )
        reg_by_id = {int(r.id): r for r in regs}

        # Buscar coords técnicas por celda tráfico (latest dt.id)
        def latest_dt_for_celda(celda: str):
            if not celda:
                return None
            return (
                db.session.query(DatoTecnico)
                .filter(
                    DatoTecnico.carga_id == carga_id,
                    DatoTecnico.tipo == "gprs",
                    func.trim(DatoTecnico.celda_id) == func.trim(celda),
                    DatoTecnico.lat.isnot(None),
                    DatoTecnico.long.isnot(None),
                )
                .order_by(DatoTecnico.id.desc())
                .first()
            )

        print("\nord | trafico_id | fecha      | hora     | celda_trafico | celda_tecnica | lat       | lng")
        print("-" * 110)
        for ord_, impacto_id in first:
            ord_ = int(ord_)
            impacto_id = int(impacto_id)
            r = reg_by_id.get(impacto_id)
            celda = (r.celda or "").strip() if r else ""
            dt = latest_dt_for_celda(celda)
            lat = float(dt.lat) if dt and dt.lat is not None else None
            lng = float(dt.long) if dt and dt.long is not None else None
            celda_tec = (dt.celda_id or "").strip() if dt else None
            fecha = r.fecha.isoformat() if (r and r.fecha) else None
            hora = r.hora if r else None
            print(
                f"{ord_:>3} | {impacto_id:>9} | {fecha or '—':<10} | {hora or '—':<8} | "
                f"{celda or '—':<12} | {celda_tec or '—':<12} | {lat if lat is not None else '—':<9} | {lng if lng is not None else '—'}"
            )

        # Extra: confirmar específicamente ord 1/2/10 si existen
        wanted = {1, 2, 10}
        ord_to_id = {int(o): int(i) for o, i in first}
        print("\nResumen ord 1/2/10 (si están en top15):")
        for o in sorted(wanted):
            iid = ord_to_id.get(o)
            if not iid:
                print(f"- ord #{o}: no está en top15 (puede existir más adelante)")
                continue
            r = reg_by_id.get(iid)
            celda = (r.celda or "").strip() if r else ""
            dt = latest_dt_for_celda(celda)
            lat = float(dt.lat) if dt and dt.lat is not None else None
            lng = float(dt.long) if dt and dt.long is not None else None
            print(f"- ord #{o}: trafico_id={iid}, celda_trafico={celda!r}, coords=({lat},{lng})")


if __name__ == "__main__":
    main()

