import sqlite3
import os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- BASE DE DATOS SQLite (Persistente) ---
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'indice_global.db')

def init_db():
    """Inicializa la base de datos SQLite con la tabla y datos por defecto."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tesis (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            autor TEXT NOT NULL,
            fecha_indexacion TEXT NOT NULL
        )
    ''')
    # Insertar datos por defecto solo si la tabla está vacía
    cursor.execute('SELECT COUNT(*) FROM tesis')
    if cursor.fetchone()[0] == 0:
        datos_defecto = [
            ("UD-2026-001", "JustiVoto: Análisis Electoral en Colombia", "Juan Diego G."),
            ("UD-2026-005", "Algoritmos de Optimización en Grafos", "Carlos Rodríguez")
        ]
        for id_t, titulo, autor in datos_defecto:
            cursor.execute(
                'INSERT INTO tesis (id, titulo, autor, fecha_indexacion) VALUES (?, ?, ?, ?)',
                (id_t, titulo, autor, datetime.now().isoformat())
            )
        print("[INIT] Datos por defecto insertados en el índice global.")
    conn.commit()
    conn.close()

def get_db():
    """Obtiene una conexión a la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- ENDPOINTS ---

@app.route('/api/indexar', methods=['POST'])
def indexar_tesis():
    datos = request.json

    # Validación de simulación de fallo (case-insensitive)
    titulo_recibido = datos.get("titulo", "").strip().lower()

    if titulo_recibido == "provocar_fallo":
        print("\n[ALERTA CENTRAL] Simulando caída... Rechazando petición.")
        return jsonify({"error": "Base de datos central caída"}), 500

    # Guardar en SQLite
    conn = get_db()
    try:
        conn.execute(
            'INSERT OR REPLACE INTO tesis (id, titulo, autor, fecha_indexacion) VALUES (?, ?, ?, ?)',
            (datos["id"], datos["titulo"], datos["autor"], datetime.now().isoformat())
        )
        conn.commit()
        print(f"\n[NUEVO INGRESO] Tesis '{datos.get('titulo')}' indexada globalmente en SQLite.")
        return jsonify({"mensaje": "Tesis indexada", "id": datos["id"]}), 201
    except Exception as e:
        print(f"[ERROR BD] {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/tesis', methods=['GET'])
def obtener_tesis():
    conn = get_db()
    tesis = [dict(row) for row in conn.execute('SELECT id, titulo, autor FROM tesis ORDER BY fecha_indexacion DESC').fetchall()]
    conn.close()
    return jsonify(tesis), 200

@app.route('/api/estado', methods=['GET'])
def estado():
    """Health check para verificar si el coordinador está activo."""
    return jsonify({"estado": "activo", "timestamp": datetime.now().isoformat()}), 200

# --- INICIALIZACIÓN ---
if __name__ == '__main__':
    init_db()
    print(f"[COORDINADOR CENTRAL] BD SQLite en: {DB_PATH}")
    print("[COORDINADOR CENTRAL] Escuchando en puerto 5000...")
    app.run(host='0.0.0.0', port=5000)
