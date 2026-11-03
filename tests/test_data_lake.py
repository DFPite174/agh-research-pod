"""Temporary-fixture checks; never write to a supplied research database."""
import hashlib
import importlib
import json

import duckdb
import pytest


def adapter():
    assert importlib.util.find_spec('agh_pod.data_lake') is not None, 'read-only lake adapter missing'
    return importlib.import_module('agh_pod.data_lake')


@pytest.fixture
def lake(tmp_path):
    path = tmp_path / 'tiny.duckdb'
    with duckdb.connect(str(path)) as db:
        db.execute('''CREATE TABLE tb_cb_basic(ts_code VARCHAR,bond_short_name VARCHAR,stk_code VARCHAR,
            stk_short_name VARCHAR,list_date VARCHAR,delist_date VARCHAR,issue_size DOUBLE,conv_price DOUBLE)''')
        db.execute('''CREATE TABLE tb_stock_basic(ts_code VARCHAR,name VARCHAR,list_date VARCHAR,
            delist_date VARCHAR)''')
        for table in ('tb_cb_daily','tb_stock_daily'):
            db.execute(f'''CREATE TABLE {table}(ts_code VARCHAR,trade_date VARCHAR,pre_close DOUBLE,
                open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,change DOUBLE,pct_chg DOUBLE,
                vol DOUBLE,amount DOUBLE)''')
        db.execute('CREATE TABLE tb_trade_cal(cal_date VARCHAR,is_open INTEGER,pretrade_date VARCHAR)')
        db.execute('''CREATE TABLE tb_sync_checkpoint(trade_date VARCHAR,cb_synced BOOLEAN,
            stock_synced BOOLEAN,cb_rows INTEGER,stock_rows INTEGER,updated_at TIMESTAMP)''')
        db.execute("INSERT INTO tb_cb_basic VALUES ('113008.SH','bond','601008.SH','stock','20160101',NULL,1e9,20)")
        db.execute("INSERT INTO tb_stock_basic VALUES ('601008.SH','stock','20000101',NULL)")
        db.execute("INSERT INTO tb_cb_daily VALUES ('113008.SH','20170103',114.66,0,0,0,114.66,0,0,0,0)")
        db.execute("INSERT INTO tb_cb_daily VALUES ('113008.SH','20170104',114.66,115,117,113,116,1.34,1.17,15,17)")
        db.execute("INSERT INTO tb_stock_daily VALUES ('601008.SH','20170104',10,10,11,9,10.5,.5,5,20,21)")
        db.execute("INSERT INTO tb_trade_cal SELECT strftime(d,'%Y%m%d'),CASE WHEN dayofweek(d) IN (0,6) THEN 0 ELSE 1 END,NULL FROM generate_series(DATE '2017-01-01',DATE '2017-01-31',INTERVAL 1 DAY) AS t(d)")
        db.execute("INSERT INTO tb_sync_checkpoint VALUES ('20170104',true,true,1,1,CURRENT_TIMESTAMP)")
    return path


def test_audit_reports_actual_coverage_and_gaps_without_private_path_or_mutation(lake):
    before=hashlib.sha256(lake.read_bytes()).hexdigest()
    report=adapter().audit_lake(lake)
    assert report['tables']['tb_cb_daily']['row_count']==2
    assert report['tables']['tb_cb_daily']['symbol_count']==1
    assert report['tables']['tb_cb_daily']['date_min']=='2017-01-03'
    assert report['tables']['tb_cb_daily']['date_max']=='2017-01-04'
    assert report['tables']['tb_cb_daily']['schema']['close']=='DOUBLE'
    quality=report['tables']['tb_cb_daily']['quality']
    assert quality['placeholder_rows']==1 and quality['invalid_ohlc_rows']==0
    assert report['month_end_coverage']['cb']['monthends_with_rows']==0
    assert report['fully_qualified'] is False
    assert report['paper_requirements']['historical_conversion_events']['status']=='MISSING'
    assert report['paper_requirements']['maturity_coupon_schedule']['status']=='MISSING'
    assert report['database']['stable'] is True
    assert report['database']['sha256_before']==before==report['database']['sha256_after']
    assert str(lake.parent) not in json.dumps(report,allow_nan=False)
    assert hashlib.sha256(lake.read_bytes()).hexdigest()==before


