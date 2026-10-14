import { buildRuleCases } from './rule-cases.js';
import { variantFields } from './scenario-templates.js';
import { addErrorDbScope, collectErrorDbScopes } from './error-db-scopes.js';

const node = (tag, text = '') => { const el = document.createElement(tag); el.textContent = text; return el; };
const types = [['string', '文字列・日時'], ['integer', '整数'], ['float', '小数'], ['boolean', '真偽値'], ['null', 'null'], ['json', 'JSON']];

function input(parent, label, value = '', choices = null) {
  const wrap = node('label', label), el = node(choices ? 'select' : 'input');
  if (choices) for (const [key, title] of choices) { const option = node('option', title); option.value = key; el.append(option); }
  else el.type = 'text';
  el.value = String(value); el.setAttribute('aria-label', label); wrap.append(el); parent.append(wrap); return el;
}
function button(parent, label, run) { const el = node('button', label); el.type = 'button'; el.className = 'secondary'; el.onclick = run; parent.append(el); return el; }
function rowsEditor(parent, label, values = []) {
  const section = node('fieldset'); section.append(node('legend', label)); parent.append(section);
  const list = node('div'); section.append(list);
  const add = (value = {}) => {
    const row = node('div'); row.className = 'rule-value-row';
    const name = input(row, `${label}：列名`, value.name || '');
    const type = input(row, `${label}：型`, value.type || 'string', types);
    const val = input(row, `${label}：値`, value.value ?? '');
    button(row, '行を削除', () => { row.remove(); section.dispatchEvent(new window.Event('input', {bubbles: true})); });
    row.collect = () => ({name: name.value.trim(), type: type.value, value: val.value}); list.append(row);
  };
  values.forEach(add);
  button(section, `${label}の列を追加`, () => { add(); section.dispatchEvent(new window.Event('input', {bubbles: true})); });
  return () => [...list.children].map(row => row.collect());
}

