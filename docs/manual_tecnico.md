# Manual Técnico — Repositorio Digital Distribuido de Trabajos de Grado (RDD-TG)
## Versión 3.0 — Sistema con Consistencia Eventual y Persistencia SQLite

---

## 1. Arquitectura del Sistema

El sistema se compone de **3 nodos** desplegados en servidores diferentes, comunicándose mediante API REST sobre HTTP:

```
┌─────────────────────────┐
│   CLIENTE WEB (Local)   │
│   Portátil Windows      │
│   Puerto: 8000          │
│   Rol: Interfaz         │
│   del estudiante        │
└────────┬────────────────┘
         │ HTTP POST/GET
         ▼
┌─────────────────────────┐         ┌──────────────────────────┐
│  NODO SEDE A (Srv e)    │  HTTP   │  COORDINADOR (Srv f)     │
│  IP: 144.217.240.21     │────────▶│  IP: 144.217.85.170      │
│  Puerto: 5001           │  POST   │  Puerto: 5000            │
│  Debian Linux           │◀────────│  Debian Linux            │
│  BD: SQLite (sede_a.db) │  201/500│  BD: SQLite              │
│  Rol: Nodo autónomo     │         │  (indice_global.db)      │
│  con cola de pendientes │         │  Rol: Indexador global   │
└─────────────────────────┘         └──────────────────────────┘
```

### Características distribuidas:
- **Cada nodo tiene su propia base de datos SQLite** (persistente en disco)
- **La Sede A opera de forma autónoma** — si el coordinador cae, las tesis se guardan localmente
- **Consistencia eventual** — las tesis pendientes se sincronizan cuando el coordinador vuelve
- **No hay punto único de fallo** — el coordinador es un indexador, no un requisito para operar

---

## 2. Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3 |
| Framework Web | Flask |
| Base de datos | SQLite 3 (incluido en Python) |
| Comunicación | API REST (HTTP/JSON) |
| Librería HTTP | requests |
| Frontend | HTML5 + Bootstrap 5 + Font Awesome |
| Servidores | Debian Linux (acceso SSH) |
| Cliente | Windows (portátil local) |

---

## 3. Patrón Saga con Consistencia Eventual

### Flujo de una transacción distribuida:

```
ESTUDIANTE → CLIENTE WEB → NODO SEDE A → COORDINADOR CENTRAL
                              │                    │
                              │ PASO 1: Guardar    │
                              │ en SQLite local     │
                              │ (SIEMPRE éxito)     │
                              │                    │
                              │ PASO 2: Sincronizar │
                              ├───── POST ─────────▶│
                              │                    │
                        ┌─────┤                    ├─────┐
                        │     │                    │     │
                   CASO A     │               CASO B     │
                   201 OK     │               500/Timeout│
                        │     │                    │     │
                        ▼     │                    ▼     │
                   Estado:    │              Estado:     │
                   "sincronizado"           "pendiente_sync"
                              │                    │
                              │    CASO B (después):│
                              │    POST /api/reintentar
                              ├───── POST ─────────▶│
                              │    Resincroniza     │
                              │    pendientes       │
                              │    → "sincronizado" │
```

### Diferencia con el sistema anterior:
| Aspecto | Versión anterior | Versión actual |
|---|---|---|
| Si coordinador cae | ROLLBACK: se borra la tesis | Se guarda con estado `pendiente_sync` |
| Persistencia | Diccionarios en memoria | SQLite en disco |
| Resincronización | No existía | Endpoint `/api/reintentar` |
| Autonomía de la sede | Dependía del coordinador | Opera 100% sin coordinador |

---

## 4. Código Fuente

### 4.1 Coordinador Central (`coordinador.py`)
**Se ejecuta en Servidor f (144.217.85.170:5000)**

```python
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/indexar', methods=['POST'])
def indexar_tesis():
    datos = request.json
    titulo_recibido = datos.get("titulo", "").strip().lower()

    if titulo_recibido == "provocar_fallo":
        print("\n[ALERTA CENTRAL] Simulando caída... Rechazando petición.")
        return jsonify({"error": "Base de datos central caída"}), 500

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
    tesis = [dict(row) for row in conn.execute(
        'SELECT id, titulo, autor FROM tesis ORDER BY fecha_indexacion DESC'
    ).fetchall()]
    conn.close()
    return jsonify(tesis), 200

@app.route('/api/estado', methods=['GET'])
def estado():
    return jsonify({"estado": "activo", "timestamp": datetime.now().isoformat()}), 200

if __name__ == '__main__':
    init_db()
    print(f"[COORDINADOR CENTRAL] BD SQLite en: {DB_PATH}")
    app.run(host='0.0.0.0', port=5000)
```