def test_bar_reads_preserve_zero_placeholders_and_filter_parameters(lake):
    rows=adapter().read_daily_bars(lake,symbols=['113008.SH'],start='2017-01-03',end='20170103')
    assert len(rows)==1
    assert rows[0]['open']==0 and rows[0]['close']==114.66 and rows[0]['vol']==0
    assert 'suspended' not in rows[0]
    stocks=adapter().read_daily_bars(lake,asset='stock',start='20170104')
    assert stocks[0]['ts_code']=='601008.SH'


@pytest.mark.parametrize('kwargs',[{'asset':'cb_daily; DROP TABLE tb_cb_basic'},
    {'asset':['cb']},
    {'symbols':["113008.SH' OR 1=1 --"]},{'symbols':'113008.SH'},
    {'start':"20170101' OR 1=1 --"},{'start':'20170104','end':'20170103'}])
def test_unsafe_or_ambiguous_query_inputs_are_rejected(lake,kwargs):
    with pytest.raises(ValueError):
        adapter().read_daily_bars(lake,**kwargs)
    with duckdb.connect(str(lake),read_only=True) as db:
        assert db.execute('SELECT COUNT(*) FROM tb_cb_basic').fetchone()[0]==1


def test_readonly_connections_are_enforced(lake,monkeypatch):
    module=adapter()
    real=duckdb.connect
    opened=[]
    def checked(*args,**kwargs):
        assert kwargs.get('read_only') is True
        opened.append(True)
        return real(*args,**kwargs)
    monkeypatch.setattr(module.duckdb,'connect',checked)
    module.audit_lake(lake)
    module.read_daily_bars(lake)
    assert len(opened)==2


def test_duplicates_and_invalid_ohlc_are_reported_separately_from_placeholders(lake):
    with duckdb.connect(str(lake)) as db:
        db.execute("INSERT INTO tb_cb_daily SELECT * FROM tb_cb_daily WHERE trade_date='20170104'")
        db.execute("INSERT INTO tb_cb_daily VALUES ('113008.SH','20170105',116,115,110,120,116,0,0,1,1)")
    report=adapter().audit_lake(lake)
    quality=report['tables']['tb_cb_daily']['quality']
    assert quality['duplicate_excess_rows']==1
    assert quality['invalid_ohlc_rows']==1 and quality['placeholder_rows']==1


def test_incomplete_calendar_does_not_invent_monthend(lake):
    with duckdb.connect(str(lake)) as db:
        db.execute("DELETE FROM tb_trade_cal WHERE cal_date>'20170116'")
    report=adapter().audit_lake(lake)
    january=next(m for m in report['month_end_coverage']['cb']['months'] if m['month']=='2017-01')
    assert january['calendar_complete'] is False
    assert january['expected_monthend'] is None


def test_paper_build_fails_with_gap_summary_without_fake_csv(lake):
    with pytest.raises(ValueError,match='historical_conversion_events'):
        adapter().build_paper_dataset(lake)
    report=adapter().capability_report(lake)
    assert report['fully_qualified'] is False
    assert report['paper_requirements']['treasury_spot_curves']['status']=='MISSING'
    assert list(lake.parent.glob('*.csv'))==[]


def test_read_transaction_cannot_mutate_schema_or_database_bytes(lake):
    module=adapter()
    before=hashlib.sha256(lake.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='read-only'):
        with module._snapshot(lake) as db:
            db.execute('CREATE TABLE forbidden_write(x INTEGER)')
    assert hashlib.sha256(lake.read_bytes()).hexdigest()==before
    with duckdb.connect(str(lake),read_only=True) as db:
        assert not db.execute("SELECT table_name FROM information_schema.tables WHERE table_name='forbidden_write'").fetchall()


def test_missing_database_is_not_silently_created(tmp_path):
    missing=tmp_path/'does-not-exist.duckdb'
    with pytest.raises(ValueError,match='existing file'):
        adapter().audit_lake(missing)
    assert not missing.exists()
