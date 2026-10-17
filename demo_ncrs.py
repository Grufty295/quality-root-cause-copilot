"""Crea NCRs de demo por la API real (clasifica confidencialidad). Solo casos dev EV-01..12."""
import json, urllib.request, http.cookiejar, itertools

BASE = "http://localhost:8000"
CUST = {"Norvane Motors": "NOR", "Kestrel Modules": "KES"}
USERS = ["u-insp-l1", "u-insp-l2", "u-ingcal-1"]
SHIFT = {"T1": 1, "T2": 2, "T3": 3}

def client(username):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def call(path, body):
        r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
            {"Content-Type": "application/json", "Origin": "http://localhost:3000"})
        return json.load(op.open(r))
    call("/auth/demo-login", {"username": username})
    return call

casos = []
with open("/workspace/evals/casos_calidad.jsonl", encoding="utf-8") as f:
    for line in itertools.islice(f, 12):   # solo dev
        casos.append(json.loads(line))

for c in casos:
    n = c["ncr"]
    linea = n["linea"].split(",")[0].strip()
    user = "u-insp-l1" if linea == "L1" else "u-insp-l2"
    body = {"plant_id": "JRZ1", "line_id": linea, "shift": SHIFT.get(n["turno"], 1),
            "description": n["descripcion"], "part_number": n["numero_parte"],
            "customer_id": CUST.get(n["cliente"])}
    try:
        out = client(user)("/ncrs", body)
        print(c["caso_id"], "OK", out["code"], out["detected_level"], out["status"])
    except Exception as e:
        print(c["caso_id"], "FALLO", getattr(e, "read", lambda: b"")()[:200] or e)