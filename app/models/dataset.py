"""
Modelo de Dataset (DataLab)
"""
from datetime import datetime
from app.extensions import db
import json


class Dataset(db.Model):
    """Dataset subido al sistema DataLab"""
    __tablename__ = 'datasets'
    
    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    source_type = db.Column(db.String(20), nullable=False)  # 'csv', 'xlsx', 'xlsm'
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    rows_count = db.Column(db.Integer, nullable=False)
    columns_count = db.Column(db.Integer, nullable=False)
    preview_json = db.Column(db.Text, nullable=True)  # Primeras 100 filas como JSON
    profile_json = db.Column(db.Text, nullable=True)  # Perfil estadístico
    charts_json = db.Column(db.Text, nullable=True)  # Especificaciones de gráficos
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def get_preview(self):
        """Obtiene el preview como diccionario"""
        if self.preview_json:
            try:
                return json.loads(self.preview_json)
            except:
                return []
        return []
    
    def get_profile(self):
        """Obtiene el perfil como diccionario"""
        if self.profile_json:
            try:
                return json.loads(self.profile_json)
            except:
                return {}
        return {}
    
    def get_charts(self):
        """Obtiene los gráficos como diccionario"""
        if self.charts_json:
            try:
                return json.loads(self.charts_json)
            except:
                return {}
        return {}
    
    def set_preview(self, data):
        """Guarda el preview como JSON"""
        self.preview_json = json.dumps(data, default=str, ensure_ascii=False)
    
    def set_profile(self, data):
        """Guarda el perfil como JSON"""
        self.profile_json = json.dumps(data, default=str, ensure_ascii=False)
    
    def set_charts(self, data):
        """Guarda los gráficos como JSON"""
        self.charts_json = json.dumps(data, default=str, ensure_ascii=False)
    
    def __repr__(self):
        return f'<Dataset {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'unidad_id': self.unidad_id,
            'user_id': self.user_id,
            'name': self.name,
            'source_type': self.source_type,
            'original_filename': self.original_filename,
            'rows_count': self.rows_count,
            'columns_count': self.columns_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