### 4.2 Nodo Sede A (`nodo_local.py`)
**Se ejecuta en Servidor e (144.217.240.21:5001)**

```python
import sqlite3
import os
from datetime import datetime
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sede_a.db')
URL_COORDINADOR = "http://144.217.85.170:5000/api/indexar"

def init_db():
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/publicar', methods=['POST'])
def publicar_tesis():
    tesis = request.json
    id_tesis = tesis["id"]
    titulo = tesis["titulo"]
    autor = tesis["autor"]

    conn = get_db()
    try:
        # PASO 1: Guardar SIEMPRE en SQLite local
        conn.execute(
            'INSERT OR REPLACE INTO tesis (id, titulo, autor, estado, fecha_registro) VALUES (?, ?, ?, ?, ?)',
            (id_tesis, titulo, autor, 'pendiente_sync', datetime.now().isoformat())
        )
        conn.commit()
        print(f"\n[ÉXITO LOCAL] Tesis {id_tesis} guardada en SQLite de Sede A.")

        # PASO 2: Intentar sincronizar con coordinador
        try:
            print("[INTENTO] Contactando al servidor coordinador central...")
            respuesta = requests.post(URL_COORDINADOR, json=tesis, timeout=5)

            if respuesta.status_code == 201:
                conn.execute('UPDATE tesis SET estado = ? WHERE id = ?', ('sincronizado', id_tesis))
                conn.commit()
                print("[ÉXITO DISTRIBUIDO] Estado: sincronizado.")
                return jsonify({
                    "status": "Éxito",
                    "msg": "Sincronización global completada",
                    "estado_tesis": "sincronizado"
                }), 200
            else:
                print(f"[COORDINADOR RECHAZÓ] Tesis queda pendiente de sync.")
                return jsonify({
                    "status": "Pendiente",
                    "msg": "Tesis guardada localmente. Coordinador no disponible, pendiente de sincronización.",
                    "estado_tesis": "pendiente_sync"
                }), 202

        except requests.exceptions.RequestException as e:
            print(f"[FALLO RED] Tesis {id_tesis} guardada localmente. Pendiente de sincronización.")
            return jsonify({
                "status": "Pendiente",
                "msg": "Tesis guardada localmente. Red no disponible, pendiente de sincronización.",
                "estado_tesis": "pendiente_sync"
            }), 202

    except Exception as e:
        conn.execute('DELETE FROM tesis WHERE id = ?', (id_tesis,))
        conn.commit()
        print(f"[ROLLBACK] Tesis {id_tesis} eliminada por error de integridad local.")
        return jsonify({"status": "Fallo", "msg": f"Error de base de datos local: {e}"}), 500
    finally:
        conn.close()

@app.route('/api/reintentar', methods=['POST'])
def reintentar_sincronizacion():
    conn = get_db()
    pendientes = [dict(row) for row in conn.execute(
        "SELECT id, titulo, autor FROM tesis WHERE estado = 'pendiente_sync'"
    ).fetchall()]

    if not pendientes:
        conn.close()
        return jsonify({"msg": "No hay tesis pendientes.", "sincronizadas": 0}), 200

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
        except requests.exceptions.RequestException:
            errores += 1
            resultados.append({"id": tesis['id'], "resultado": "error_red"})

    conn.close()
    return jsonify({
        "msg": f"Resincronización: {sincronizadas} éxitos, {errores} fallos.",
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
    conn = get_db()
    pendientes = [dict(row) for row in conn.execute(
        "SELECT id, titulo, autor FROM tesis WHERE estado = 'pendiente_sync'"
    ).fetchall()]
    conn.close()
    return jsonify({"cantidad": len(pendientes), "tesis": pendientes}), 200

if __name__ == '__main__':
    init_db()
    print(f"[NODO SEDE A] BD SQLite en: {DB_PATH}")
    app.run(host='0.0.0.0', port=5001)
```

### 4.3 Cliente Web (`cliente_web.py`)
**Se ejecuta en el portátil local (Windows, puerto 8000)**

