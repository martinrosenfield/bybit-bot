from __future__ import annotations
"""Offline regression tests. No credentials, SDK session, or orders are used."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from types import SimpleNamespace

SOURCE = Path(__file__).with_name('bybit_bot.py')
FUNCS = {'round_qty', 'daily_realized_pnl', 'calc_qty', 'place_entry', 'save_state', 'preflight'}
SUBSET = ast.Module(body=[n for n in ast.parse(SOURCE.read_text()).body
                         if isinstance(n, ast.FunctionDef) and n.name in FUNCS], type_ignores=[])

class Guards(unittest.TestCase):
    def setUp(self):
        self.events=[]; self.saved=[]; self.orders=[]
        self.position=None; self.fills=[]; self.raise_send=False; self.raise_verify=False
        self.filters={'tick_size':'0.1','qty_step':'0.001','min_qty':Decimal('0.001'),
                      'max_qty':Decimal('100'),'min_notional':Decimal('5')}
        self.ns={'Decimal':Decimal,'ROUND_DOWN':ROUND_DOWN,'datetime':datetime,'timezone':timezone}
        exec(compile(SUBSET,'guards','exec'),self.ns)
        def send(**kw):
            self.orders.append(kw)
            if self.raise_send: raise TimeoutError('never log raw SDK request')
            return {'result':{'orderId':'mock-id'}}
        def executions(**kw):
            if self.raise_verify: raise ConnectionError('secret request')
            return {'result':{'list':self.fills}}
        self.api=SimpleNamespace(place_order=send,get_executions=executions)
        self.ns.update(ATR_STOP_MULT=1.5,ATR_TP_MULT=3.0,TAKER_FEE=0.00055,
            RISK_PER_TRADE=0.0025,MAX_NOTIONAL_PCT=0.5,DRY_RUN=False,
            get_equity=lambda:10000,instrument_filters=lambda s:self.filters,
            session=self.api,checked=lambda r,c:r,jlog=lambda e,**kw:self.events.append((e,kw)),
            time=SimpleNamespace(sleep=lambda n:None),open_position=lambda s:self.position,
            RUNTIME={'halted':[],'attempts':{},'pending':{},'entries_paused':False},
            save_state=lambda:self.saved.append(json.loads(json.dumps(self.ns['RUNTIME']))),
            load_config=lambda:{'dry_run':False},log=SimpleNamespace(info=lambda *a:None,warning=lambda *a:None))
    def entry(self):
        self.ns['place_entry']('BTCUSDT','Buy',Decimal('0.01'),80000,100,'demo-mock')
    def verified(self):
        self.position={'side':'Buy','size':'0.01','positionIdx':0,'avgPrice':'80001',
                       'stopLoss':'79850.0','takeProfit':'80300.0'}
        self.fills=[{'orderId':'mock-id','symbol':'BTCUSDT','side':'Buy','execType':'Trade',
                     'execQty':'0.01','execPrice':'80001','execId':'fill-1'}]
    def test_increment(self):
        self.assertEqual(self.ns['round_qty'](1.19,'0.25'),Decimal('1.00'))
    def test_acceptance_alone_halts(self):
        with self.assertRaises(RuntimeError): self.entry()
        self.assertNotIn('ENTRY',[e for e,d in self.events]);self.assertIn('BTCUSDT',self.ns['RUNTIME']['halted'])
        self.assertEqual(self.saved[0]['pending']['BTCUSDT'],'demo-mock')
    def test_verified_execution(self):
        self.verified();self.entry()
        d=[d for e,d in self.events if e=='ENTRY'][0]
        self.assertEqual(d['price'],'80001');self.assertEqual(d['execution_ids'],['fill-1'])
        self.assertFalse(d['dry_run']);self.assertIn('planned_risk',d)
        self.assertEqual(self.ns['RUNTIME']['pending'],{})
    def test_wrong_stop_halts(self):
        self.verified();self.position['stopLoss']='79849.9'
        with self.assertRaises(RuntimeError): self.entry()
        self.assertNotIn('ENTRY',[e for e,d in self.events])
    def test_unrelated_execution_halts(self):
        self.verified();self.fills[0]['orderId']='other'
        with self.assertRaises(RuntimeError): self.entry()
    def test_partial_execution_halts(self):
        self.verified();self.fills[0]['execQty']='0.005'
        with self.assertRaises(RuntimeError): self.entry()
    def test_send_timeout_persists_halt(self):
        self.raise_send=True
        with self.assertRaises(RuntimeError): self.entry()
        self.assertIn('BTCUSDT',self.ns['RUNTIME']['halted']);self.assertIn('BTCUSDT',self.ns['RUNTIME']['pending'])
    def test_verify_exception_persists_halt(self):
        self.raise_verify=True
        with self.assertRaises(RuntimeError): self.entry()
        self.assertIn('BTCUSDT',self.ns['RUNTIME']['halted'])
    def test_dry_run_never_orders_or_entry(self):
        self.ns['DRY_RUN']=True;self.entry()
        self.assertEqual(self.orders,[]);self.assertEqual([e for e,d in self.events],['DRY_RUN'])
    def test_pause_blocks_even_with_live_env(self):
        self.ns['RUNTIME']['entries_paused']=True
        with self.assertRaises(RuntimeError): self.entry()
        self.assertEqual(self.orders,[])
    def test_current_config_blocks(self):
        self.ns['load_config']=lambda:{'dry_run':True}
        with self.assertRaises(RuntimeError):self.entry()
        self.assertEqual(self.orders,[])
    def test_duplicate_never_retries(self):
        self.verified();self.entry()
        with self.assertRaises(RuntimeError):self.entry()
        self.assertEqual(len(self.orders),1)
    def test_fee_in_size(self):
        q=self.ns['calc_qty']('BTCUSDT',10000,80000,100)
        self.assertLessEqual(float(q)*(150+2*.00055*80000),25)
    def test_millisecond_pnl_pagination(self):
        calls=[]
        def pnl(**kw):
            calls.append(kw);return {'result':{'list':[{'closedPnl':'-3.5'}],
                           'nextPageCursor':'next' if len(calls)==1 else ''}}
        self.api.get_closed_pnl=pnl
        self.assertEqual(self.ns['daily_realized_pnl'](),-7)
        self.assertEqual(calls[0]['startTime']%86400000,0);self.assertEqual(calls[1]['cursor'],'next')
    def test_dry_preflight_never_changes_leverage(self):
        self.ns.update(DRY_RUN=True,SYMBOLS=['BTCUSDT'],get_klines=lambda s:[{'close':80000}],
                       atr=lambda r,p:100,ATR_PERIOD=14,set_leverage=lambda s:self.fail('mutation in dry-run'))
        self.ns['preflight']()

if __name__=='__main__':unittest.main()
