// Explicit rules -> ordinary reviewable scenarios. No database/name inference.
import { variantFields } from './scenario-templates.js';
const clone = (value) => JSON.parse(JSON.stringify(value));
const ident = /^[A-Za-z_][A-Za-z0-9_]*$/;
const forbidden = new Set(['__proto__', 'constructor', 'prototype']);
const ensure = (ok, message) => { if (!ok) throw new Error(message); };
const status = (value) => { const n = Number(value); ensure(Number.isInteger(n) && n >= 100 && n <= 599, '期待ステータスを指定してください'); return n; };

export function rowValues(entries) {
  const result = {};
  for (const entry of entries || []) {
    ensure(ident.test(entry.name) && !forbidden.has(entry.name) && !Object.hasOwn(result, entry.name), '列名を重複なしで指定してください');
    let value;
    if (entry.type === 'string') value = String(entry.value);
    else if (entry.type === 'null') value = null;
    else if (entry.type === 'boolean') { ensure(['true', 'false'].includes(String(entry.value)), '真偽値はtrueまたはfalseにしてください'); value = entry.value === true || entry.value === 'true'; }
    else if (['integer', 'float'].includes(entry.type)) {
      ensure(String(entry.value).trim() !== '', '数値を入力してください'); value = Number(entry.value);
      ensure(Number.isFinite(value) && (entry.type !== 'integer' || Number.isSafeInteger(value)), '有効な数値を入力してください');
    } else if (entry.type === 'json') value = JSON.parse(entry.value);
    else throw new Error('値の型を選択してください');
    result[entry.name] = value;
  }
  return result;
}

function instant(value) {
  ensure(typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?(?:Z|[+-]\d\d:\d\d)$/.test(value), '境界日時はタイムゾーン付き・ミリ秒までで指定してください');
  const [year, month, day, hour, minute, second] = value.match(/\d+/g).slice(0, 6).map(Number);
  ensure(month >= 1 && month <= 12 && day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate() && hour < 24 && minute < 60 && second < 60, '日時が不正です');
  const n = Date.parse(value); ensure(Number.isFinite(n), '日時が不正です'); return n;
}

function requestField(body, field) {
  ensure(field, 'リクエスト項目を選択してください');
  const key = {body: 'body', query: 'query_params', path: 'path_params'}[field.source];
  ensure(key && ident.test(field.name) && !forbidden.has(field.name), 'リクエスト項目を選択してください');
  body[key] ??= {};
  ensure(typeof body[key] === 'object' && !Array.isArray(body[key]), '基準リクエストはオブジェクトで設定してください');
  return [body[key], field.name];
}

