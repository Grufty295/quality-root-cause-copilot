"""NCRs de demo para JRZ2 por la API real. Requiere haber corrido el seed con los usuarios JRZ2."""
import json, urllib.request, http.cookiejar

BASE = "http://localhost:8000"
NCRS = [
 ("u-insp-jrz2", 1, "B3-FDH-0451", "KES", "Inspección final en JRZ2: 3 arneses B3-FDH-0451 con terminal retraída en el conector C11 durante la prueba de jalón. Detectado al cierre del turno 1."),
 ("u-insp-jrz2", 2, "A7-DRH-2210-M", "NOR", "Prueba eléctrica en JRZ2: 2 arneses A7-DRH-2210-M con circuito abierto intermitente en el ramal de bocina. Falla al flexionar el ramal; en estático pasan."),
 ("u-insp-jrz2", 3, "B3-FDH-0451", "KES", "Auditoría de producto en JRZ2: 1 arnés B3-FDH-0451 con aislante dañado cerca del sello del conector C03, posible daño durante el ruteo en tablero."),
 ("u-ingcal-jrz2", 2, "A7-DRH-2210-M", "NOR", "Reclamo de Norvane Motors recibido en JRZ2: 4 arneses A7-DRH-2210-M con altura de crimpado fuera de especificación en la terminal del circuito de ventana."),
 ("u-ingcal-jrz2", 1, "B3-FDH-0451", "KES", "Rechazo en recibo de cliente Kestrel Modules en JRZ2: 2 arneses B3-FDH-0451 con etiqueta de trazabilidad ilegible; se solicita contención y verificación de lote."),
]
def login(u):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(path, body):
        r = urllib.request.Request(BASE+path, json.dumps(body).encode(), {"Content-Type":"application/json","Origin":"http://localhost:3000"})
        return json.load(op.open(r))
    call("/auth/demo-login", {"username": u}); return call
for i,(u,shift,part,cust,desc) in enumerate(NCRS,1):
    try:
        o = login(u)("/ncrs", {"plant_id":"JRZ2","line_id":"L1","shift":shift,"description":desc,"part_number":part,"customer_id":cust})
        print(i,"OK",o["code"],o["detected_level"],o["status"])
    except Exception as e:
        print(i,"FALLO",getattr(e,"read",lambda:b"")()[:300] or e)