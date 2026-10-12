// Copy settings without reusing IDs/reviews; require explicit outcomes for variants.
const clone = (value) => JSON.parse(JSON.stringify(value));
export function copyScenario(source, name, operationId = source.request.operationId) {
  if (!name.trim() || !operationId) throw new Error('試験名とAPI操作が必要です');
  const result = clone(source);
  result.id = `ui-${globalThis.crypto.randomUUID()}`;
  result.name = name.trim(); result.request.operationId = operationId;
  return result;
}
export function variantFields(operation) {
  const body = Object.entries(operation?.requestSchema?.properties || {}).map(([name, schema]) => ({source:'body', name, schema, required:(operation.requestSchema.required || []).includes(name)}));
  return [...body, ...(operation?.parameters || []).filter((p) => ['query','path'].includes(p.in)).map((p) => ({source:p.in,name:p.name,schema:p.schema || {},required:p.required}))];
}
export function makeVariants(source, field, values, omit, status, unchanged, scope) {
  if (!Array.isArray(values) || values.length + Number(omit) > 20 || (!values.length && !omit)) throw new Error('候補値はJSON配列で1〜20件を指定してください');
  if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error('期待statusを指定してください');
  if (omit && field.required) throw new Error('必須項目の省略は異常系の設定から作成してください');
  if (status < 400 && source.response_check?.expect?.status >= 400) throw new Error('正常系の基準ケースから候補を作成してください');
  if (status >= 400 && source.given?.length) throw new Error('事前データ付きの異常系は複製後に個別設定してください');
  if (status >= 400 && (source.influx_mutation || source.db_check?.engine === 'influxdb' || source.db_response_check?.engine === 'influxdb' || source.db_unchanged?.some((check) => check.engine && check.engine !== 'postgres'))) throw new Error('InfluxDBの異常系は複製後に時間範囲を含めて個別設定してください');
  const key = {body:'body',query:'query_params',path:'path_params'}[field.source];
  if (!key || !field.name || ['__proto__','prototype','constructor'].includes(field.name)) throw new Error('対象項目が不正です');
  if (status >= 400 && !unchanged) throw new Error('異常系はDB変更なしの確認範囲を指定してください');
  if (status >= 400 && (!scope || !scope.table || !scope.columns?.length)) throw new Error('DB変更なしのテーブルと列を指定してください');
  return [...values.map((value) => ({value})), ...(omit ? [{omit:true}] : [])].map((choice, index) => {
    const result = copyScenario(source, `${source.name} / ${field.source}.${field.name}=${choice.omit ? '省略' : JSON.stringify(choice.value)} (${index+1})`);
    result.request[key] ??= {};
    if (typeof result.request[key] !== 'object' || Array.isArray(result.request[key])) throw new Error('条件別ケースの入力はオブジェクトが必要です');
    if (choice.omit) delete result.request[key][field.name]; else result.request[key][field.name] = clone(choice.value);
    if (status >= 400) {
      for (const property of ['db_insert_check','db_response_check','db_sql_response_check','influx_mutation','db_check','cleanup','given']) delete result[property];
      result.db_unchanged = [clone(scope)]; result.response_check = {expect:{status}};
    } else {
      result.response_check ||= {expect:{}}; result.response_check.expect ||= {}; result.response_check.expect.status = status;
    }
    return result;
  });
}

