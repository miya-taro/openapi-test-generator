import {test, expect, vi} from 'vitest';
import {buildRuleCases, rowValues} from '../src/rule-cases.js';
import {ruleControls} from '../src/rule-controls.js';
const operation = {operationId:'read', method:'GET', requestSchema:{type:'object', required:['start','end'], properties:{
  start:{type:'string'},end:{type:'string'},site:{type:'integer'},location:{type:'string'},correct:{type:'boolean'},type:{type:'integer',enum:[1,2]}}}};
const source = {name:'取得',request:{operationId:'read',body:{start:'2026-01-01T00:00:00Z',end:'2026-01-02T00:00:00Z',site:1}},response_check:{expect:{status:200}}};
const form = {kind:'boundary',status:200,engine:'postgres',table:'measure',scope:[{name:'site',type:'integer',value:'1'}],seed:[],markerColumn:'value',timeColumn:'datetime',responseArray:'data',responseField:'value',stepMs:1000,includeStart:true,includeEnd:false,startField:{source:'body',name:'start'},endField:{source:'body',name:'end'}};

test('six independent boundaries preserve the base and exact inclusion expectations',()=>{
  const cases=buildRuleCases(source,operation,form);
  expect(cases).toHaveLength(6);
  expect(cases.map(x=>x.response_check.expect.collections[0].rows.length)).toEqual([1,2,2,2,1,1]);
  expect(cases.every(x=>x.test_fixture.rows.length===2)).toBe(true);
  expect(source).not.toHaveProperty('test_fixture');
  expect(cases[0].test_fixture.rows[1].datetime).toBe('2025-12-31T23:59:59.000Z');
  cases[0].request.body.site=99;expect(cases[1].request.body.site).toBe(1);
  expect(()=>buildRuleCases(source,operation,{...form,startField:undefined})).toThrow('項目');
});
test('priority generates every pair both orders and the whole ranked set',()=>{
  const cases=buildRuleCases(source,operation,{...form,kind:'priority',candidates:[3,2,1].map(v=>[{name:'rank',type:'integer',value:v}])});
  expect(cases).toHaveLength(8);
  expect(cases[0].test_fixture.rows.map(x=>x.rank)).toEqual([3,2]);
  expect(cases[1].test_fixture.rows.map(x=>x.rank)).toEqual([2,3]);
  expect(cases.slice(-2).map(x=>x.response_check.expect.collections[0].rows)).toEqual([[{value:1}],[{value:1}]]);
});
test('empty outcome is explicit, with no inherited success DB check',()=>{
  const cases=buildRuleCases({...source,db_response_check:{table:'measure'}},operation,{...form,kind:'empty',status:400,responseArray:'',emptyValues:[{path:'error',value:'"not-found"'}]});
  expect(cases[0].test_fixture.rows).toEqual([]);
  expect(cases[0]).not.toHaveProperty('db_response_check');
  expect(cases[0].response_check.expect).toEqual({status:400,values:[{path:'error',source:'fixed',value:'not-found'}]});
});
test('combinations generate absent and present cases and guard invalid requests',()=>{
  const combos={kind:'combinations',status:200,invalidStatus:400,fields:[{source:'body',name:'site',values:[1],omit:true},{source:'body',name:'location',values:['a'],omit:true}],relations:[{a:0,b:1,kind:'atLeastOne'}],unchanged:[{table:'measure',columns:['site'],where:{}}]};
  const cases=buildRuleCases(source,operation,combos);
  expect(cases.map(x=>x.response_check.expect.status)).toEqual([200,200,200,400]);
  expect(cases[3].db_unchanged).toEqual(combos.unchanged);
  expect(()=>buildRuleCases(source,operation,{...combos,unchanged:[]})).toThrow('DB変更なし');
  expect(()=>buildRuleCases(source,operation,{...combos,fields:[{source:'body',name:'type',values:[3]}]})).toThrow('enum');
  expect(()=>buildRuleCases(source,operation,{...combos,fields:[{source:'body',name:'site',values:Array.from({length:65},(_,i)=>i)}]})).toThrow('64');
});
test('typed cells reject invalid numbers and conflicting scope',()=>{
  expect(()=>rowValues([{name:'a',type:'integer',value:'1.5'}])).toThrow();
  expect(()=>buildRuleCases(source,operation,{...form,seed:[{name:'site',type:'integer',value:2}]})).toThrow('矛盾');
});
test('UI preview, edit invalidation, append and lazy initialization',()=>{
  const append=vi.fn(), error=vi.fn();
  const el=ruleControls({...source,rule_test:{settings:form}},operation,append,error);
  document.body.append(el);expect(el.querySelector('input')).toBeNull();
  el.open=true;el.dispatchEvent(new window.Event('toggle'));
  const button=name=>[...el.querySelectorAll('button')].find(x=>x.textContent===name);
  const preview=button('生成する試験を確認'), add=button('確認した試験を追加');
  expect(add.disabled).toBe(true);preview.click();expect(error).not.toHaveBeenCalled();expect(add.disabled).toBe(false);
  expect(el.querySelectorAll('.rule-preview li')).toHaveLength(6);
  const step=el.querySelector('[aria-label="境界の刻み幅（ミリ秒）"]');step.value='2000';step.dispatchEvent(new window.Event('input',{bubbles:true}));
  expect(add.disabled).toBe(true);preview.click();add.click();expect(append.mock.calls[0][0]).toHaveLength(6);
  el.remove();
});