```python
from flask import Flask, render_template, request, url_for, jsonify
import requests

app = Flask(__name__)

URL_NODO = "http://144.217.240.21:5001"
URL_CENTRAL = "http://144.217.85.170:5000"

@app.route('/')
def home():
    tesis_local = []
    pendientes = 0
    try:
        r_local = requests.get(f"{URL_NODO}/api/tesis", timeout=3)
        if r_local.status_code == 200:
            tesis_local = r_local.json()
            pendientes = sum(1 for t in tesis_local if t.get('estado') == 'pendiente_sync')
    except:
        pass
    return render_template('index.html', local=tesis_local, pendientes=pendientes)

@app.route('/dashboard')
def dashboard():
    tesis_local, tesis_global = [], []
    estado_local, estado_global = 'Offline', 'Offline'
    pendientes = 0
    try:
        r_local = requests.get(f"{URL_NODO}/api/tesis", timeout=3)
        if r_local.status_code == 200:
            tesis_local = r_local.json()
            estado_local = 'Online'
            pendientes = sum(1 for t in tesis_local if t.get('estado') == 'pendiente_sync')
    except:
        pass
    try:
        r_global = requests.get(f"{URL_CENTRAL}/api/tesis", timeout=3)
        if r_global.status_code == 200:
            tesis_global = r_global.json()
            estado_global = 'Online'
    except:
        pass
    return render_template('dashboard.html',
                           local=tesis_local, global_db=tesis_global,
                           estado_local=estado_local, estado_global=estado_global,
                           pendientes=pendientes)

@app.route('/enviar', methods=['POST'])
def enviar():
    datos = {"id": request.form['id'], "titulo": request.form['titulo'], "autor": request.form['autor']}
    try:
        r = requests.post(f"{URL_NODO}/api/publicar", json=datos, timeout=10)
        data = r.json()
        if r.status_code == 200:
            return jsonify({"estado": "exito", "mensaje": data['msg']})
        elif r.status_code == 202:
            return jsonify({"estado": "pendiente", "mensaje": data['msg']})
        else:
            return jsonify({"estado": "fallo", "mensaje": data['msg']})
    except requests.exceptions.RequestException:
        return jsonify({"estado": "error", "mensaje": "La Sede A no responde."})

@app.route('/reintentar', methods=['POST'])
def reintentar():
    try:
        r = requests.post(f"{URL_NODO}/api/reintentar", timeout=15)
        if r.status_code == 200:
            data = r.json()
            return jsonify({
                "estado": "exito",
                "mensaje": data['msg'],
                "sincronizadas": data.get('sincronizadas', 0),
                "errores": data.get('errores', 0),
                "detalle": data.get('detalle', [])
            })
        else:
            return jsonify({"estado": "fallo", "mensaje": "Error en resincronización."})
    except requests.exceptions.RequestException:
        return jsonify({"estado": "error", "mensaje": "La Sede A no responde."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
```

---

## 5. Instrucciones de Ejecución

### 5.1 En Servidor f (Coordinador Central)
```bash
ssh f
cd ~/demo_transaccion
source venv/bin/activate
python coordinador.py
```
Salida esperada:
```
[INIT] Datos por defecto insertados en el índice global.
[COORDINADOR CENTRAL] BD SQLite en: /root/demo_transaccion/indice_global.db
[COORDINADOR CENTRAL] Escuchando en puerto 5000...
```

### 5.2 En Servidor e (Nodo Sede A)
```bash
ssh e
cd ~/demo_transaccion
source venv/bin/activate
python nodo_local.py
```
Salida esperada:
```
[INIT] Datos por defecto insertados en Sede A.
[NODO SEDE A] BD SQLite en: /root/demo_transaccion/sede_a.db
[NODO SEDE A] Escuchando en puerto 5001...
```

### 5.3 En Portátil Local (Cliente)
```bash
cd ~/demo_visual
source venv/bin/activate  # o venv\Scripts\activate en Windows
python cliente_web.py
```
Abrir en navegador: `http://localhost:8000`

---

## 6. Escenarios de Prueba

### Escenario 1: Publicación exitosa (Coordinador activo)

1. Llenar el formulario con datos normales:
   - ID: `UD-2026-010`
   - Título: `Inteligencia Artificial Aplicada`
   - Autor: `María López`
2. Clic en "Sincronizar con Nodos"

**Resultado esperado:**
- Consola muestra: `COMMIT DISTRIBUIDO: Sincronización global completada`
- Badge en la lista: ✅ verde (sincronizado)
- La tesis aparece tanto en Sede A como en el Índice Global del dashboard
- Terminal del servidor e: `[ÉXITO DISTRIBUIDO] Estado: sincronizado`
- Terminal del servidor f: `[NUEVO INGRESO] Tesis 'Inteligencia Artificial Aplicada' indexada globalmente`

