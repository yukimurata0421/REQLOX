"Finite reliability controls and verification."
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import datetime
import os
from pathlib import Path
import re
import resource
import time

from . import incident_reference as c

SCHEMA = 'reqlox.workflow-effort.v0.1'
MAX_EVENTS = 1024
HUMAN_SCOPE = 'RUNNER_INTERVENTIONS_ONLY'
AMOUNTS = ('reserved', 'estimated', 'invoiced')


def number(value):
    c.require(type(value) is str and re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,12})?', value)
              and Decimal(value) <= Decimal('1000000000'), 'EFFORT_AMOUNT')
    return Decimal(value)


def token(value):
    c.require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', value), 'EFFORT_IDENTIFIER')


def interval(value, end):
    c.require(type(value) is list and len(value) == 2
              and all(type(n) is int for n in value) and 0 <= value[0] <= value[1] <= end,
              'EFFORT_INTERVAL')


def union_ns(intervals):
    total = 0; right = 0
    for left, end in sorted(intervals):
        total += max(0, end - max(left, right))
        right = max(right, end)
    return total


def seconds(ns):
    return float(Decimal(ns) / Decimal(1000000000))


def summarize(meta, events):
    c.check_seal(meta)
    c.require(meta['schema_version'] == SCHEMA and meta['human_scope'] == HUMAN_SCOPE
              and type(meta['human_tracking_complete']) is bool and type(meta['retry_tracking_complete']) is bool
              and type(meta['binding']) is dict, 'EFFORT_METADATA')
    token(meta['run_id'])
    sources = meta['cost_sources']
    c.require(type(sources) is dict and 0 < len(sources) <= 32, 'EFFORT_COST_SOURCES')
    for name, currency in sources.items():
        token(name); c.require(currency in ('JPY', 'USD'), 'EFFORT_CURRENCY')
    c.require(type(events) is list and 1 <= len(events) <= MAX_EVENTS, 'EFFORT_EVENT_BOUND')
    previous = c.digest(meta); last_offset = 0; starts = {}; stages = []; human = []; costs = {}; retries = []
    for seq, event in enumerate(events):
        c.check_seal(event)
        c.require(set(event) == {'sequence', 'previous_sha256', 'offset_ns', 'kind', 'data', 'record_sha256'}
                  and type(event['sequence']) is int and event['sequence'] == seq
                  and event['previous_sha256'] == previous, 'EFFORT_TRACE_CHAIN')
        offset = event['offset_ns']; data = event['data']
        c.require(type(offset) is int and last_offset <= offset and type(data) is dict, 'EFFORT_CLOCK')
        last_offset = offset; previous = c.digest(event)
        if event['kind'] == 'STAGE_START':
            c.require(set(data) == {'id', 'name'} and data['id'] not in starts, 'EFFORT_STAGE_START')
            token(data['id']); token(data['name'])
            starts[data['id']] = (offset, data['name'], False)
        elif event['kind'] == 'STAGE_END':
            c.require(set(data) == {'id', 'status', 'cpu_parent_ns', 'cpu_children_ns', 'error_class'}
                      and data['id'] in starts and starts[data['id']][2] is False, 'EFFORT_STAGE_END')
            c.require(data['status'] in ('COMPLETE', 'FAILED')
                      and all(type(data[k]) is int and data[k] >= 0
                              for k in ('cpu_parent_ns', 'cpu_children_ns')), 'EFFORT_STAGE_STATUS')
            if data['error_class'] is not None: token(data['error_class'])
            c.require((data['error_class'] is None) == (data['status'] == 'COMPLETE'), 'EFFORT_STAGE_ERROR')
            start, name, _ = starts[data['id']]; starts[data['id']] = (start, name, True)
            stages.append(dict(id=data['id'], name=name, status=data['status'],
                elapsed_seconds=seconds(offset-start), cpu_parent_seconds=seconds(data['cpu_parent_ns']),
                cpu_children_seconds=seconds(data['cpu_children_ns']), error_class=data['error_class']))
        elif event['kind'] == 'INTERVENTION':
            c.require(set(data) == {'reason', 'active_intervals_ns', 'wait_interval_ns', 'basis'}, 'EFFORT_HUMAN_EVENT')
            token(data['reason'])
            c.require(data['basis'] in ('INSTRUMENTED', 'SELF_REPORTED', 'UNKNOWN'), 'EFFORT_HUMAN_BASIS')
            active = data['active_intervals_ns']
            if active is not None:
                c.require(type(active) is list and len(active) <= 64 and data['basis'] != 'UNKNOWN', 'EFFORT_HUMAN_ACTIVE')
                for value in active: interval(value, offset)
            else:
                c.require(data['basis'] == 'UNKNOWN', 'EFFORT_HUMAN_UNKNOWN')
            if data['wait_interval_ns'] is not None: interval(data['wait_interval_ns'], offset)
            human.append(data)
        elif event['kind'] == 'COST':
            c.require(set(data) == {'source', 'currency', *AMOUNTS, 'usage_known', 'invoice_reconciled'}
                      and data['source'] in sources and data['source'] not in costs
                      and data['currency'] == sources[data['source']], 'EFFORT_COST_IDENTITY')
            c.require(type(data['usage_known']) is bool and type(data['invoice_reconciled']) is bool,
                      'EFFORT_COST_KNOWN')
            for key in AMOUNTS:
                if data[key] is not None: number(data[key])
            c.require(data['usage_known'] or data['estimated'] is None, 'EFFORT_ESTIMATE_WITH_UNKNOWN_USAGE')
            c.require(not data['invoice_reconciled'] or data['invoiced'] is not None, 'EFFORT_INVOICE_MISSING')
            costs[data['source']] = data
        elif event['kind'] == 'RETRY':
            c.require(set(data) == {'reason', 'prior_stage_id', 'automatic'}
                      and type(data['automatic']) is bool and data['prior_stage_id'] in starts
                      and any(s['id'] == data['prior_stage_id'] and s['status'] == 'FAILED' for s in stages),
                      'EFFORT_RETRY_WITHOUT_FAILURE')
            token(data['reason']); retries.append(data)
        elif event['kind'] == 'TERMINAL':
            c.require(seq == len(events)-1 and set(data) == {'status', 'reason'}
                      and data['status'] in ('COMPLETE', 'STOPPED'), 'EFFORT_TERMINAL')
            if data['reason'] is not None: token(data['reason'])
        else:
            raise ValueError('EFFORT_EVENT_KIND')
    c.require(events[-1]['kind'] == 'TERMINAL', 'EFFORT_TERMINAL_REQUIRED')
    terminal = events[-1]['data']
    incomplete = [name for _, name, done in starts.values() if not done]
    
    c.require(terminal['status'] != 'COMPLETE' or not incomplete, 'EFFORT_FALSE_COMPLETION')
    active = union_ns([v for h in human for v in (h['active_intervals_ns'] or [])])
    active_known = meta['human_tracking_complete'] and all(h['active_intervals_ns'] is not None for h in human)
    wait = union_ns([h['wait_interval_ns'] for h in human if h['wait_interval_ns'] is not None])
    wait_known = meta['human_tracking_complete'] and all(h['wait_interval_ns'] is not None for h in human)
    vectors = {}
    for currency in sorted(set(sources.values())):
        names = [name for name in sources if sources[name] == currency]
        row = dict(expected_sources=len(names), observed_sources=sum(n in costs for n in names))
        for key in AMOUNTS:
            known = [number(costs[n][key]) for n in names if n in costs and costs[n][key] is not None]
            complete = len(known) == len(names)
            if key == 'invoiced': complete = complete and all(costs[n]['invoice_reconciled'] for n in names)
            row[key+'_known_subtotal'] = str(sum(known, Decimal('0')))
            row[key+'_total'] = str(sum(known, Decimal('0'))) if complete else None
        vectors[currency] = row
    return c.seal(dict(schema_version=SCHEMA, run_id=meta['run_id'], binding=deepcopy(meta['binding']),
        metadata_sha256=c.digest(meta), trace_terminal_sha256=previous, event_count=len(events),
        status=terminal['status'], stop_reason=terminal['reason'], elapsed_seconds=seconds(last_offset),
        stages=stages, incomplete_stages=incomplete, failed_stages=sum(s['status'] == 'FAILED' for s in stages),
        human_scope=HUMAN_SCOPE, human_tracking_complete=meta['human_tracking_complete'],
        observed_interventions=len(human), intervention_reasons=[h['reason'] for h in human],
        known_human_active_seconds=seconds(active), human_active_seconds=seconds(active) if active_known else None,
        known_human_wait_seconds=seconds(wait), human_wait_seconds=seconds(wait) if wait_known else None,
        human_time_outside_runner_unknown=True, cost_sources=deepcopy(sources),
        observed_costs=deepcopy(costs), cost_vectors=vectors,
        observed_retries=len(retries), observed_automatic_retries=sum(r['automatic'] for r in retries),
        retry_count=len(retries) if meta['retry_tracking_complete'] else None,
        retry_tracking_complete=meta['retry_tracking_complete'], reservations_are_not_invoice_charges=True,
        missing_costs_not_set_to_zero=True, measurement_grants_execution_authority=False))


