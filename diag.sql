\echo '--- conteos'
select 'ncr' t, count(*) from ncr
union all select 'section_version', count(*) from section_version
union all select 'analysis_run', count(*) from analysis_run
union all select 'audit_log', count(*) from audit_log
union all select 'document', count(*) from document
union all select 'fragment', count(*) from fragment
union all select 'app_user', count(*) from app_user
union all select 'user_scope', count(*) from user_scope;
\echo '--- NCR huerfanas (opened_by sin usuario)'
select count(*) as huerfanas from ncr n left join app_user u on u.id = n.opened_by where u.id is null;
\echo '--- NCR por planta y linea'
select plant_id, line_id, count(*) from ncr group by 1,2 order by 1,2;
\echo '--- lineas existentes'
select plant_id, line_id from line order by 1,2;
\echo '--- usuarios y alcances'
select u.username, u.role, string_agg(s.plant_id||'/'||s.line_id, ', ' order by s.plant_id, s.line_id) as alcance
from app_user u left join user_scope s on s.user_id = u.id group by 1,2 order by 1;
\echo '--- esquema para el seed de demo'
\d ncr
\dT+ ncr_status