### Escenario 2: Fallo del coordinador (Consistencia Eventual)

1. Llenar el formulario:
   - ID: `UD-2026-011`
   - Título: `provocar_fallo`
   - Autor: `Test`
2. Clic en "Sincronizar con Nodos"

**Resultado esperado:**
- Consola muestra: `CONSISTENCIA EVENTUAL: Tesis guardada localmente...`
- Badge en la lista: ⏳ amarillo (pendiente)
- La tesis **SÍ aparece** en Sede A (guardada en SQLite)
- La tesis **NO aparece** en el Índice Global
- Terminal del servidor e: `[COORDINADOR RECHAZÓ] Tesis queda pendiente de sync`
- Se muestra alerta: "X tesis pendientes de sincronización"

### Escenario 3: Resincronización

1. Después del Escenario 2, ir al Dashboard o ver la alerta
2. Clic en "Reintentar Sincronización" o "Resincronizar"

**Resultado esperado (si el coordinador ya está activo):**
- Consola: `→ UD-2026-011: SINCRONIZADO ✅`
- Badge cambia de ⏳ amarillo a ✅ verde
- La tesis ahora aparece en ambos: Sede A e Índice Global

**Nota:** Para que la resincronización funcione con la tesis de prueba "provocar_fallo", primero debe cambiar el título en la base de datos o publicar una nueva tesis con título diferente, ya que el coordinador siempre rechaza ese título específico.

### Escenario 4: Persistencia de datos

1. Publicar una tesis exitosamente
2. Detener los servidores (Ctrl+C)
3. Reiniciar los servidores
4. Verificar que la tesis sigue visible

**Resultado esperado:** Los datos persisten porque están en archivos SQLite en disco, no en memoria.

---

## 7. Estructura del Proyecto

```
repoDigitalDistribuidoTrabajosGrado/
├── nodo_coordinador/           ← Servidor f (144.217.85.170:5000)
│   ├── coordinador.py
│   └── indice_global.db       ← (se crea automáticamente)
├── nodo_sede_a/                ← Servidor e (144.217.240.21:5001)
│   ├── nodo_local.py
│   └── sede_a.db              ← (se crea automáticamente)
├── cliente_web/                ← Portátil local (localhost:8000)
│   ├── cliente_web.py
│   ├── static/
│   │   └── Escudo_UD.svg.png
│   └── templates/
│       ├── index.html
│       └── dashboard.html
└── docs/
    ├── manual_tecnico.md       ← Este archivo
    └── TGS trabajo final.pdf
```

---

## 8. Endpoints API

### Coordinador Central (Servidor f — Puerto 5000)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/indexar` | Indexa una tesis en el índice global |
| GET | `/api/tesis` | Lista todas las tesis del índice global |
| GET | `/api/estado` | Health check del coordinador |

### Nodo Sede A (Servidor e — Puerto 5001)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/publicar` | Publica una tesis (guarda local + intenta sincronizar) |
| GET | `/api/tesis` | Lista todas las tesis locales con su estado |
| GET | `/api/pendientes` | Lista solo las tesis pendientes de sincronización |
| POST | `/api/reintentar` | Resincroniza todas las tesis pendientes con el coordinador |

### Cliente Web (Portátil — Puerto 8000)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Página principal (formulario + consola) |
| GET | `/dashboard` | Monitor de nodos |
| POST | `/enviar` | Envía datos de tesis al nodo local |
| POST | `/reintentar` | Dispara resincronización de pendientes |

---

## 9. Relación con TGS

| Concepto TGS | Implementación en el sistema |
|---|---|
| **Homeostasis** | El Patrón Saga mantiene estabilidad: si el coordinador falla, la tesis se guarda localmente |
| **Neguentropía** | La cola de resincronización inyecta orden al reintegrar datos pendientes |
| **Entropía** | Los fallos de red aumentan el desorden (tesis desincronizadas) |
| **Sinergia** | El índice global es más que la suma de las BD locales |
| **Equifinalidad** | Múltiples caminos para que la tesis llegue al índice global (directo o vía reintento) |
| **Retroalimentación negativa** | El mecanismo de reintento corrige desviaciones del estado ideal (todo sincronizado) |
| **Sistema abierto** | API REST permite integración con sistemas externos |
| **Holismo** | El repositorio unificado trasciende las bases individuales de cada sede |
