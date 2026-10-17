from app.modules.auth.models import CurrentUser
from app.agent.tools import QualityTools
import os, json, uuid
from datetime import datetime
from sqlalchemy import create_engine

jsonl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../evals/casos_calidad.jsonl'))
cases = []
with open(jsonl_path, encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        if r['caso_id'] in ('EV-07', 'EV-08', 'EV-10'):
            cases.append(r)

engine = create_engine(os.environ.get('DATABASE_URL') or 'postgresql+psycopg://app:devonlychangeme@localhost:5432/eightd')
out_lines = []

user = CurrentUser(id=uuid.UUID('00000000-0000-0000-0000-000000000001'), username='auditor', display_name='Auditor', role='ingeniero', scopes=['*'])

for c in cases:
    cid = c['caso_id']
    ncr = c['ncr']
    as_of_str = c.get('as_of') or ncr['fecha']
    as_of = datetime.fromisoformat(as_of_str).date()
    plant_id = 'JRZ1'
    line_id = ncr['linea']
    
    out_lines.append(f"# CASO: {cid} | Episodio: {c['episodio']} | as_of: {as_of} | Línea: {line_id}")
    out_lines.append(f"Descripción: {ncr['descripcion']}\n")
    
    with engine.connect() as conn:
        tools = QualityTools(conn=conn, user=user, retrieval=None, today=as_of, as_of=as_of)
        
        t5 = tools.defect_summary(line_id, None, None, 'parte')
        t6 = tools.defect_summary(line_id, None, None, 'lote_terminal')
        t7 = tools.maintenance_history(line_id, None, None)
        t8 = tools.applicator_wear(line_id, on=None)
        t9 = tools.crimp_summary(line_id, None, None)
        t11 = tools.material_lots(line_id, None, None)
        
        for name, tool_res in [('T5 (parte)', t5), ('T6 (lote_terminal)', t6), ('T7 (mantenimiento)', t7), ('T8 (desgaste)', t8), ('T9 (crimpado)', t9), ('T11 (lotes de material)', t11)]:
            out_lines.append(f"## {name}")
            out_lines.append(tool_res.text if hasattr(tool_res, 'text') else str(tool_res))
            out_lines.append("")

output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../audit/03-evidencia-ev07-08-10.md'))
with open(output_path, 'w', encoding='utf-8') as out_f:
    out_f.write('\n'.join(out_lines))
print(f"Generado {output_path} exitosamente.")
