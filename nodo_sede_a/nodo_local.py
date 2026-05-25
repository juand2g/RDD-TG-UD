import sqlite3
import os
from datetime import datetime
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURACIÓN ---
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sede_a.db')
URL_COORDINADOR = "http://144.217.85.170:5000/api/indexar"

# --- BASE DE DATOS SQLite (Persistente) ---

def init_db():
    """Inicializa la base de datos SQLite con tablas y datos por defecto."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tesis (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            autor TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'sincronizado',
            fecha_registro TEXT NOT NULL
        )
    ''')
    # Insertar datos por defecto solo si la tabla está vacía
    cursor.execute('SELECT COUNT(*) FROM tesis')
    if cursor.fetchone()[0] == 0:
        datos_defecto = [
            ("UD-2026-001", "JustiVoto: Análisis Electoral en Colombia", "Juan Diego G.", "sincronizado"),
            ("UD-2026-005", "Algoritmos de Optimización en Grafos", "Carlos Rodríguez", "sincronizado")
        ]
        for id_t, titulo, autor, estado in datos_defecto:
            cursor.execute(
                'INSERT INTO tesis (id, titulo, autor, estado, fecha_registro) VALUES (?, ?, ?, ?, ?)',
                (id_t, titulo, autor, estado, datetime.now().isoformat())
            )
        print("[INIT] Datos por defecto insertados en Sede A.")
    conn.commit()
    conn.close()

def get_db():
    """Obtiene una conexión a la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- ENDPOINTS ---

@app.route('/api/publicar', methods=['POST'])
def publicar_tesis():
    tesis = request.json
    id_tesis = tesis["id"]
    titulo = tesis["titulo"]
    autor = tesis["autor"]

    conn = get_db()
    try:
        # PASO 1: Transacción Local — SIEMPRE se guarda (autonomía de la sede)
        conn.execute(
            'INSERT OR REPLACE INTO tesis (id, titulo, autor, estado, fecha_registro) VALUES (?, ?, ?, ?, ?)',
            (id_tesis, titulo, autor, 'pendiente_sync', datetime.now().isoformat())
        )
        conn.commit()
        print(f"\n[ÉXITO LOCAL] Tesis {id_tesis} guardada en SQLite de Sede A.")

        # PASO 2: Intento de Sincronización Distribuida
        try:
            print("[INTENTO] Contactando al servidor coordinador central...")
            respuesta = requests.post(URL_COORDINADOR, json=tesis, timeout=5)

            if respuesta.status_code == 201:
                # Sincronización exitosa — actualizar estado
                conn.execute('UPDATE tesis SET estado = ? WHERE id = ?', ('sincronizado', id_tesis))
                conn.commit()
                print("[ÉXITO DISTRIBUIDO] El coordinador confirmó. Estado: sincronizado.")
                return jsonify({
                    "status": "Éxito",
                    "msg": "Sincronización global completada",
                    "estado_tesis": "sincronizado"
                }), 200
            else:
                # El coordinador rechazó (ej: provocar_fallo) — la tesis queda pendiente
                print(f"[COORDINADOR RECHAZÓ] Status {respuesta.status_code}. Tesis queda pendiente de sync.")
                return jsonify({
                    "status": "Pendiente",
                    "msg": "Tesis guardada localmente. Coordinador no disponible, pendiente de sincronización.",
                    "estado_tesis": "pendiente_sync"
                }), 202

        except requests.exceptions.RequestException as e:
            # Fallo de red — la tesis queda guardada localmente, pendiente de sync
            print(f"[FALLO RED] Error: {e}")
            print(f"[CONSISTENCIA EVENTUAL] Tesis {id_tesis} guardada localmente. Pendiente de sincronización.")
            return jsonify({
                "status": "Pendiente",
                "msg": "Tesis guardada localmente. Red no disponible, pendiente de sincronización.",
                "estado_tesis": "pendiente_sync"
            }), 202

    except Exception as e:
        # Error real de BD local — este SÍ merece rollback
        print(f"[ERROR CRÍTICO BD LOCAL] {e}")
        conn.execute('DELETE FROM tesis WHERE id = ?', (id_tesis,))
        conn.commit()
        print(f"[ROLLBACK] Tesis {id_tesis} eliminada por error de integridad local.")
        return jsonify({"status": "Fallo", "msg": f"Error de base de datos local: {e}"}), 500
    finally:
        conn.close()

@app.route('/api/reintentar', methods=['POST'])
def reintentar_sincronizacion():
    """Reintenta sincronizar todas las tesis pendientes con el coordinador central."""
    conn = get_db()
    pendientes = [dict(row) for row in conn.execute(
        "SELECT id, titulo, autor FROM tesis WHERE estado = 'pendiente_sync'"
    ).fetchall()]

    if not pendientes:
        conn.close()
        return jsonify({"msg": "No hay tesis pendientes de sincronización.", "sincronizadas": 0}), 200

    sincronizadas = 0
    errores = 0
    resultados = []

    for tesis in pendientes:
        try:
            respuesta = requests.post(URL_COORDINADOR, json=tesis, timeout=5)
            if respuesta.status_code == 201:
                conn.execute('UPDATE tesis SET estado = ? WHERE id = ?', ('sincronizado', tesis['id']))
                conn.commit()
                sincronizadas += 1
                resultados.append({"id": tesis['id'], "resultado": "sincronizado"})
                print(f"[RESYNC] Tesis {tesis['id']} sincronizada exitosamente.")
            else:
                errores += 1
                resultados.append({"id": tesis['id'], "resultado": "rechazado"})
                print(f"[RESYNC] Tesis {tesis['id']} rechazada por coordinador.")
        except requests.exceptions.RequestException:
            errores += 1
            resultados.append({"id": tesis['id'], "resultado": "error_red"})
            print(f"[RESYNC] Tesis {tesis['id']} falló: coordinador no disponible.")

    conn.close()
    return jsonify({
        "msg": f"Resincronización completada: {sincronizadas} éxitos, {errores} fallos.",
        "sincronizadas": sincronizadas,
        "errores": errores,
        "detalle": resultados
    }), 200

@app.route('/api/tesis', methods=['GET'])
def obtener_tesis():
    conn = get_db()
    tesis = [dict(row) for row in conn.execute(
        'SELECT id, titulo, autor, estado FROM tesis ORDER BY fecha_registro DESC'
    ).fetchall()]
    conn.close()
    return jsonify(tesis), 200

@app.route('/api/pendientes', methods=['GET'])
def obtener_pendientes():
    """Devuelve solo las tesis pendientes de sincronización."""
    conn = get_db()
    pendientes = [dict(row) for row in conn.execute(
        "SELECT id, titulo, autor FROM tesis WHERE estado = 'pendiente_sync'"
    ).fetchall()]
    conn.close()
    return jsonify({"cantidad": len(pendientes), "tesis": pendientes}), 200

# --- INICIALIZACIÓN ---
if __name__ == '__main__':
    init_db()
    print(f"[NODO SEDE A] BD SQLite en: {DB_PATH}")
    print("[NODO SEDE A] Escuchando en puerto 5001...")
    app.run(host='0.0.0.0', port=5001)
