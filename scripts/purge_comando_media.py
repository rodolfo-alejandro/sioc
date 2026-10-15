"""Limpia audio/video de Centro de Comando y deja grabación en modo a-demanda."""
from pathlib import Path

from sqlalchemy import text

from app import create_app
from app.blueprints.comando_vivo.routes import _ensure_tables, _purge_all_media
from app.extensions import db


def main():
    app = create_app()
    with app.app_context():
        _ensure_tables()
        db.session.execute(
            text(
                "UPDATE comando_operativos "
                "SET grabar_audio=0, grabar_video=0, grabar_media_hasta=NULL"
            )
        )
        db.session.commit()
        purged = _purge_all_media()
        root = Path(app.config.get("UPLOAD_FOLDER", "instance/uploads")) / "comando_vivo"
        removed_files = 0
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in {
                    ".webm",
                    ".ogg",
                    ".m4a",
                    ".mp4",
                    ".ogv",
                    ".wav",
                }:
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass
        print("purged_db", purged, "files", removed_files)


if __name__ == "__main__":
    main()