export function ruleControls(source, operation, onAppend, onError) {
  const root = node('details'); root.className = 'rule-controls';
  root.append(node('summary', '共通ルールから試験を作成（期間・組み合わせ・優先順位・0件）'));
  // A large case list must not eagerly create hundreds of editors.
  root.addEventListener('toggle', () => {
    if (!root.open || root.dataset.ready) return;
    root.dataset.ready = 'true';
    const saved = source.rule_test?.settings || {};
    const form = node('div'); form.className = 'rule-form'; root.append(form);
    const help = node('p', 'ルールを設定 → 生成内容を確認 → ケースに追加 → 保存・実行。期待結果は設定した仕様から作ります。検証データは既存行のない専用範囲に準備し、作成した行だけを片付けます。'); form.append(help);
    const kind = input(form, '試験ルール', saved.kind || 'boundary', [['boundary', '期間の境界'], ['combinations', '項目の組み合わせ'], ['priority', 'データの優先順位'], ['empty', '対象データ0件']]);
    const code = input(form, 'ルール試験の期待ステータス', saved.status ?? source.response_check?.expect?.status ?? '');
    const fields = variantFields(operation);
    const choices = [['', '項目を選択'], ...fields.map((field, index) => [String(index), `${field.source}：${field.name}`])];
    const indexFor = (field) => { const index = fields.findIndex(x => x.name === field?.name && x.source === field?.source); return index < 0 ? '' : String(index); };

    const data = node('fieldset'); data.append(node('legend', '検証データ')); form.append(data);
    data.append(node('p', '専用のテストDBで、APIが参照する範囲を指定してください。既存データがあれば「未確認」で停止します。DB必須列は入力してください。値を推測して埋めることはしません。'));
    const useFixture = input(data, '組み合わせ試験でも検証データを準備', String(saved.useFixture ?? false), [['false', '準備しない（既存の正常設定を使用）'], ['true', '準備する']]);
    const engine = input(data, '検証データのDB', saved.engine || source.db_response_check?.engine || 'postgres', [['postgres', 'PostgreSQL'], ['influxdb', 'InfluxDB 1.x']]);
    const table = input(data, '検証データのテーブル／measurement', saved.table || source.db_response_check?.table || source.db_insert_check?.table || '');
    const scope = rowsEditor(data, '専用範囲（InfluxDBは全タグ）', saved.scope || []);
    const seed = rowsEditor(data, '共通の初期行（専用範囲は自動付加）', saved.seed || []);

    const projection = node('fieldset'); projection.append(node('legend', '返却データの照合')); form.append(projection);
    projection.append(node('p', '配列は件数・値・重複を比較します。並び順は問いません。入れ子は plans[].controls[] のように指定します。'));
    projection.append(node('p', '境界・優先順位では、レスポンスにそのまま返る数値列を1、2…に変えて行を識別します。計算で変換される値は、別途DB・SQLとの対応設定で照合してください。'));
    const array = input(projection, '照合するレスポンス配列', saved.responseArray || source.db_response_check?.array_path || '');
    const responseField = input(projection, '配列内の照合項目', saved.responseField || '');
    const marker = input(projection, '照合項目に対応する数値のDB列', saved.markerColumn || '');

    const period = node('fieldset'); period.append(node('legend', '期間境界：6つの条件')); form.append(period);
    const start = input(period, '開始のリクエスト項目', indexFor(saved.startField), choices);
    const end = input(period, '終了のリクエスト項目', indexFor(saved.endField), choices);
    const timeColumn = input(period, 'DBの日時列', saved.timeColumn || '');
    const startIn = input(period, '開始と一致するデータ', String(saved.includeStart ?? true), [['true', '含む（以上）'], ['false', '含まない（より後）']]);
    const endIn = input(period, '終了と一致するデータ', String(saved.includeEnd ?? false), [['false', '含まない（未満）'], ['true', '含む（以下）']]);
    const step = input(period, '境界の刻み幅（ミリ秒）', saved.stepMs ?? '1000');
    period.append(node('p', '基準リクエストの期間を使います。常に期間内の1行と、境界を確認する1行を用意します。日時列・照合用列はケースごとに設定されます。'));

    const priority = node('fieldset'); priority.append(node('legend', '優先する候補行（上ほど優先）')); form.append(priority);
    priority.append(node('p', '共通の初期行から変える列だけ指定します。全ペアと全候補を、投入順を変えて確認します。同じグループに属し、主キーが衝突しない候補を設定してください。'));
    const candidates = node('div'); priority.append(candidates);
    const numberCandidates = () => [...candidates.children].forEach((entry, index) => { entry.querySelector('legend').textContent = `候補${index+1}の変更値`; });
    const addCandidate = (values = []) => {
      const entry = node('div'); entry.className = 'rule-candidate';
      entry.collect = rowsEditor(entry, `候補${candidates.children.length+1}の変更値`, values);
      button(entry, '候補を上へ', () => { if (entry.previousElementSibling) candidates.insertBefore(entry, entry.previousElementSibling); numberCandidates(); root.dispatchEvent(new window.Event('input')); });
      button(entry, '候補を削除', () => { entry.remove(); numberCandidates(); root.dispatchEvent(new window.Event('input')); });
      candidates.append(entry); numberCandidates();
    };
    (saved.candidates || [[], []]).forEach(addCandidate);
    button(priority, '候補行を追加', () => { addCandidate(); root.dispatchEvent(new window.Event('input')); });

    const combos = node('fieldset'); combos.append(node('legend', '項目の組み合わせ（最大64件・省略なしで全生成）')); form.append(combos);
    const comboRows = node('div'); combos.append(comboRows);
    const addField = (value = {}) => {
      const row = node('div'); row.className = 'rule-value-row';
      const field = input(row, '組み合わせる項目', indexFor(value), choices);
      const vals = input(row, '候補値（JSON配列）', JSON.stringify(value.values || []));
      const omit = input(row, '省略も試験する', String(value.omit ?? false), [['false', 'しない'], ['true', 'する']]);
      row.collect = () => ({...fields[field.value === '' ? -1 : Number(field.value)], values: JSON.parse(vals.value), omit: omit.value === 'true'});
      field.onchange = () => { const item = fields[Number(field.value)]; vals.value = JSON.stringify(item?.schema.enum || (item?.schema.type === 'boolean' ? [false, true] : [])); };
      button(row, '項目を削除', () => { row.remove(); root.dispatchEvent(new window.Event('input')); }); comboRows.append(row);
    };
    (saved.fields || []).forEach(addField); button(combos, '組み合わせる項目を追加', () => { addField(); root.dispatchEvent(new window.Event('input')); });
    const relations = node('div'); combos.append(relations);
    const addRelation = (value = {}) => {
      const row = node('div'); row.className = 'rule-value-row';
      const options = [...comboRows.children].map((entry, index) => [String(index), entry.querySelector('select').selectedOptions[0].textContent]);
      const a = input(row, '条件の項目1', value.a ?? '', [['', '項目を選択'], ...options]);
      const b = input(row, '条件の項目2', value.b ?? '', [['', '項目を選択'], ...options]);
      const rel = input(row, '項目間の条件', value.kind || 'atLeastOne', [['atLeastOne', '少なくとも一方が必須'], ['together', '両方指定または両方省略'], ['exactlyOne', 'どちらか一方だけ必須']]);
      row.collect = () => ({a: a.value === '' ? -1 : Number(a.value), b: b.value === '' ? -1 : Number(b.value), kind: rel.value});
      button(row, '条件を削除', () => { row.remove(); root.dispatchEvent(new window.Event('input')); }); relations.append(row);
    };
    (saved.relations || []).forEach(addRelation); button(combos, '項目間の条件を追加', () => { addRelation(); root.dispatchEvent(new window.Event('input')); });
    // Changing the field list invalidates relations rather than silently rebinding them.
    comboRows.addEventListener('change', event => { if (event.target.matches('select[aria-label="組み合わせる項目"]')) relations.replaceChildren(); });
    comboRows.addEventListener('click', event => { if (event.target.tagName === 'BUTTON') relations.replaceChildren(); });
    const invalid = input(combos, '条件違反時の期待ステータス', saved.invalidStatus || '');
    combos.append(node('h4', '異常時に変更されないことを確認するDB範囲'));
    const guards = node('div'); combos.append(guards);
    (saved.unchanged || source.db_unchanged || []).forEach(scope => addErrorDbScope(guards, scope));
    button(combos, 'DB変更なしの確認範囲を追加', () => { addErrorDbScope(guards); root.dispatchEvent(new window.Event('input')); });
    guards.addEventListener('click', () => root.dispatchEvent(new window.Event('input')));
    combos.append(node('p', '正常時のDB対応は基準ケースを使います。条件違反時にはDB変更なしを照合します。候補値は正常な型・enumの値を指定してください。'));

    const empty = node('fieldset'); empty.append(node('legend', '0件時の期待レスポンス')); form.append(empty);
    const emptyBody = input(empty, '0件時のボディ', String(saved.emptyBody ?? false), [['false', 'JSON（空配列や固定値）'], ['true', '本文なし']]);
    empty.append(node('p', '空配列なら「返却データの照合」に配列と項目を指定します。エラー本文などは下に固定期待値を設定してください。ステータスはAPI仕様どおり指定します。'));
    const emptyValues = node('div'); empty.append(emptyValues);
    const addExpected = (value = {}) => {
      const row = node('div'); row.className = 'rule-value-row';
      const path = input(row, '0件時のレスポンス項目', value.path || '');
      const val = input(row, '0件時の期待値（JSON）', value.value || '');
      row.collect = () => ({path: path.value.trim(), value: val.value});
      button(row, '期待値を削除', () => { row.remove(); root.dispatchEvent(new window.Event('input')); }); emptyValues.append(row);
    };
    (saved.emptyValues || []).forEach(addExpected); button(empty, '0件時の期待値を追加', () => { addExpected(); root.dispatchEvent(new window.Event('input')); });
    const collect = () => ({kind: kind.value, status: code.value, engine: engine.value, table: table.value.trim(),
      useFixture: useFixture.value === 'true', scope: scope(), seed: seed(), responseArray: array.value.trim(),
      responseField: responseField.value.trim(), markerColumn: marker.value.trim(), timeColumn: timeColumn.value.trim(),
      startField: start.value === '' ? undefined : fields[Number(start.value)], endField: end.value === '' ? undefined : fields[Number(end.value)],
      includeStart: startIn.value === 'true', includeEnd: endIn.value === 'true', stepMs: step.value,
      candidates: [...candidates.children].map(row => row.collect()), fields: [...comboRows.children].map(row => row.collect()),
      relations: [...relations.children].map(row => row.collect()), invalidStatus: invalid.value,
      unchanged: collectErrorDbScopes(guards), emptyBody: emptyBody.value === 'true', emptyValues: [...emptyValues.children].map(row => row.collect())});
    const message = node('p'); message.setAttribute('role', 'status'); root.append(message);
    const preview = node('div'); preview.className = 'rule-preview'; root.append(preview);
    let pending = null;
    button(root, '生成する試験を確認', () => {
      try {
        pending = buildRuleCases(source, operation, collect());
        preview.replaceChildren(); const list = node('ol');
        for (const scenario of pending) {
          const item = node('li'), detail = node('details');
          detail.append(node('summary', `${scenario.rule_test.condition} → ${scenario.response_check.expect.status} / 検証データ${scenario.test_fixture?.rows.length ?? '既存'}行`));
          detail.append(node('pre', JSON.stringify({request: scenario.request, data: scenario.test_fixture, expect: scenario.response_check.expect}, null, 2)));
          item.append(detail); list.append(item);
        }
        preview.append(list); message.textContent = `${pending.length}件を生成します。まだ保存・実行していません。`; append.disabled = false;
      } catch (error) { pending = null; append.disabled = true; preview.replaceChildren(); message.textContent = error.message; onError(error.message); }
    });
    const append = button(root, '確認した試験を追加', () => { if (pending) onAppend(pending); }); append.disabled = true;
    const invalidate = () => { pending = null; append.disabled = true; preview.replaceChildren(); message.textContent = '設定後に「生成する試験を確認」を押してください'; };
    root.addEventListener('input', invalidate); root.addEventListener('change', invalidate);
    const show = () => {
      period.hidden = kind.value !== 'boundary'; priority.hidden = kind.value !== 'priority';
      combos.hidden = kind.value !== 'combinations'; empty.hidden = kind.value !== 'empty';
      projection.hidden = kind.value === 'combinations'; useFixture.parentElement.hidden = kind.value !== 'combinations';
      marker.parentElement.hidden = kind.value === 'empty'; invalidate();
    };
    kind.onchange = show; show();
  });
  return root;
}