export function templateControls(source, operations, onAppend, onReplace, onError) {
  const root = document.createElement('details'); root.className = 'scenario-template';
  const node = (tag, text='') => { const el=document.createElement(tag);el.textContent=text;return el; };
  root.append(node('summary','編集・複製・条件別ケースを作成'));
  const field = (label, value='', multiline=false) => {
    const wrap=node('label',label), el=node(multiline?'textarea':'input');
    if (!multiline) el.type='text'; else el.rows=6;
    el.value=value; el.setAttribute('aria-label',label);wrap.append(el);root.append(wrap);return el;
  };
  const name=field('試験名',source.name);
  const op=node('select');op.setAttribute('aria-label','複製先API');
  for (const operation of operations) { const option=node('option',`${operation.method} ${operation.path}`);option.value=operation.operationId;op.append(option); }
  op.value=source.request.operationId;root.append(op);
  const request=field('送信設定（body・query_params・path_params）',JSON.stringify(source.request,null,2),true);
  root.append(node('p','保存日時・主キーの重複に注意してください。DB対応・SQL・固定期待値は引き継ぎます。別APIへの複製では対応関係を必ず見直してください。保存しただけでは実行されません。'));
  const button=(label,action) => { const el=node('button',label);el.type='button';el.className='secondary';el.onclick=()=>{try{action();}catch(error){onError(error.message);}};root.append(el); };
  const edited=()=>{ const result=copyScenario(source,name.value,op.value);const req=JSON.parse(request.value); if(!req || Array.isArray(req) || typeof req!=='object') throw new Error('送信設定はオブジェクトで入力してください'); result.request={...req,operationId:op.value};return result; };
  button('変更を適用',()=>onReplace(edited()));
  button('この設定を複製',()=>{const result=edited();result.name+='（複製）';onAppend([result]);});
  const advanced=node('details');advanced.append(node('summary','DB対応・期待結果も編集する'));
  const raw=node('textarea');raw.rows=10;raw.value=JSON.stringify(source,null,2);raw.setAttribute('aria-label','対応設定全体（JSON）');advanced.append(raw);
  const apply=node('button','全体の変更を適用');apply.type='button';apply.className='secondary';apply.onclick=()=>{try{const value=JSON.parse(raw.value);if(!value?.request?.operationId || !value.name)throw new Error('試験名とrequest.operationIdが必要です');value.id=`ui-${globalThis.crypto.randomUUID()}`;onReplace(value);}catch(error){onError(error.message);}};advanced.append(apply);root.append(advanced);
  root.append(node('h4','条件別ケース候補（1項目ずつ）'));
  const selector=node('select');selector.setAttribute('aria-label','条件を変える項目');root.append(selector);
  let fields=[];
  const values=field('候補値（JSON配列）','[]');
  const omitLabel=node('label','省略ケースも追加');const omit=node('input');omit.type='checkbox';omit.setAttribute('aria-label','省略ケースも追加');omitLabel.append(omit);root.append(omitLabel);
  const status=field('候補の期待status',String(source.response_check?.expect?.status || ''));
  const guardLabel=node('label','異常系ではDB変更なしを確認');const guard=node('input');guard.type='checkbox';guard.setAttribute('aria-label','異常系ではDB変更なしを確認');guardLabel.append(guard);root.append(guardLabel);
  const table=field('DB変更なしのテーブル',source.db_insert_check?.table || source.db_unchanged?.[0]?.table || '');
  const columns=field('DB変更なしの列（カンマ区切り）',Object.keys(source.db_insert_check?.columns || {}).join(',') || source.db_unchanged?.[0]?.columns?.join(',') || '');
  const reset=()=>{
    fields=variantFields(operations.find((item)=>item.operationId===op.value));selector.replaceChildren();
    fields.forEach((entry,index)=>{const option=node('option',`${entry.source}.${entry.name}`);option.value=String(index);selector.append(option);});suggest();
  };
  const suggest=()=>{const entry=fields[Number(selector.value)];values.value=JSON.stringify(entry?.schema.enum || (entry?.schema.type==='boolean'?[true,false]:[]));omit.checked=false;omit.disabled=!!entry?.required;};
  selector.onchange=suggest;op.onchange=reset;reset();
  button('条件別ケースを追加',()=>{const base=edited();onAppend(makeVariants(base,fields[Number(selector.value)] || {},JSON.parse(values.value),omit.checked,Number(status.value),guard.checked,{table:table.value.trim(),columns:columns.value.split(',').map((v)=>v.trim()).filter(Boolean),where:{}}));});
  return root;
}