export function buildRuleCases(source, operation, form) {
  ensure(source?.request?.operationId && operation?.operationId === source.request.operationId, '基準APIを選択してください');
  ensure(!source.given?.length && !source.cleanup && !source.influx_mutation, '既存の事前データ・片付け設定は共通ルールの検証データに移してから生成してください');
  const kind = form.kind;
  ensure(['boundary', 'combinations', 'priority', 'empty'].includes(kind), '試験ルールを選択してください');
  if (kind !== 'combinations') ensure(operation.method.toUpperCase() === 'GET', '期間境界・優先順位・0件の共通生成はGETで設定してください');
  const expectedStatus = status(form.status);
  if (kind !== 'empty') ensure(expectedStatus >= 200 && expectedStatus < 300, '正常系の期待ステータスを指定してください');
  const usingFixture = kind !== 'combinations' || form.useFixture;
  let fixture;
  if (usingFixture) {
    ensure(['postgres', 'influxdb'].includes(form.engine) && ident.test(form.table), '検証用DBとテーブル名を指定してください');
    const scope = rowValues(form.scope);
    ensure(Object.keys(scope).length && Object.values(scope).every(v => v !== null && typeof v !== 'object'), '既存データと分ける専用範囲を指定してください');
    if (form.engine === 'influxdb') ensure(Object.values(scope).every(v => typeof v === 'string' && v), 'InfluxDBの範囲は全タグを空でない文字列で指定してください');
    const seed = rowValues(form.seed);
    ensure(!Object.keys(scope).some(k => Object.hasOwn(seed, k) && seed[k] !== scope[k]), '検証行と専用範囲の値が矛盾しています');
    fixture = {engine: form.engine, table: form.table, scope, rows: [{...seed, ...scope}]};
    if (form.engine === 'influxdb') fixture.field_types = Object.fromEntries((form.seed || []).filter(x => x.name !== 'time' && !Object.hasOwn(scope, x.name)).map(x => [x.name, x.type]));
  }
  const result = [];
  const add = (condition, overrides = {}) => {
    const value = clone(source);
    delete value.id;
    delete value.test_fixture;
    delete value.rule_test;
    value.name = `${source.name} / ${condition}`;
    value.rule_test = {kind, condition, body_present: Object.hasOwn(source.request, 'body'), settings: clone(form)};
    value.response_check ??= {expect: {}};
    value.response_check.expect ??= {};
    if (source.rule_test) delete value.response_check.expect.collections;
    value.response_check.expect.status = expectedStatus;
    if (fixture) value.test_fixture = clone(fixture);
    Object.assign(value, overrides);
    result.push(value);
    ensure(result.length <= 64, '生成件数が64件を超えます。条件を分けてください（省略せず停止）');
    return value;
  };
  const collection = (markers) => ({path: form.responseArray, fields: [form.responseField], rows: markers.map(value => ({[form.responseField]: value}))});
  const markerReady = () => {
    ensure(ident.test(form.markerColumn) && !Object.hasOwn(fixture.scope, form.markerColumn), '照合用のDB列を専用範囲と別に指定してください');
    ensure(form.responseArray && form.responseField, '照合するレスポンス配列と項目を指定してください');
    if (fixture.engine === 'influxdb') fixture.field_types[form.markerColumn] = 'float';
  };
  const replaceChecks = (value) => {
    for (const key of ['db_check', 'db_insert_check', 'db_response_check', 'db_sql_response_check']) delete value[key];
    value.response_check = {expect: {status: expectedStatus}};
  };
  if (kind === 'boundary') {
    markerReady();
    ensure(ident.test(form.timeColumn) && form.timeColumn !== form.markerColumn && !Object.hasOwn(fixture.scope, form.timeColumn), '日時列を専用範囲・照合用列と別に指定してください');
    if (fixture.engine === 'influxdb') ensure(form.timeColumn === 'time', 'InfluxDBの日時列はtimeです');
    const request = clone(source.request), [startContainer, startKey] = requestField(request, form.startField), [endContainer, endKey] = requestField(request, form.endField);
    ensure(form.startField.source !== form.endField.source || startKey !== endKey, '開始と終了には異なる項目を指定してください');
    const start = instant(startContainer[startKey]), end = instant(endContainer[endKey]), step = Number(form.stepMs);
    ensure(Number.isSafeInteger(step) && step > 0 && end-start > 4*step, '正の刻み幅と、その4倍より長い期間を指定してください');
    ensure(typeof form.includeStart === 'boolean' && typeof form.includeEnd === 'boolean', '境界を含むか指定してください');
    const probes = [['開始の直前', start-step, false], ['開始と一致', start, form.includeStart], ['開始の直後', start+step, true],
      ['終了の直前', end-step, true], ['終了と一致', end, form.includeEnd], ['終了の直後', end+step, false]];
    for (const [name, time, included] of probes) {
      const value = add(`期間境界：${name}（${included ? '含む' : '含まない'}）`);
      value.test_fixture.rows = [
        {...fixture.rows[0], [form.timeColumn]: new Date(Math.floor((start+end)/2)).toISOString(), [form.markerColumn]: 1},
        {...fixture.rows[0], [form.timeColumn]: new Date(time).toISOString(), [form.markerColumn]: 2},
      ];
      value.response_check.expect.collections = [collection(included ? [1, 2] : [1])];
    }
  } else if (kind === 'priority') {
    markerReady();
    const candidates = form.candidates || [];
    ensure(candidates.length >= 2 && candidates.length <= 8, '優先順に候補を2〜8行設定してください');
    const rows = candidates.map((entries, index) => {
      const overrides = rowValues(entries);
      if (fixture.engine === 'influxdb') for (const entry of entries) {
        if (entry.name !== 'time' && !Object.hasOwn(fixture.scope, entry.name) && entry.name !== form.markerColumn) {
          ensure(!fixture.field_types[entry.name] || fixture.field_types[entry.name] === entry.type, '同じInfluxDBフィールドには同じ型を指定してください');
          fixture.field_types[entry.name] = entry.type;
        }
      }
      ensure(!Object.keys(fixture.scope).some(k => Object.hasOwn(overrides, k) && overrides[k] !== fixture.scope[k]), '候補行は同じ専用範囲にしてください');
      return {...fixture.rows[0], ...overrides, [form.markerColumn]: index+1};
    });
    for (let a = 0; a < rows.length; a++) for (let b = a+1; b < rows.length; b++) {
      for (const reverse of [false, true]) {
        const value = add(`優先順位：候補${a+1} > 候補${b+1}（${reverse ? '逆順' : '順方向'}に準備）`);
        value.test_fixture.rows = clone(reverse ? [rows[b], rows[a]] : [rows[a], rows[b]]);
        value.response_check.expect.collections = [collection([a+1])];
      }
    }
    if (rows.length > 2) for (const reverse of [false, true]) {
      const value = add(`優先順位：全候補・候補1を選択（${reverse ? '逆順' : '順方向'}に準備）`);
      value.test_fixture.rows = clone(reverse ? [...rows].reverse() : rows);
      value.response_check.expect.collections = [collection([1])];
    }
  } else if (kind === 'empty') {
    const value = add('対象データ0件');
    replaceChecks(value);
    value.test_fixture.rows = [];
    if (form.emptyBody) value.response_check.expect.empty_body = true;
    else {
      ensure(form.responseArray || form.emptyValues?.length, '0件時のレスポンス配列または固定期待値を設定してください');
      if (form.responseArray) {
        ensure(form.responseField, '配列の項目名を指定してください');
        value.response_check.expect.collections = [collection([])];
      }
      value.response_check.expect.values = (form.emptyValues || []).map(item => ({path: item.path, source: 'fixed', value: JSON.parse(item.value)}));
    }
  } else {
    const available = variantFields(operation);
    const fields = (form.fields || []).map(field => {
      const definition = available.find(x => x.source === field.source && x.name === field.name);
      ensure(definition, 'APIに定義された組み合わせ項目を選択してください');
      ensure(field.source !== 'path' || !field.omit, 'URLを組み立てるパス項目は省略できません');
      ensure(Array.isArray(field.values), '候補値をJSON配列で指定してください');
      const schema = definition.schema;
      const supported = ['string', 'integer', 'number', 'boolean'];
      ensure(supported.includes(schema.type), '組み合わせ候補は文字列・整数・数値・真偽値に対応しています');
      ensure(!['$ref', 'oneOf', 'anyOf', 'allOf', 'not', 'if'].some(key => key in schema), '合成条件を持つ項目は個別ケースで期待結果を設定してください');
      for (const value of field.values) {
        ensure(field.source === 'body' || value !== null, 'query・pathの候補値にはnullを指定できません。省略を選択してください');
        const validType = value === null ? schema.nullable === true : schema.type === 'integer' ? Number.isSafeInteger(value) : schema.type === 'number' ? typeof value === 'number' && Number.isFinite(value) : typeof value === schema.type;
        ensure(validType && (!schema.enum || schema.enum.includes(value)), `${field.name}の候補値を定義された型・enumに合わせてください`);
        if (typeof value === 'string') {
          ensure((schema.minLength === undefined || [...value].length >= schema.minLength) && (schema.maxLength === undefined || [...value].length <= schema.maxLength), `${field.name}の候補値が文字数制約に違反しています`);
          ensure(!schema.pattern || new RegExp(schema.pattern).test(value), `${field.name}の候補値が文字列パターンに違反しています`);
          if (schema.format === 'date-time') instant(value);
        }
        if (typeof value === 'number') {
          ensure((schema.minimum === undefined || (schema.exclusiveMinimum === true ? value > schema.minimum : value >= schema.minimum)) &&
            (schema.maximum === undefined || (schema.exclusiveMaximum === true ? value < schema.maximum : value <= schema.maximum)) &&
            (typeof schema.exclusiveMinimum !== 'number' || value > schema.exclusiveMinimum) &&
            (typeof schema.exclusiveMaximum !== 'number' || value < schema.exclusiveMaximum), `${field.name}の候補値が範囲制約に違反しています`);
          if (schema.multipleOf !== undefined) ensure(schema.multipleOf > 0 && Math.abs(value / schema.multipleOf - Math.round(value / schema.multipleOf)) < 1e-9, `${field.name}の候補値が倍数制約に違反しています`);
        }
      }
      ensure(new Set(field.values.map(JSON.stringify)).size === field.values.length, '候補値が重複しています');
      return {...field, required: definition.required};
    });
    ensure(fields.length >= 1 && fields.length <= 6, '組み合わせる項目を1〜6個指定してください');
    ensure(new Set(fields.map(x => `${x.source}.${x.name}`)).size === fields.length, '組み合わせる項目が重複しています');
    const invalidStatus = status(form.invalidStatus);
    ensure(invalidStatus >= 400 && invalidStatus < 500, '条件違反時の4xxステータスを指定してください');
    let variants = [{request: clone(source.request), descriptions: []}];
    for (const field of fields) {
      ensure(Array.isArray(field.values) && field.values.length + Number(!!field.omit) > 0, '候補値または省略を指定してください');
      const choices = [...field.values.map(value => ({value})), ...(field.omit ? [{omit: true}] : [])];
      ensure(variants.length * choices.length <= 64, '組み合わせが64件を超えます。項目を分けてください');
      variants = variants.flatMap(v => choices.map(choice => {
        const next = clone(v), [container, key] = requestField(next.request, field);
        if (choice.omit) delete container[key]; else container[key] = clone(choice.value);
        next.descriptions.push(`${field.name}=${choice.omit ? '省略' : JSON.stringify(choice.value)}`);
        return next;
      }));
    }
    for (const variant of variants) {
      const present = (field) => { const [container, key] = requestField(variant.request, field); return Object.hasOwn(container, key); };
      let valid = fields.every(field => !field.required || present(field));
      for (const relation of form.relations || []) {
        ensure(['atLeastOne', 'together', 'exactlyOne'].includes(relation.kind) && relation.a !== relation.b && fields[relation.a] && fields[relation.b], '項目間の条件を設定してください');
        const a = present(fields[relation.a]), b = present(fields[relation.b]);
        valid &&= relation.kind === 'atLeastOne' ? a || b : relation.kind === 'together' ? a === b : a !== b;
      }
      const value = add('組み合わせ：'+variant.descriptions.join(' / '), {request: variant.request});
      if (!valid) {
        replaceChecks(value);
        value.response_check.expect.status = invalidStatus;
        ensure(form.unchanged?.length, '異常系のDB変更なし確認範囲を指定してください');
        value.db_unchanged = clone(form.unchanged);
      }
    }
  }
  return result;
}
