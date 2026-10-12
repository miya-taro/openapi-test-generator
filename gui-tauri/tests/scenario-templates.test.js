import { expect, test } from 'vitest';
import { copyScenario, makeVariants } from '../src/scenario-templates.js';
const source = () => ({name:'保存',request:{operationId:'set',body:{type:1}},response_check:{expect:{status:200,empty_body:true}},db_insert_check:{table:'sample',columns:{type:{kind:'request',path:'type'}}}});
const field = {source:'body',name:'type',required:false};

test('copy isolates request and mapping and does not reuse review identity',()=>{
  const original=source();original.id='old';
  const copy=copyScenario(original,'複製');
  copy.request.body.type=2;copy.db_insert_check.columns.type.path='other';
  expect(original.request.body.type).toBe(1);
  expect(original.db_insert_check.columns.type.path).toBe('type');
  expect(copy.id).not.toBe(original.id);
});
test('explicit values and omission remain distinct with unique ids',()=>{
  const original=source();
  const variants=makeVariants(original,field,[0,false,null],true,200,false);
  expect(variants.map(v=>v.request.body)).toEqual([{type:0},{type:false},{type:null},{}]);
  expect(new Set(variants.map(v=>v.id)).size).toBe(4);
  expect(original.request.body).toEqual({type:1});
});
test('negative variant requires explicit unchanged scope and removes success assertions',()=>{
  expect(()=>makeVariants(source(),field,[3],false,400,false)).toThrow();
  const scope={table:'sample',columns:['type'],where:{}};
  const [result]=makeVariants(source(),field,[3],false,400,true,scope);
  expect(result.db_insert_check).toBeUndefined();
  expect(result.response_check).toEqual({expect:{status:400}});
  expect(result.db_unchanged).toEqual([scope]);
});
test('cannot silently turn Influx guards into PostgreSQL guards',()=>{
  const original={...source(),influx_mutation:{}};
  expect(()=>makeVariants(original,field,[3],false,400,true,{table:'sample',columns:['type']})).toThrow(/InfluxDB/);
});
test('array input cannot silently lose named property on serialization',()=>{
  const original=source();original.request.body=[];
  expect(()=>makeVariants(original,field,[1],false,200,false)).toThrow(/オブジェクト/);
});
