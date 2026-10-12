"""Build the confirmed pwrco request/DB test matrix."""
import argparse
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path


def mapping(table='y_pwrco', site_table='t_site'):
    return {'table':table, 'primary_key':['site_id','datetime'], 'rows_path':'schedule[]', 'columns':{
        'site_id':{'kind':'lookup','path':'location_id','preferred_path':'site_id','lookup':{'engine':'postgres','table':site_table,'match_column':'location_id','value_column':'site_id','cardinality':'one','value_type':'integer','on_empty':'unverified'}},
        'datetime':{'kind':'request','path':'schedule[].time'}, 'rate':{'kind':'request','path':'schedule[].value'},
        'start':{'kind':'request','path':'start_datetime'}, 'end':{'kind':'request','path':'end_time'},
        'type':{'kind':'request','path':'type','missing':'null'}}}


def build_suite(start, table='y_pwrco', site_table='t_site', site_id=101, location='HOME', other_location='OTHER'):
    base=datetime.fromisoformat(start)
    if base.tzinfo is None:
        raise ValueError('開始日時にはタイムゾーンを指定してください')
    cases=[]
    for site_mode in ['site','location','both-site-wins']:
        for type_value in [1,2,None]:
            for count in [1,2]:
                day=base+timedelta(days=len(cases))
                body={'start_datetime':day.isoformat(),'end_time':(day+timedelta(hours=2)).isoformat(),
                      'schedule':[{'time':(day+timedelta(minutes=30*i)).isoformat(),'value':12.5 if i==0 else 27.125} for i in range(count)]}
                if site_mode!='location':body['site_id']=site_id
                if site_mode!='site':body['location_id']=other_location if site_mode=='both-site-wins' else location
                if type_value is not None:body['type']=type_value
                cases.append({'name':f'pwrco {site_mode} / type={type_value if type_value is not None else "省略→NULL"} / {count}行',
                              'request':{'operationId':'setPwrco','body':body},'response_check':{'expect':{'status':200,'empty_body':True}},
                              'db_insert_check':mapping(table,site_table)})
    for item in invalid_cases(cases[0]['request']['body']):
        cases.append({'name':'pwrco 400 / '+item['name'], 'request':{'operationId':'setPwrco','body':item['body']},
                      'response_check':{'expect':{'status':400}},
                      'db_unchanged':[{'table':table,'columns':['site_id','datetime','rate','start','end','type'],'where':{}}]})
    return {'scenarios':cases}


def invalid_cases(valid_body):
    result=[]
    def add(name,body):
        result.append({'name':name,'body':body})
    for path in [('start_datetime',),('end_time',),('schedule',),('schedule',0,'time'),('schedule',0,'value')]:
        body=copy.deepcopy(valid_body);target=body
        for part in path[:-1]:target=target[part]
        del target[path[-1]];add('必須欠落:'+'.'.join(map(str,path)),body)
    body=copy.deepcopy(valid_body);body.pop('site_id',None);body.pop('location_id',None);add('拠点両方なし',body)
    for field,value in [('site_id','101'),('location_id',123),('type',3),('type','1'),('type',None),('start_datetime','not-a-date'),('end_time','not-a-date'),('schedule',{})]:
        body=copy.deepcopy(valid_body);body[field]=value;add(f'型・形式・enum:{field}={value!r}',body)
    for field,value in [('time','not-a-date'),('value','12.5'),('value',None)]:
        body=copy.deepcopy(valid_body);body['schedule'][0][field]=value;add(f'schedule項目:{field}={value!r}',body)
    for missing in [True,False]:
        body=copy.deepcopy(valid_body);second=copy.deepcopy(body['schedule'][0])
        second['time']=(datetime.fromisoformat(second['time'])+timedelta(minutes=30)).isoformat()
        if missing:del second['time']
        else:second['value']='invalid'
        body['schedule'].append(second);add('2件目不正・部分保存なし:'+('time欠落' if missing else 'value型違い'),body)
    body=copy.deepcopy(valid_body);body['schedule']=[];add('空schedule',body)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',required=True,help='主キーが既存と重ならない開始日時（オフセット付き）')
    parser.add_argument('--output',required=True)
    parser.add_argument('--table',default='y_pwrco');parser.add_argument('--site-table',default='t_site')
    parser.add_argument('--site-id',type=int,default=101);parser.add_argument('--location',default='HOME');parser.add_argument('--other-location',default='OTHER')
    args=parser.parse_args()
    data=build_suite(args.start,args.table,args.site_table,args.site_id,args.location,args.other_location)
    Path(args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
