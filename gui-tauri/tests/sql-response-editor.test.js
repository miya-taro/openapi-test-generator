import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import { buildDbScenario } from '../src/db-scenario-editor.js';
import { buildSqlResponseScenario, responsePaths } from '../src/sql-response-editor.js';
const spec = JSON.parse(fs.readFileSync('../examples/plan-get/openapi.json', 'utf8'));
const sample = JSON.parse(fs.readFileSync('../examples/plan-get/scenario.json', 'utf8')).scenarios[0];
const op = spec.paths['/plan/control/get'].get;
function form() { return {engine:'postgres', operation:{...op,method:'GET', responseSchema:op.responses['200'].content['application/json'].schema}, name:sample.name, requestBody:sample.request.body, sqlStatus:200, sqlCheck:JSON.parse(JSON.stringify(sample.db_sql_response_check))}; }
describe('SQL response editor', () => {
  it('roundtrips the nested plan contract', () => {
    const result=buildSqlResponseScenario(form());
    expect(result.db_sql_response_check).toEqual(sample.db_sql_response_check);
    expect(buildDbScenario({...form(), mode:'sql_response'}).db_sql_response_check).toEqual(sample.db_sql_response_check);
    expect(result.request.body).toEqual(sample.request.body);
    expect(responsePaths(form().operation.responseSchema).some((p)=>p.path==='plans[].controls[].correct_point.start.buy')).toBe(true);
  });
  it('rejects overlapping JSON mappings', () => {
    const value=form();value.sqlCheck.fields['plans[].controls[].correct_point.start.buy']='buy';
    expect(()=>buildSqlResponseScenario(value)).toThrow('同時');
  });
  it.each(['DELETE FROM h_plan','SELECT 1; SELECT 2'])('rejects non-query %s', (sql) => {
    const value=form();value.sqlCheck.sql=sql;expect(()=>buildSqlResponseScenario(value)).toThrow();
  });
  it('requires PostgreSQL GET and success status', () => {
    for (const change of [{engine:'influxdb'},{sqlStatus:500},{operation:{method:'POST'}}]) expect(()=>buildSqlResponseScenario({...form(),...change})).toThrow();
  });
});
