WITH request AS (
  SELECT COALESCE(%(site_id)s::integer,
    (SELECT site_id FROM t_site WHERE location_id = %(location_id)s::text)) AS selected_site,
    %(start)s::timestamptz AS start_at, %(end)s::timestamptz AS end_at,
    %(correct)s::boolean AS selected_correct, %(type)s::text AS selected_type
), ranked AS (
  SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.datetime, p.use_id ORDER BY
    (p.correct OR p.force) DESC NULLS LAST,
    CASE WHEN p.fixed THEN CASE WHEN p.cpbs_type IS NOT NULL THEN 1000 + p.cpbs_type ELSE 500 END
         ELSE CASE WHEN p.cpbs_type IS NULL THEN 100 ELSE 0 END END DESC,
    p.created DESC) AS rn
  FROM h_plan p CROSS JOIN request r
  WHERE p.site_id = r.selected_site AND p.datetime >= r.start_at AND p.datetime < r.end_at
    AND (r.selected_correct IS NULL OR p.correct = r.selected_correct)
), preferred AS (
  SELECT COALESCE(r.selected_type,
    (SELECT use_id FROM ranked WHERE rn = 1 AND (fixed OR force) ORDER BY created DESC, use_id LIMIT 1),
    (SELECT param->'multiuse'->>'use_id' FROM h_setting WHERE site_id = r.selected_site
     AND setting_id = 2 ORDER BY datetime DESC LIMIT 1)) AS use_id
  FROM request r
)
SELECT p.site_id, %(start)s::text AS start_datetime, %(end)s::text AS end_datetime,
  to_char(p.datetime AT TIME ZONE 'Asia/Tokyo', 'YYYY-MM-DD') AS plan_date,
  p.profit, p.use_id, to_char(p.datetime AT TIME ZONE 'Asia/Tokyo', 'HH24:MI') AS control_time,
  p.correct, p.buy, p.sell, p.charge, p.discharge, p.soc, p.gen, p.suppression, p.correct_point
FROM ranked p CROSS JOIN preferred s WHERE p.rn = 1 AND p.use_id = s.use_id
ORDER BY p.datetime, p.use_id
