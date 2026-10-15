import {expect, test} from 'vitest';
import {loginEditor} from '../src/login-editor.js';

function setup() {
  const root=document.createElement('div');
  root.innerHTML='<div id="fields"></div><textarea></textarea><input id="token"><input id="header"><input id="format"><div id="templates"></div><select></select><p></p>';
  document.body.append(root);
  const raw=root.querySelector('textarea');
  const editor=loginEditor({container:root.querySelector('#fields'),raw,token:root.querySelector('#token'),header:root.querySelector('#header'),format:root.querySelector('#format'),templates:root.querySelector('#templates'),tokenChoices:root.querySelector('select'),status:root.querySelector('p'),enabled:()=>true});
  return {root,raw,editor};
}
const op={requestSchema:{required:['username','password'],properties:{username:{type:'string'},password:{type:'string'},tenant:{type:'integer'}}},responseSchema:{properties:{id:{type:'string'},data:{properties:{access_token:{type:'string'}}}}}};
const fill=(root,name,value)=>{const input=root.querySelector(`[aria-label="ログイン：${name}"]`);input.value=value;input.dispatchEvent(new window.Event('input'));};

test('login fields create exact credentials and templates preserve them',()=>{
  const {root,raw,editor}=setup();editor.render(op);
  fill(root,'username','007');fill(root,'password','not-a-real-secret');
  expect(JSON.parse(raw.value)).toEqual({username:'007',password:'not-a-real-secret'});
  expect(root.querySelector('[aria-label="ログイン：password"]').type).toBe('password');
  root.querySelector('button').click();
  expect(root.querySelector('#token').value).toBe('id');
  expect(root.querySelector('#header').value).toBe('auth-key');
  expect(root.querySelector('#format').value).toBe('{token}');
  expect(JSON.parse(raw.value).password).toBe('not-a-real-secret');
  const picker=root.querySelector('select');picker.value='data.access_token';picker.dispatchEvent(new window.Event('change'));
  expect(root.querySelector('#token').value).toBe('data.access_token');
});
test('invalid typed input blocks stale data, correction restores exact types and JSON editing stays available',()=>{
  const {root,raw,editor}=setup();raw.value='{"username":"007","password":"fixture","tenant":7}';editor.render(op);
  fill(root,'tenant','abc');
  expect(raw.validity.valid).toBe(false);
  expect(root.querySelector('[aria-label="ログイン：tenant"]').getAttribute('aria-invalid')).toBe('true');
  fill(root,'tenant','8');expect(raw.validity.valid).toBe(true);expect(JSON.parse(raw.value).tenant).toBe(8);
  raw.value='{"username":"new","password":"changed"}';raw.dispatchEvent(new window.Event('change'));
  expect(root.querySelector('[aria-label="ログイン：username"]').value).toBe('new');
  raw.value='{invalid';raw.dispatchEvent(new window.Event('change'));
  expect(raw.value).toBe('{invalid');expect(root.querySelector('p').textContent).toContain('JSONを確認');
});
test('editing one credential preserves unrelated null, objects and fields without schema',()=>{
  const {root,raw,editor}=setup();
  raw.value=JSON.stringify({username:'old',password:'fixture',extra:7,profile:{enabled:false},nullable:null});
  editor.render(op);fill(root,'username','new');
  expect(JSON.parse(raw.value)).toEqual({username:'new',password:'fixture',extra:7,profile:{enabled:false},nullable:null});
  fill(root,'extra','8');expect(JSON.parse(raw.value).extra).toBe(8);
});