def save(path, value):
    with Path(path).open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(c.canonical(value))


def read(directory):
    import json
    directory = Path(directory)
    c.require(not any(p.is_symlink() for p in (directory, *directory.parents)), 'EFFORT_SYMLINK')
    c.require(not any((directory/n).is_symlink() for n in ('metadata.json', 'summary.json', 'events')), 'EFFORT_SYMLINK')
    meta = json.loads((directory/'metadata.json').read_bytes())
    paths = sorted((directory/'events').iterdir())
    c.require(len(paths) <= MAX_EVENTS and all(p.name == f'{i:04d}.json' and not p.is_symlink()
                  for i, p in enumerate(paths)), 'EFFORT_EVENT_FILES')
    events = [json.loads(p.read_bytes()) for p in paths]
    result = summarize(meta, events)
    c.require(result == json.loads((directory/'summary.json').read_bytes()), 'EFFORT_SUMMARY_DRIFT')
    return result


class Recorder:
    def __init__(self, directory, *, run_id, binding, cost_sources, human_tracking_complete=False,
                 retry_tracking_complete=False,
                 clock=time.monotonic_ns, cpu_clock=time.process_time_ns):
        token(run_id)
        self.directory = Path(directory).absolute()
        c.require(not any(p.is_symlink() for p in (self.directory, *self.directory.parents)), 'EFFORT_SYMLINK')
        c.require(type(binding) is dict and type(human_tracking_complete) is bool
                  and type(retry_tracking_complete) is bool, 'EFFORT_METADATA')
        c.require(type(cost_sources) is dict and 0 < len(cost_sources) <= 32, 'EFFORT_COST_SOURCES')
        for name, currency in cost_sources.items():
            token(name); c.require(currency in ('JPY', 'USD'), 'EFFORT_CURRENCY')
        self.meta = c.seal(dict(schema_version=SCHEMA, run_id=run_id, binding=deepcopy(binding),
            cost_sources=deepcopy(cost_sources), human_tracking_complete=human_tracking_complete,
            retry_tracking_complete=retry_tracking_complete,
            human_scope=HUMAN_SCOPE, created_at_jst=datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds')))
        self.directory.mkdir(mode=0o700)
        (self.directory/'events').mkdir(mode=0o700)
        save(self.directory/'metadata.json', self.meta)
        self.clock = clock; self.cpu_clock = cpu_clock; self.origin = clock()
        self.events = []; self.closed = False; self.stage_index = 0

    def offset(self):
        return self.clock() - self.origin

    def emit(self, kind, data):
        c.require(not self.closed and len(self.events) < MAX_EVENTS-(kind != 'TERMINAL'), 'EFFORT_CLOSED_OR_BOUND')
        previous = c.digest(self.events[-1]) if self.events else c.digest(self.meta)
        event = c.seal(dict(sequence=len(self.events), previous_sha256=previous,
                           offset_ns=self.offset(), kind=kind, data=deepcopy(data)))
        c.require(type(event['offset_ns']) is int and event['offset_ns'] >= (
            self.events[-1]['offset_ns'] if self.events else 0), 'EFFORT_CLOCK')
        prefix = self.events + [event]
        if kind != 'TERMINAL':
            prefix += [c.seal(dict(sequence=len(prefix), previous_sha256=c.digest(event),
                offset_ns=event['offset_ns'], kind='TERMINAL', data=dict(status='STOPPED', reason=None)))]
        summarize(self.meta, prefix)
        save(self.directory/'events'/f'{len(self.events):04d}.json', event)
        self.events.append(event)

    @contextmanager
    def stage(self, name):
        token(name)
        stage_id = f's{self.stage_index:04d}'; self.stage_index += 1
        self.emit('STAGE_START', dict(id=stage_id, name=name))
        cpu = self.cpu_clock(); usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        children = usage.ru_utime + usage.ru_stime
        error = None
        try:
            yield
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            self.emit('STAGE_END', dict(id=stage_id, status='COMPLETE' if error is None else 'FAILED',
                cpu_parent_ns=max(0, self.cpu_clock()-cpu),
                cpu_children_ns=max(0, round((usage.ru_utime+usage.ru_stime-children)*1000000000)),
                error_class=error))

    def intervention(self, reason, *, active_intervals_ns=None, wait_interval_ns=None, basis='UNKNOWN'):
        token(reason)
        self.emit('INTERVENTION', dict(reason=reason, active_intervals_ns=active_intervals_ns,
                                      wait_interval_ns=wait_interval_ns, basis=basis))

    def cost(self, source, *, reserved=None, estimated=None, invoiced=None,
             usage_known=False, invoice_reconciled=False):
        c.require(source in self.meta['cost_sources'], 'EFFORT_COST_SOURCE')
        self.emit('COST', dict(source=source, currency=self.meta['cost_sources'][source],
            reserved=reserved, estimated=estimated, invoiced=invoiced,
            usage_known=usage_known, invoice_reconciled=invoice_reconciled))

    def retry(self, reason, prior_stage_id, *, automatic):
        self.emit('RETRY', dict(reason=reason, prior_stage_id=prior_stage_id, automatic=automatic))

    def finish(self, status='COMPLETE', reason=None):
        self.emit('TERMINAL', dict(status=status, reason=reason))
        self.closed = True
        result = summarize(self.meta, self.events)
        save(self.directory/'summary.json', result)
        return result
