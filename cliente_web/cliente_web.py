from flask import Flask, render_template, request, url_for, jsonify
import requests

app = Flask(__name__)

URL_NODO = "http://144.217.240.21:5001"
URL_CENTRAL = "http://144.217.85.170:5000"

@app.route('/')
def home():
    tesis_local = []
    pendientes = 0
    # Consultamos al Nodo Local para listar en la página de inicio
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
            # Tesis guardada localmente, pendiente de sincronización
            return jsonify({"estado": "pendiente", "mensaje": data['msg']})
        else:
            return jsonify({"estado": "fallo", "mensaje": data['msg']})
    except requests.exceptions.RequestException:
        return jsonify({"estado": "error", "mensaje": "La Sede A no responde al intento de conexión."})

@app.route('/reintentar', methods=['POST'])
def reintentar():
    """Dispara la resincronización de tesis pendientes en el nodo local."""
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
            return jsonify({"estado": "fallo", "mensaje": "El nodo no pudo procesar la resincronización."})
    except requests.exceptions.RequestException:
        return jsonify({"estado": "error", "mensaje": "La Sede A no responde."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
