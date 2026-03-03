"""
Script para analizar un archivo Excel de sabana de llamadas GPRS.
Uso: python scripts/analizar_excel_gprs.py <ruta_al_archivo.xlsx>
Ejemplo: python scripts/analizar_excel_gprs.py "C:/Descargas/A0151254_A0151254_GPRS_Parte_1_de_1.xlsx"

Analiza TODAS las hojas: nombres, columnas, tipos, y muestra las primeras filas.
No modifica nada; solo imprime un reporte para decidir el modelo y el mapeo.
"""
import sys
import os

def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/analizar_excel_gprs.py <ruta_al_archivo.xlsx>")
        print("Ejemplo: python scripts/analizar_excel_gprs.py instance/uploads/1/archivo.xlsx")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"Error: no existe el archivo: {path}")
        sys.exit(1)

    try:
        import pandas as pd
    except ImportError:
        print("Error: instalar pandas (pip install pandas openpyxl xlrd)")
        sys.exit(1)

    # .xls (Excel 97-2003) requiere xlrd
    ext = os.path.splitext(path)[1].lower()
    engine = 'xlrd' if ext == '.xls' else None  # None = openpyxl para .xlsx
    engine_kwargs = {'ignore_workbook_corruption': True} if ext == '.xls' else {}

    print("=" * 80)
    print("ANÁLISIS DE ARCHIVO EXCEL - SABANA DE LLAMADAS GPRS")
    print("=" * 80)
    print(f"Archivo: {path}")
    print(f"Tamaño: {os.path.getsize(path) / 1024:.1f} KB")
    print()

    xl = pd.ExcelFile(path, engine=engine, engine_kwargs=engine_kwargs)
    sheet_names = xl.sheet_names
    print(f"Total de hojas: {len(sheet_names)}")
    print(f"Nombres: {sheet_names}")
    print()

    for i, name in enumerate(sheet_names):
        print("-" * 80)
        print(f"HOJA {i + 1} (índice {i}): \"{name}\"")
        print("-" * 80)
        df = pd.read_excel(path, sheet_name=i, engine=engine, engine_kwargs=engine_kwargs)
        print(f"Filas: {len(df)}, Columnas: {len(df.columns)}")
        print()
        print("Columnas (orden):")
        for j, col in enumerate(df.columns):
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            sample = df[col].dropna().head(1).tolist()
            sample_str = repr(sample[0])[:50] if sample else "—"
            print(f"  {j+1:2}. {col!r}  |  tipo: {dtype:10}  |  no nulos: {non_null:5}  |  ejemplo: {sample_str}")
        print()
        print("Primeras 3 filas (vista):")
        print(df.head(3).to_string())
        print()

    print("=" * 80)
    print("Fin del análisis. Con este reporte se puede definir modelo y mapeo por hoja.")
    print("=" * 80)


if __name__ == "__main__":
    main()
