import copy
from decimal import Decimal

import pytest
import yaml

from db_backends.sql_response import bind_parameters, expected_tree, compare
from db_backends.postgres_backend import DBResponseCheckUnverified
from db_scenario import parse_scenarios
from src.sql_response_mapping import validate_sql_response


def definition():
    return {'sql': 'SELECT 1', 'parameters': {'site': {'source':'body', 'path':'site_id'}, 'correct': {'source':'body','path':'correct','missing':'null'}},
            'fields': {'site_id':'site', 'plans[].date':'day', 'plans[].type':'type', 'plans[].profit':'profit',
                       'plans[].controls[].time':'time', 'plans[].controls[].value':'value', 'plans[].controls[].correct_point':'point'},
            'arrays':[{'path':'plans[]','group_by':['day','type']}, {'path':'plans[].controls[]','group_by':[]}]}


def rows():
    return [dict(site=1,day=day,type=kind,profit=10 if day=='a' else 20,time=time,value=Decimal('1.123'),point={'start':{'buy':1}})
            for day, kind, time in [('a','1-1','00:00'),('a','1-1','00:30'),('a','2-1','00:00'),('b','1-1','00:00')]]


def test_parent_grouping_json_decimal_and_order():
    check=definition(); tree=expected_tree(check,rows())
    assert len(tree['plans'])==3 and len(tree['plans'][0]['controls'])==2
    actual=copy.deepcopy(tree); actual['plans'].reverse()
    actual['plans'][2]['controls'].reverse()
    actual['plans'][2]['controls'][0]['value']=1.123
    assert compare(check,tree,actual,{})[0]
    check['arrays'][0]['ordered']=True
    assert not compare(check,tree,actual,{})[0]


@pytest.mark.parametrize('fault',['missing','extra','duplicate','wrong_parent','split','value','json','bool','root'])
def test_faults(fault):
    check=definition(); tree=expected_tree(check,rows()); actual=copy.deepcopy(tree)
    controls=actual['plans'][0]['controls']
    if fault=='missing': controls.pop()
    if fault=='extra': controls.append(copy.deepcopy(controls[0]))
    if fault=='duplicate': controls[1]=copy.deepcopy(controls[0])
    if fault=='wrong_parent': actual['plans'][0]['controls'],actual['plans'][2]['controls']=actual['plans'][2]['controls'],controls
    if fault=='split': actual['plans'].append(copy.deepcopy(actual['plans'][0])); actual['plans'][0]['controls'].pop()
    if fault=='value': controls[0]['value']=1.124
    if fault=='json': controls[0]['correct_point']['start']['buy']=2
    if fault=='bool': controls[0]['correct_point']['start']['buy']=True
    if fault=='root': actual['site_id']=2
    assert not compare(check,tree,actual,{})[0]


def test_ambiguous_group_stops_and_duplicates_preserved():
    data=rows(); data[1]['profit']=999
    with pytest.raises(ValueError,match='グループ'): expected_tree(definition(),data)
    data=rows(); data.append(copy.deepcopy(data[0]))
    assert len(expected_tree(definition(),data)['plans'][0]['controls'])==3


def test_empty_rows_are_not_blindly_passed():
    with pytest.raises(DBResponseCheckUnverified): expected_tree(definition(),[])
    check=definition();del check['fields']['site_id']
    tree=expected_tree(check,[])
    assert tree=={'plans':[]}
    assert compare(check,tree,tree,{})[0]
    assert not compare(check,tree,{},{} )[0]


def test_parameter_omission_false_zero_and_injection_data():
    check=definition()
    assert bind_parameters(check,{'body':{'site_id':0,'correct':False}})=={'site':0,'correct':False}
    assert bind_parameters(check,{'body':{'site_id':"x'; DELETE FROM t; --"}})['correct'] is None
    with pytest.raises(ValueError): bind_parameters(check,{'body':{}})


@pytest.mark.parametrize('sql',['DELETE FROM h_plan','SELECT 1; DELETE FROM h_plan','', 'SET transaction_read_only=off'])
def test_bad_sql(sql):
    check=definition();check['sql']=sql
    with pytest.raises(ValueError): validate_sql_response(check)


def test_invalid_mappings():
    check=definition();check['arrays']=[]
    with pytest.raises(ValueError): validate_sql_response(check)
    check=definition();check['fields']['plans[].controls[].correct_point.start.buy']='value'
    with pytest.raises(ValueError): validate_sql_response(check)
    check=definition();check['fields']['plans.date']='day'
    with pytest.raises(ValueError): validate_sql_response(check)


def test_definition_changes_review_identity():
    raw={'name':'sql', 'request':{'operationId':'getPlans'},'db_sql_response_check':definition()}
    first=parse_scenarios(yaml.safe_dump({'scenarios':[raw]}))[0]
    raw['db_sql_response_check']['sql']='SELECT 2'
    second=parse_scenarios(yaml.safe_dump({'scenarios':[raw]}))[0]
    assert first.case_id!=second.case_id
    assert first.case_definition()['dbSqlResponseCheck']==definition()
