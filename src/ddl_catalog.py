"""Parse PostgreSQL DDL as metadata only. Never connect to or execute against a DB."""
import re

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers


IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def parse_ddl(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > 2_000_000:
        raise ValueError('DDLは2MB以下のテキストを指定してください')
    try:
        statements = [normalize_identifiers(s, dialect='postgres') if s is not None else None for s in sqlglot.parse(text, read='postgres')]
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f'DDLを解析できません: {exc}') from exc
    tables, warnings = {}, []

    def name(node):
        return (node.db or 'public') + '.' + node.name

    def constraint(table, node, column=None):
        if isinstance(node, exp.Constraint):
            for child in node.expressions:
                constraint(table, child, column)
        elif isinstance(node, exp.PrimaryKey):
            table['primaryKey'] = [item.name for item in node.expressions]
        elif isinstance(node, exp.PrimaryKeyColumnConstraint):
            table['primaryKey'].append(column)
        elif isinstance(node, exp.UniqueColumnConstraint):
            table['unique'].append([column] if column else [item.name for item in node.this.expressions])
        elif isinstance(node, exp.ForeignKey):
            reference = node.args['reference'].this
            target = reference.this if isinstance(reference, exp.Schema) else reference
            table['foreignKeys'].append({'columns': [item.name for item in node.expressions],
                                        'table': name(target), 'targetColumns': [item.name for item in reference.expressions]})
        elif isinstance(node, exp.Reference):
            target = node.this.this if isinstance(node.this, exp.Schema) else node.this
            table['foreignKeys'].append({'columns': [column], 'table': name(target),
                                        'targetColumns': [item.name for item in node.this.expressions]})
        elif isinstance(node, exp.CheckColumnConstraint):
            table['checks'].append(node.this.sql(dialect='postgres'))
        elif isinstance(node, (exp.NotNullColumnConstraint, exp.DefaultColumnConstraint, exp.GeneratedAsIdentityColumnConstraint, exp.ComputedColumnConstraint)):
            pass  # Stored on the column below.
        else:
            warnings.append('未対応の制約: ' + node.sql(dialect='postgres'))
            table['incomplete'] = True

    def column(table, node):
        if any(c['name'] == node.name for c in table['columns']):
            raise ValueError('DDL内のカラム名が重複しています: ' + table['name'] + '.' + node.name)
        constraints = [c.args['kind'] for c in node.args.get('constraints', [])]
        table['columns'].append({'name': node.name, 'type': node.args['kind'].sql(dialect='postgres'),
                                'nullable': not any(isinstance(c, (exp.NotNullColumnConstraint, exp.PrimaryKeyColumnConstraint, exp.GeneratedAsIdentityColumnConstraint)) for c in constraints),
                                'default': next((c.this.sql(dialect='postgres') for c in constraints if isinstance(c, exp.DefaultColumnConstraint)), None),
                                'generated': next((c.sql(dialect='postgres') for c in constraints if isinstance(c, (exp.GeneratedAsIdentityColumnConstraint, exp.ComputedColumnConstraint))), None)})
        for item in constraints:
            constraint(table, item, node.name)

    for statement in statements:
        if statement is None:
            continue
        if isinstance(statement, exp.Create) and statement.args.get('kind') == 'TABLE' and isinstance(statement.this, exp.Schema):
            node = statement.this.this
            key = name(node)
            if key in tables:
                raise ValueError('DDL内のテーブル定義が重複しています: ' + key)
            table = {'name': node.name, 'schema': node.db or 'public', 'columns': [], 'primaryKey': [],
                     'unique': [], 'foreignKeys': [], 'checks': [], 'incomplete': False,
                     'mappingSelectable': (node.db or 'public') == 'public' and bool(IDENT.fullmatch(node.name))}
            tables[key] = table
            for item in statement.this.expressions:
                if isinstance(item, exp.ColumnDef):
                    column(table, item)
                else:
                    constraint(table, item)
            if statement.args.get('expression') or statement.args.get('properties'):
                warnings.append(key + ': テーブルの付加設定は型・制約一覧に反映していません')
        elif isinstance(statement, exp.Alter) and statement.args.get('kind') == 'TABLE':
            table = tables.get(name(statement.this))
            if table is None:
                warnings.append('CREATE TABLEがない変更: ' + statement.sql(dialect='postgres'))
                continue
            for action in statement.args.get('actions', []):
                if isinstance(action, exp.AddConstraint):
                    for item in action.expressions:
                        constraint(table, item)
                elif isinstance(action, exp.ColumnDef):
                    column(table, action)
                elif isinstance(action, exp.AlterColumn) and set(action.args) <= {'this', 'default', 'drop', 'exists', 'allow_null', 'dtype', 'collate', 'using'} and not action.args.get('using') and not action.args.get('collate'):
                    found = next((c for c in table['columns'] if c['name'] == action.name), None)
                    if found is None:
                        raise ValueError('変更対象のカラムがありません: ' + action.name)
                    if 'allow_null' in action.args:
                        found['nullable'] = action.args['allow_null']
                    elif action.args.get('drop'):
                        found['default'] = None
                    elif action.args.get('default') is not None:
                        found['default'] = action.args['default'].sql(dialect='postgres')
                    elif action.args.get('dtype') is not None:
                        found['type'] = action.args['dtype'].sql(dialect='postgres')
                    else:
                        table['incomplete'] = True
                        warnings.append('未対応のカラム変更: ' + action.sql(dialect='postgres'))
                else:
                    table['incomplete'] = True
                    warnings.append('未対応の変更: ' + action.sql(dialect='postgres'))
        else:
            if isinstance(statement, exp.Drop) and statement.args.get('kind') == 'TABLE':
                for node in statement.args.get('tables', []) or [statement.this]:
                    if node is not None:
                        tables.pop(name(node), None)
            if isinstance(statement, exp.Command) and statement.name.upper() == 'ALTER':
                # An unparsed structural ALTER must never leave an apparently complete catalog.
                command = str(statement.args.get('expression', ''))
                owner_only = re.fullmatch(r'\s*TABLE\s+(?:ONLY\s+)?(?:"[^"]+"|[\w.]+)\s+OWNER\s+TO\s+(?:"[^"]+"|\w+)\s*', command, re.I)
                if not owner_only:
                    for table in tables.values():
                        table['incomplete'] = True
            warnings.append('一覧に反映しない文（実行しません）: ' + statement.sql(dialect='postgres')[:300])
    for table in tables.values():
        for item in table['columns']:
            if item['name'] in table['primaryKey']:
                item['nullable'] = False
        table['mappingSelectable'] &= not table['incomplete']
    if not tables:
        raise ValueError('CREATE TABLEの定義がありません')
    return {'version': 1, 'dialect': 'postgres', 'tables': list(tables.values()), 'warnings': warnings,
            'note': '無修飾のテーブル名はpublicとして表示します。DDLは実行していません。APIの対応や業務ルールは推測しません。'}
