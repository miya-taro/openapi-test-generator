import {expect, test, vi} from 'vitest';
import {attachFlow, flowControls, newApiScenario} from '../src/api-flow-editor.js';
const operations = [{operationId:'get',method:'GET',path:'/jobs/{id}',parameters:[{name:'id',in:'path',schema:{type:'integer'}}],requestSchema:{type:'object',properties:{user:{type:'string'}}}}, {operationId:'create',method:'POST',path:'/jobs'}];
const source = () => ({...newApiScenario(operations[0],'完了確認'),request:{operationId:'get',body:{user:'007'},path_params:{id:7}},response_check:{expect:{status:200,body:{value:42}}},db_check:{engine:'postgres',table:'jobs',where:{id:7},expect:{value:42}}});
const findButton = (root,text) => [...root.querySelectorAll('button')].find(b => b.textContent === text);
const findInput = (root,text) => [...root.querySelectorAll('label')].find(l => l.firstChild?.textContent === text)?.querySelector('input');

test('save/reopen preserves all DB checks and string values without handwritten code', () => {
  const save = vi.fn(); const error = vi.fn(); const original = source();
  original.api_flow = {before:[{name:'create',request:{operationId:'create',body:{enabled:false,zero:0,empty:null}},expect_status:200}],cleanup:[]};
  original.request.path_params.id = '{{steps.create.id}}';
  original.poll = {path:'state',equals:'done',timeout:30,interval:1};
  const panel = flowControls(original,operations,save,error); document.body.append(panel);
  findButton(panel,'連続実行の設定を反映').click();
  expect(error).not.toHaveBeenCalled();
  const updated = save.mock.calls[0][0];
  expect(updated.request).toEqual({...original.request,query_params:{}});
  expect(updated.api_flow.before[0].request.body).toEqual({enabled:false,zero:0,empty:null});
  expect(updated.db_check).toEqual(original.db_check);
  expect(updated.poll).toEqual(original.poll);
  expect(updated.response_check).toEqual(original.response_check);
});
test('operator can set the response and enable bounded polling', () => {
  const save=vi.fn(), error=vi.fn();
  const panel=flowControls(source(),operations,save,error); document.body.append(panel);
  findInput(panel,'本試験の期待HTTPステータス').value='202';
  const enabled=findInput(panel,'完了するまで繰り返し確認する'); enabled.click();
  findInput(panel,'レスポンス項目（例 status）').value='state';
  findInput(panel,'完了時の値（例 done）').value='done';
  findButton(panel,'連続実行の設定を反映').click();
  expect(error).not.toHaveBeenCalled();
  expect(save.mock.calls[0][0].poll).toEqual({path:'state',equals:'done',timeout:30,interval:1});
  expect(save.mock.calls[0][0].response_check.expect.status).toBe(202);
});
test('duplicate names cannot be silently overwritten', () => {
  const step={name:'create',request:{operationId:'create'},expect_status:200};
  expect(()=>attachFlow(source(),[step,step],[],undefined)).toThrow(/重複/);
  expect(()=>attachFlow(source(),[{...step,name:'result'}],[],undefined)).toThrow(/予約/);
});
