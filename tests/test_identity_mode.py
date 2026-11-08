"""Identity API permission isolation using TEST-ONLY synthetic identities."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.auth import VerifiedPrincipal
from analytics.config import Settings
from analytics.storage import Storage


@pytest.fixture
def api(tmp_path):
    path=tmp_path/'analytics.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for name in ('alpha','bravo','unowned'):
            db.execute('INSERT INTO sites VALUES(?,?,?,?)',
                       (name,name,json.dumps([f'{name}.example.com']),'2026-11-07'))
            db.execute('INSERT INTO site_domains VALUES(?,?,?,?)',
                       (name,f'{name}.example.com','', '2026-11-07'))
        db.executemany('INSERT INTO site_owners VALUES(?,?,?,?)', [
            ('alpha','tenant-a','2026-11-07','offline-operator'),
            ('bravo','tenant-b','2026-11-07','offline-operator')])
        db.executemany('INSERT INTO site_permissions VALUES(?,?,?,?)', [
            ('alpha','alice','analytics:read','2026-11-07'),
            ('alpha','alice','analytics:manage','2026-11-07'),
            ('alpha','bob','analytics:export','2026-11-07'),
            ('alpha','charlie','analytics:admin','2026-11-07'),
            ('bravo','alice','analytics:read','2026-11-07')])
    settings=Settings(admin_token='legacy-token-'+'l'*40,
                      hash_secret='h'*48,database=str(path),auth_mode='identity')
    identities={'alice':VerifiedPrincipal('tenant-a','alice'),
                'bob':VerifiedPrincipal('tenant-a','bob'),
                'charlie':VerifiedPrincipal('tenant-a','charlie'),
                'other':VerifiedPrincipal('tenant-b','alice')}
    def stub(token):
        if token not in identities:
            raise ValueError('not signed')
        return identities[token]
    return TestClient(create_app(settings,identity_verifier=stub)),settings


def headers(value):
    return {'Authorization':'Bearer '+value}


def test_missing_identity_verifier_refuses_to_start(tmp_path):
    config=Settings('a'*48,'b'*48,str(tmp_path/'db.sqlite3'),auth_mode='identity')
    with pytest.raises(RuntimeError,match='trusted signed-token verifier'):
        create_app(config)
    with pytest.raises(RuntimeError,match='Unknown authorization mode'):
        create_app(Settings('a'*48,'b'*48,config.database,auth_mode='wrong'))
    with pytest.raises(RuntimeError,match='Do not attach'):
        create_app(Settings('a'*48,'b'*48,config.database),
                   identity_verifier=lambda _:VerifiedPrincipal('tenant','subject'))


def test_legacy_token_is_never_identity_fallback(api):
    client,settings=api
    for hdr in ({},headers('invalid'),headers(settings.admin_token),
                {'Authorization':'Basic alice'},headers('alice\nforged')):
        assert client.get('/api/v1/sites',headers=hdr).status_code==401
    assert client.get('/api/v1/sites/alpha/summary',
                      headers={'X-GoreeCloud-Tenant':'tenant-a','X-GoreeCloud-Subject':'alice'}).status_code==401


def test_site_list_is_tenant_and_membership_filtered(api):
    client,_=api
    assert [s['id'] for s in client.get('/api/v1/sites',headers=headers('alice')).json()]==['alpha']
    assert client.get('/api/v1/sites',headers=headers('bob')).json()==[]
    assert client.get('/api/v1/sites',headers=headers('charlie')).json()==[]
    assert [s['id'] for s in client.get('/api/v1/sites',headers=headers('other')).json()]==['bravo']


@pytest.mark.parametrize('endpoint',['summary','timeseries','breakdown','goals',
                                     'realtime','funnel?first=signup&second=checkout'])
def test_read_routes_check_exact_membership(api,endpoint):
    client,_=api
    for token,expected in [('alice',200),('bob',404),('other',404)]:
        res=client.get('/api/v1/sites/alpha/'+endpoint,headers=headers(token))
        assert res.status_code==expected,(endpoint,token,res.text)


def test_manage_export_and_dns_admin_are_distinct(api):
    client,_=api
    assert client.get('/api/v1/sites/alpha/export.csv',headers=headers('alice')).status_code==404
    assert client.get('/api/v1/sites/alpha/export.csv',headers=headers('bob')).status_code==200
    goal={'name':'signup','kind':'event','target':'signup'}
    assert client.post('/api/v1/sites/alpha/goals',headers=headers('bob'),json=goal).status_code==404
    assert client.post('/api/v1/sites/alpha/goals',headers=headers('alice'),json=goal).status_code==201
    url='/api/v1/sites/alpha/domains/revoke'
    assert client.post(url,headers=headers('alice'),json={'domain':'alpha.example.com'}).status_code==404
    assert client.post(url,headers=headers('charlie'),json={'domain':'alpha.example.com'}).status_code==200
    assert client.post('/api/v1/sites',headers=headers('charlie'),
                       json={'name':'Unapproved','domains':['new.example.com']}).status_code==403


def test_wrong_tenant_unowned_and_unknown_are_indistinguishable(api):
    client,_=api
    for site in ('bravo','unowned','missing'):
        res=client.get(f'/api/v1/sites/{site}/summary',headers=headers('alice'))
        assert res.status_code==404 and res.json()['detail']=='Unknown site'


def test_collector_is_anonymous_separate_trust_boundary(api):
    client,_=api
    assert client.post('/api/v1/collect',headers={'Origin':'https://alpha.example.com'},
                       json={'site_id':'alpha','type':'pageview',
                             'url':'https://alpha.example.com/'}).status_code==202
    assert client.get('/api/v1/sites/alpha/summary').status_code==401
    assert client.get('/api/v1/sites/alpha/summary',headers=headers('alice')).json()['pageviews']==1


def test_malformed_verifier_results_and_exceptions_fail_closed(api):
    client,settings=api
    def bad(token):
        if token=='dict':return {'tenant_id':'tenant-a','subject_id':'alice'}
        if token=='invalid':return VerifiedPrincipal('tenant with spaces','alice')
        raise RuntimeError('sensitive upstream error')
    target=TestClient(create_app(settings,identity_verifier=bad))
    for token in ('dict','invalid','upstream'):
        res=target.get('/api/v1/sites/alpha/summary',headers=headers(token))
        assert res.status_code==401 and 'sensitive upstream' not in res.text


def test_mode_env_fails_closed_for_unknown_value(monkeypatch):
    monkeypatch.setenv('GC_ANALYTICS_ADMIN_TOKEN','a'*48)
    monkeypatch.setenv('GC_ANALYTICS_HASH_SECRET','b'*48)
    monkeypatch.setenv('GC_ANALYTICS_AUTH_MODE','identity')
    assert Settings.from_env().auth_mode=='identity'
    monkeypatch.setenv('GC_ANALYTICS_AUTH_MODE','invalid')
    with pytest.raises(RuntimeError,match='GC_ANALYTICS_AUTH_MODE'):
        Settings.from_env()


def test_pending_dns_challenges_are_admin_only_even_with_read_permission(api):
    client, settings = api
    with sqlite3.connect(settings.database) as db:
        db.execute("UPDATE site_domains SET verified_at=NULL, challenge=? "
                   "WHERE site_id=?", ("not-a-public-challenge", "alpha"))
        db.execute("INSERT INTO site_permissions(site_id,subject_id,permission,granted_at) "
                   "VALUES(?,?,?,?)", ("alpha", "charlie", "analytics:read", "2026-11-08"))
    # Reader can observe a pending hostname, but cannot fetch its verification secret.
    listed = client.get('/api/v1/sites', headers=headers('alice'))
    assert listed.status_code == 200
    proof = listed.json()[0]['verification'][0]
    assert proof['domain'] == 'alpha.example.com'
    assert proof['verified'] is False and proof['record_name']
    assert proof['record_value'] is None
    assert 'not-a-public-challenge' not in listed.text
    # An explicit site admin plus read grant can still complete DNS onboarding.
    privileged = client.get('/api/v1/sites', headers=headers('charlie'))
    assert privileged.status_code == 200
    admin_proof = privileged.json()[0]['verification'][0]
    assert admin_proof['record_value'] == 'goreecloud-analytics-verification=not-a-public-challenge'
    # Export-only principals cannot list a site or any TXT secret.
    assert client.get('/api/v1/sites', headers=headers('bob')).json() == []
