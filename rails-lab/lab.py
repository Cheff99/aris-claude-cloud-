#!/usr/bin/env python3
"""Rails lab v2 (6 Oct 2026) -- rebuilt after the independent review (findings A1-A16, B1-B23, C1-C13).

David: "Rail every single point ... log every single portion ... ledger everything."
Every role in the mining pipeline (rails.json) is a rail; every step of every run goes to an append-only ledger.
  python3 lab.py preflight --models M,..        binary, key, credit, zero-retention endpoints, cases -- before spending
  python3 lab.py run --roles 1,2 --models plan:sonnet,or:x [--cases synthetic] [--repeats 2] [--council or:a,plan:b]
                     [--resume RID] [--workers 4]
  python3 lab.py summary [RID] [--include-mock]  per role x model: coverage, failures, scores (+95% CI), cost, latency
  python3 lab.py rejudge RID --council or:a,..   council-judge saved outputs again (refuses if cases changed)
  python3 lab.py dryrun                           mock model, separate ledger: proves every rail end to end
Models: mock | plan:<opus|sonnet|haiku|fable> (claude -p --safe-mode: no CLAUDE.md, hooks, skills or user settings, neutral system prompt) | or:<openrouter id> (ZDR only)
"""
import os, sys, json, time, re, hashlib, uuid, subprocess, urllib.request, urllib.error, datetime, argparse, fcntl, random
import platform, traceback, threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RAILS = {r['id']: r for r in json.load(open(os.path.join(HERE, 'rails.json'), encoding='utf-8'))}
LEDGER = os.path.join(HERE, 'ledger.jsonl')
RAW = os.path.join(HERE, 'raw')
CASES = os.path.join(HERE, 'cases')
OR_KEY = '/root/.aris/secrets/openrouter.txt'
SYS = 'You are a careful, literal assistant. Follow the task exactly and answer in the requested format only.'
TEMP = 0
COUNCIL_ROLES = (9, 10)          # plus every fact_check role
_lock = threading.Lock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def h(s):
    return hashlib.sha256((s or '').encode('utf-8')).hexdigest()[:12]


def ledger(run, stage, **kw):
    ev = {'ts': now(), 'run': run, 'stage': stage, **kw}
    data = (json.dumps(ev, ensure_ascii=False, default=str) + '\n').encode('utf-8')
    with _lock:
        fd = os.open(LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    return ev


def read_ledger(path=None):
    evs, bad = [], 0
    p = path or LEDGER
    if not os.path.exists(p):
        return evs, bad
    with open(p, encoding='utf-8', errors='replace') as f:
        for l in f:
            try:
                evs.append(json.loads(l))
            except ValueError:
                bad += 1
    return evs, bad


def family(model):
    if model.startswith('plan:') or 'anthropic/' in model:
        return 'anthropic'
    if model == 'mock':
        return 'mock'
    return model.split(':', 1)[-1].split('/')[0]


# ---------------- errors ----------------
class CallError(Exception):
    def __init__(self, msg, kind='error', retry=False, wait=0):
        super().__init__(msg)
        self.kind, self.retry, self.wait = kind, retry, wait


class LimitHit(Exception):
    pass


# ---------------- model adapters ----------------
def call_mock(prompt, case):
    t = case['truth']
    if 'items' in t:
        out = [{'quote': x} for x in t['items'][:-1]] + [{'quote': 'an invented statement that is not in the text'}]
    elif 'labels' in t:
        ks = list(t['labels'])
        lab = lambda v: v if isinstance(v, str) else v[0]
        out = [{'item_id': k, 'label': lab(t['labels'][k])} for k in ks[:-1]] + [{'item_id': ks[-1], 'label': 'WRONG'}]
    elif 'conflicts' in t:
        out = [{'quotes': c['pair'], 'governs': c['governs']} for c in t['conflicts'][:-1]]
    else:
        out = '\n'.join('- ' + f['prop'] for f in t.get('facts', [])[:-1]) + '\n- the value is 999'
    txt = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return txt, {'route': 'mock', 'in': len(prompt) // 4, 'out': len(txt) // 4, 'usd': 0.0, 'usd_is_notional': True}, \
        {'request': {'model': 'mock'}, 'response': {'result': txt}}


def call_plan(model, prompt, timeout=900):
    work = '/tmp/rails-lab-claude-cwd'           # empty dir: no project CLAUDE.md, no repo context
    os.makedirs(work, exist_ok=True)
    cmd = ['claude', '-p', '--model', model, '--safe-mode', '--setting-sources', '', '--no-session-persistence', '--tools', '',
           '--system-prompt', SYS, '--output-format', 'json']
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=work)
    except subprocess.TimeoutExpired:
        raise CallError(f'timeout after {timeout}s', 'timeout', retry=True)
    try:
        j = json.loads(p.stdout or '{}')
    except ValueError:
        j = {'unparsed_stdout': (p.stdout or '')[:3000]}
    txt = j.get('result') or ''
    low = (txt + ' ' + (p.stderr or '')).lower()
    if any(s in low for s in ('usage limit', 'limit reached', 'rate limit', 'limit will reset')) and len(txt) < 800:
        raise LimitHit((txt or p.stderr or '')[:300])
    if p.returncode != 0 or j.get('is_error') or j.get('subtype') not in (None, 'success') or 'unparsed_stdout' in j:
        raise CallError(f"claude error rc={p.returncode} subtype={j.get('subtype')} {txt[:200]} {(p.stderr or '')[:200]}",
                        'error', retry=p.returncode != 0 and not j)
    u = j.get('usage') or {}
    cc = u.get('cache_creation') or {}
    use = {'route': 'claude-plan', 'model_requested': model, 'models_served': list((j.get('modelUsage') or {}).keys()),
           'in_fresh': u.get('input_tokens'), 'in_cache_read': u.get('cache_read_input_tokens'),
           'in_cache_write': u.get('cache_creation_input_tokens'), 'in_cache_write_1h': cc.get('ephemeral_1h_input_tokens'),
           'in_cache_write_5m': cc.get('ephemeral_5m_input_tokens'), 'out': u.get('output_tokens'),
           'service_tier': u.get('service_tier'),
           'in': sum(x or 0 for x in (u.get('input_tokens'), u.get('cache_read_input_tokens'), u.get('cache_creation_input_tokens'))),
           'usd': j.get('total_cost_usd'), 'usd_is_notional': True, 'duration_ms': j.get('duration_ms'),
           'duration_api_ms': j.get('duration_api_ms'), 'num_turns': j.get('num_turns'), 'stop_reason': j.get('stop_reason'),
           'exit_code': p.returncode, 'stderr_chars': len(p.stderr or ''), 'wall_s': round(time.time() - t0, 2),
           'temperature': 'cli-default', 'reasoning': 'cli-default', 'system_prompt_hash': h(SYS)}
    if j.get('num_turns') not in (None, 1):
        use['warning'] = f"num_turns={j.get('num_turns')} (expected 1)"
    return txt, use, {'request': {'argv': cmd, 'prompt_chars': len(prompt)}, 'response': j, 'stderr': (p.stderr or '')[:3000]}


_OR_KEY = None
_MAXTOK = {}


def or_key():
    global _OR_KEY
    if _OR_KEY is None:
        _OR_KEY = open(OR_KEY).read().strip()
    return _OR_KEY


PINS = json.load(open(os.path.join(HERE, 'providers.json'))) if os.path.exists(os.path.join(HERE, 'providers.json')) else {}
CAP = {'set_match': 16000, 'fact_check': 12000, 'conflict_match': 8000, 'label_match': 6000}   # stops runaway loops


def call_or(model, prompt, timeout=900, cap=32000):
    body = {'model': model, 'max_tokens': min(cap, _MAXTOK.get(model) or cap), 'temperature': TEMP,
            'messages': [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': prompt}],
            'provider': {'data_collection': 'deny', 'zdr': True, **({'order': [PINS[model]], 'allow_fallbacks': False} if model in PINS else {})},
            'usage': {'include': True}}
    t0 = time.time()
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + or_key(), 'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.status
    except urllib.error.HTTPError as e:
        bodytxt = e.read().decode('utf-8', 'replace')[:1000]
        if e.code in (402,):
            raise LimitHit(f'OpenRouter 402 (credit): {bodytxt[:200]}')
        if e.code == 429 or e.code >= 500:
            ra = e.headers.get('Retry-After')
            raise CallError(f'HTTP {e.code}: {bodytxt}', 'http', retry=True, wait=float(ra) if ra and ra.isdigit() else 0)
        raise CallError(f'HTTP {e.code}: {bodytxt}', 'http', retry=False)
    except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
        raise CallError(f'network/timeout: {e!r}', 'timeout', retry=True)
    try:
        r = json.loads(raw)
    except ValueError:
        raise CallError(f'non-JSON body: {raw[:300]!r}', 'error', retry=True)
    if 'error' in r or not r.get('choices'):
        raise CallError(f"OpenRouter error body: {json.dumps(r.get('error', r))[:600]}", 'error', retry=True)
    ch = r['choices'][0]
    if ch.get('error'):
        raise CallError(f"choice error: {json.dumps(ch['error'])[:600]}", 'error', retry=True)
    u = r.get('usage', {})
    gen = {}
    for wait in (1.5, 4):
        time.sleep(wait)
        try:
            greq = urllib.request.Request('https://openrouter.ai/api/v1/generation?id=' + r.get('id', ''),
                                          headers={'Authorization': 'Bearer ' + or_key()})
            gen = json.loads(urllib.request.urlopen(greq, timeout=60).read()).get('data', {})
            break
        except Exception as e:  # noqa: BLE001
            gen = {'stats_error': repr(e)[:200]}
    use = {'route': 'openrouter-zdr', 'model_requested': model, 'model_served': r.get('model'), 'provider': r.get('provider'),
           'in': u.get('prompt_tokens'), 'in_cached': (u.get('prompt_tokens_details') or {}).get('cached_tokens'),
           'out': u.get('completion_tokens'), 'reasoning_tokens': (u.get('completion_tokens_details') or {}).get('reasoning_tokens'),
           'usd': u.get('cost') if u.get('cost') is not None else gen.get('total_cost'), 'usd_is_notional': False,
           'finish_reason': ch.get('finish_reason'), 'native_finish_reason': ch.get('native_finish_reason'), 'http_status': status,
           'wall_s': round(time.time() - t0, 2), 'gen_latency_ms': gen.get('latency'), 'gen_time_ms': gen.get('generation_time'),
           'gen_native_in': gen.get('native_tokens_prompt'), 'gen_native_out': gen.get('native_tokens_completion'),
           'gen_native_reasoning': gen.get('native_tokens_reasoning'), 'gen_provider': gen.get('provider_name'),
           'gen_total_cost': gen.get('total_cost'), 'gen_upstream_id': gen.get('upstream_id'), 'temperature': TEMP,
           'reasoning': 'provider-default', 'max_tokens': body['max_tokens'], 'system_prompt_hash': h(SYS)}
    req_logged = {k: v for k, v in body.items() if k != 'messages'}
    req_logged['prompt_chars'] = len(prompt)
    return (ch.get('message') or {}).get('content') or '', use, {'request': req_logged, 'response': r, 'generation_stats': gen}


def call(model, prompt, case, run, role, repeat, cap=32000):
    attempt = 0
    while True:
        attempt += 1
        try:
            if model == 'mock':
                return call_mock(prompt, case) + (attempt,)
            kind, name = model.split(':', 1)
            return (call_plan(name, prompt) if kind == 'plan' else call_or(name, prompt, cap=cap)) + (attempt,)
        except LimitHit:
            raise
        except CallError as e:
            last = not e.retry or attempt >= (2 if e.kind == 'timeout' else 4)
            ledger(run, 'error' if last else 'retry', role=role, case=case['case_id'], model=model, repeat=repeat,
                   attempt=attempt, kind=e.kind, error=str(e)[:1000])
            if last:
                raise
            time.sleep(e.wait or min(120, 5 * 2 ** attempt + random.random() * 3))


# ---------------- parsing ----------------
TOK = re.compile(r'\w+', re.UNICODE)


def toks(s):
    if not isinstance(s, str):
        s = json.dumps(s, ensure_ascii=False) if s is not None else ''
    return [t.lower() for t in TOK.findall(s)]


def norm(s):
    return ' '.join(toks(s))


ALIASES = ('quote', 'quotes', 'text', 'statement', 'item', 'finding', 'gap', 'error', 'mistake')


def extract_json(txt):
    """strip fences; whole-text JSON, else the longest decodable [ or { block. returns (obj, route)."""
    s = re.sub(r'```(?:json)?', '', txt or '').strip()
    try:
        return json.loads(s), 'whole'
    except ValueError:
        pass
    dec, best = json.JSONDecoder(), None
    for i, ch in enumerate(s):
        if ch in '[{':
            try:
                obj, end = dec.raw_decode(s[i:])
                if best is None or end > best[1]:
                    best = (obj, end)
            except ValueError:
                continue
    return (best[0], 'scan') if best else (None, 'fail')


def as_items(obj):
    """flatten to a list of strings: list of str / dicts with alias keys, or a dict wrapping one list."""
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list)]
        obj = lists[0] if len(lists) == 1 else [obj]
    out = []
    for x in obj if isinstance(obj, list) else []:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for k in ALIASES:
                if k in x:
                    v = x[k]
                    out.extend(v if isinstance(v, list) else [v])
                    break
            else:
                out.append(json.dumps(x, ensure_ascii=False))
    return [o for o in out if isinstance(o, str)]


def as_labels(obj):
    if isinstance(obj, dict) and not any(k in obj for k in ('item_id', 'label')):
        lists = [v for v in obj.values() if isinstance(v, list)]
        if len(lists) == 1 and all(isinstance(x, dict) for x in lists[0]):
            obj = lists[0]
        else:
            return {str(k): v for k, v in obj.items()}
    if isinstance(obj, dict):
        obj = [obj]
    res = {}
    for x in obj if isinstance(obj, list) else []:
        if isinstance(x, dict):
            res[str(x.get('item_id', x.get('id', '')))] = x.get('label', x.get('labels'))
    return res


def norm_label(v, is_set=False):
    if isinstance(v, list):
        v = '+'.join(str(x) for x in v)
    s = re.sub(r'\s*\|\s*', '|', str(v if v is not None else '').strip().upper())
    s = re.sub(r'\s+', ' ', s)
    if is_set:
        return '+'.join(sorted({x.strip().replace(' ', '_') for x in re.split(r'[+,]', s) if x.strip()}))
    return s


# ---------------- scoring ----------------
def f1_match(a, b):
    A, B = toks(a), toks(b)
    if not A or not B or not (0.5 <= len(A) / len(B) <= 2):
        return 0.0
    if {t for t in A if t.isdigit()} - set(B):        # every number in the truth must be in the output
        return 0.0
    common = sum(min(A.count(t), B.count(t)) for t in set(A))
    if not common:
        return 0.0
    p, r = common / len(B), common / len(A)
    return 2 * p * r / (p + r)


def match_one_to_one(truth, got, thr=0.6, src=None):
    pairs = sorted(((f1_match(t, g), i, j) for i, t in enumerate(truth) for j, g in enumerate(got)), reverse=True)
    ti, gi, m = set(), set(), {}
    for s, i, j in pairs:
        if s < thr or i in ti or j in gi:
            continue
        if src is not None and norm(got[j]) not in src:   # verbatim required: must be copied from the source
            continue
        ti.add(i); gi.add(j); m[i] = (j, round(s, 3))
    return m


NEG = {'not', 'no', 'never', 'old', 'older', 'replaced', 'replaces', 'superseded', 'supersedes', 'instead', 'previously', 'previous',
       'was', 'earlier', 'formerly', 'wrong', 'rather', 'contested', 'disputed', 'contradicted', 'contradicts', 'contradiction',
       'conflict', 'conflicts', 'unconfirmed', 'rejected', 'dropped', 'overridden', 'overrides', 'updated', 'changed', 'suggested',
       'proposed', 'claimed', 'paraphrase', 'paraphrased', 'expired', 'obsolete', 'retired', 'ignore', 'ignored', 'vs', 'versus'}
SENT = re.compile(r'\n+|(?<=[.!?])\s+')
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')


def fact_present(fact, T, window=None, negation_aware=False):
    """all required tokens appear inside one window of tokens. For forbidden claims the check runs clause by clause, and a
    clause carrying a negation or flag word (contested, superseded, earlier...) is reporting the claim, not asserting it."""
    need = [n.lower() for n in (fact.get('tokens') or toks(fact.get('prop') or fact.get('claim') or ''))]
    if not need:
        return False
    if negation_aware:
        text = T if isinstance(T, str) else ' '.join(T)
        for sent in SENT.split(text):           # quoted text is a citation, not an assertion; flagged sentences report
            if NEG & set(toks(sent)):
                continue
            ct = toks(QUOTED.sub(' ', sent))
            if ct and fact_present(fact, ct, window or len(set(need)) + 2):
                return True
        return False
    T = toks(T) if isinstance(T, str) else T
    if window is None:
        window = 2 * len(set(need)) + 2
    pos = {n: [i for i, t in enumerate(T) if t == n] for n in set(need)}
    if any(not v for v in pos.values()):
        return False
    for start in pos[need[0]]:
        span = []
        for n in set(need):
            near = [i for i in pos[n] if abs(i - start) <= window]
            if not near:
                break
            span.append(min(near, key=lambda i: abs(i - start)))
        else:
            if max(span) - min(span) <= window:
                return True
    return False


LISTNUM = re.compile(r'^\s*(\d+[.)]|[-*•]|\|)\s*')


def invented_numbers(txt, case):
    allowed = set(toks(json.dumps(case['input'], ensure_ascii=False)))
    body = '\n'.join(LISTNUM.sub('', l) for l in (txt or '').splitlines())
    body = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', ' ', body)
    return sorted({t for t in toks(body) if t.isdigit() and t not in allowed})


def score(rail, case, txt):
    t, s = case['truth'], rail['scorer']
    if s == 'set_match':
        obj, route = extract_json(txt)
        got = as_items(obj)
        src = norm(case['input'].get('text', '')) if t.get('verbatim_required') else None
        m = match_one_to_one(t['items'], got, src=src)
        used = {v[0] for v in m.values()}
        rest = [g for j, g in enumerate(got) if j not in used]
        also = match_one_to_one(t.get('also_ok', []), rest)
        res = {'recall': len(m) / max(len(t['items']), 1), 'precision': (len(m) + len(also)) / len(got) if got else 0.0,
               'hits': len(m), 'truth_n': len(t['items']), 'out_n': len(got), 'extras': len(got) - len(m) - len(also),
               'parse_route': route}
        if src is not None and got:
            res['verbatim_rate'] = sum(norm(g) in src for g in got) / len(got)
        return res, {'matched': {str(k): v for k, v in m.items()}, 'got': got}
    if s == 'conflict_match':
        obj, route = extract_json(txt)
        conf = obj if isinstance(obj, list) else (next((v for v in obj.values() if isinstance(v, list)), []) if isinstance(obj, dict) else [])
        conf = [x for x in conf if isinstance(x, dict)]
        found = gov = 0
        used = set()
        for c in t['conflicts']:
            for j, x in enumerate(conf):
                if j in used:
                    continue
                qs = x.get('quotes') or x.get('pair') or [x.get('a'), x.get('b')]
                qs = [q for q in (qs if isinstance(qs, list) else []) if isinstance(q, str)]
                if len(match_one_to_one(c['pair'], qs)) == 2:
                    used.add(j); found += 1
                    gov += f1_match(c['governs'], str(x.get('governs', ''))) >= 0.6
                    break
        n = len(t['conflicts'])
        return {'recall': found / n, 'governs_right': gov / n, 'precision': found / len(conf) if conf else 0.0,
                'out_n': len(conf), 'parse_route': route}, {'used': sorted(used)}
    if s == 'label_match':
        obj, route = extract_json(txt)
        iset = t.get('label_is_set')
        got = {k: norm_label(v, iset) for k, v in as_labels(obj).items()}
        ok, traps_ok, per = 0, 0, {}
        for k, v in t['labels'].items():
            acc = {norm_label(x, iset) for x in (v if isinstance(v, list) else [v])} if not iset else {norm_label(v, True)}
            right = got.get(str(k)) in acc
            ok += right
            per[k] = (got.get(str(k)), sorted(acc), right)
            traps_ok += right and k in t.get('traps', [])
        n = len(t['labels'])
        res = {'accuracy': ok / max(n, 1), 'right': ok, 'truth_n': n, 'unknown_ids': len(set(got) - set(map(str, t['labels']))),
               'parse_route': route}
        if t.get('traps'):
            res['trap_accuracy'] = traps_ok / len(t['traps'])
        return res, {'per_item': per}
    if s == 'fact_check':
        T = toks(txt)
        facts = t.get('facts', [])
        kept = [f['prop'] for f in facts if fact_present(f, T)]
        forb = [f['claim'] for f in t.get('forbidden', []) if fact_present(f, txt, negation_aware=True)]
        inv = invented_numbers(txt, case)
        res = {'facts_kept': len(kept) / max(len(facts), 1), 'forbidden_present': len(forb), 'invented_numbers': len(inv)}
        if t.get('also_ok_facts'):
            res['also_ok_kept'] = sum(fact_present(f, T) for f in t['also_ok_facts'])
        if t.get('headline'):
            hf = next((f for f in facts if f['prop'] == t['headline']), {'prop': t['headline']})
            res['headline_right'] = float(fact_present(hf, T))
        return res, {'kept': kept, 'forbidden': forb, 'invented': inv}
    return {}, {}


def mechanical(role, case):
    if role == 19:
        truth = {q: sp for q, sp in case['truth']['bank']}
        found = re.findall(r'\*\*(David|Aris|Rohit \(forwarded\))\*\* · [0-9-]+\n(.+)', case['input']['text'])
        hdr = {'David': 'DAVID', 'Aris': 'ARIS-LEAD', 'Rohit (forwarded)': '3RD'}
        ok = sum(1 for who, x in found if truth.get(x.strip()) == hdr[who])
        return {'accuracy': ok / max(len(found), 1), 'checked': len(found), 'self_check': True}
    if role == 22:
        nums_src = set(re.findall(r'\d+', re.sub(r'\d{4}-\d{2}-\d{2}', ' ', case['input']['findings'])))
        flagged = [r for r in case['input']['rules'] if any(n not in nums_src for n in re.findall(r'\d+', r))]
        want = set(case['truth']['flag'])
        hit = len(want & set(flagged))
        return {'recall': hit / max(len(want), 1), 'precision': hit / len(flagged) if flagged else 1.0, 'flagged': flagged,
                'self_check': True, 'limit': 'cannot see a superseded number that still appears in the findings'}
    return {}


# ---------------- council (judges from other families) ----------------
def judge_once(run, judge, rail, case, txt, cand, repeat):
    facts = [f['prop'] for f in case['truth'].get('facts', [])] or case['truth'].get('items', [])
    forb = [f['claim'] for f in case['truth'].get('forbidden', [])]
    pr = ("You are a strict grader. For each EXPECTED FACT answer 1 if the CANDIDATE states it with the same meaning AND the same "
          "values, else 0. For each FORBIDDEN CLAIM answer 1 if the candidate asserts it as true (mentioning it as rejected or "
          'replaced does not count), else 0. Answer only JSON: {"present": [0 or 1, ...], "forbidden": [0 or 1, ...]} with one entry '
          "per item, in order.\n\nEXPECTED FACTS:\n" + json.dumps(facts, ensure_ascii=False) + "\n\nFORBIDDEN CLAIMS:\n" +
          json.dumps(forb, ensure_ascii=False) + "\n\n=== CANDIDATE ===\n" + txt[:60000] + "\n=== END ===")
    try:
        out, use, _, _att = call(judge, pr, case, run, rail['id'], repeat)
    except LimitHit:
        raise
    except Exception as e:  # noqa: BLE001
        ledger(run, 'judge-error', role=rail['id'], case=case['case_id'], candidate=cand, judge=judge, repeat=repeat, error=repr(e)[:400])
        return None
    obj, _ = extract_json(out)
    pres = obj.get('present') if isinstance(obj, dict) else None
    forbv = obj.get('forbidden') if isinstance(obj, dict) else None
    strict = lambda x: x is True or x == 1 or (isinstance(x, str) and x.strip() in ('1', 'true', 'True'))
    ok = isinstance(pres, list) and len(pres) == len(facts) and (not forb or (isinstance(forbv, list) and len(forbv) == len(forb)))
    kept = sum(1 for x in pres if strict(x)) / max(len(facts), 1) if ok else None
    fb = sum(1 for x in forbv if strict(x)) if ok and forb else (0 if ok else None)
    ledger(run, 'judge', role=rail['id'], case=case['case_id'], candidate=cand, judge=judge, repeat=repeat, valid=ok,
           kept=kept, forbidden=fb, truncated=len(txt) > 60000, raw_out=out[:2000],
           **{f'use_{k}': v for k, v in use.items() if k in ('usd', 'usd_is_notional', 'in', 'out', 'wall_s')})
    return (kept, fb) if ok else None


def council_score(run, council, rail, case, txt, cand, repeat):
    eligible = [j for j in council if family(j) != family(cand)]
    votes = [v for v in (judge_once(run, j, rail, case, txt, cand, repeat) for j in eligible) if v]
    if not votes:
        return {'council_n': 0, 'council_eligible': len(eligible)}
    kept = sorted(v[0] for v in votes)
    fb = sorted(v[1] for v in votes if v[1] is not None)
    med = lambda xs: (xs[(len(xs) - 1) // 2] + xs[len(xs) // 2]) / 2
    return {'council_n': len(votes), 'council_eligible': len(eligible), 'council_kept': med(kept),
            'council_forbidden': med(fb) if fb else None, 'council_spread': kept[-1] - kept[0]}


def wants_council(rail):
    return rail['scorer'] == 'fact_check' or rail['id'] in COUNCIL_ROLES


# ---------------- prompts ----------------
def prompt_for(rail, case):
    inp = dict(case['input'])
    blocks = []
    for k in ('text', 'findings', 'passage'):
        if k in inp and isinstance(inp[k], str):
            blocks.append(f"=== {k.upper()} START ===\n{inp.pop(k)}\n=== {k.upper()} END ===")
    fmt = inp.pop('answer_format', None) or rail['out']
    return (f"ROLE: {rail['name']}\nTASK: {rail['task']}\nOUTPUT: {fmt}. Answer with that and nothing else.\n\n"
            f"CASE DATA (JSON):\n{json.dumps(inp, ensure_ascii=False, indent=1)}\n\n" + '\n\n'.join(blocks))


# ---------------- run ----------------
def run_one(run, rail, case, model, repeat, council):
    pr = prompt_for(rail, case)
    ledger(run, 'prepare', role=rail['id'], case=case['case_id'], model=model, repeat=repeat, prompt_hash=h(pr), prompt_chars=len(pr),
           kind='mock' if model == 'mock' else 'real')
    t0 = time.time()
    try:
        txt, use, rawobj, attempts = call(model, pr, case, run, rail['id'], repeat, cap=CAP.get(rail['scorer'], 32000))
    except LimitHit:
        raise
    except Exception as e:  # noqa: BLE001 -- a failure is scored as 0 (coverage), never dropped
        ledger(run, 'score', role=rail['id'], case=case['case_id'], model=model, repeat=repeat, failed=True, failure=repr(e)[:300])
        return
    d = os.path.join(RAW, run, str(rail['id']), case['case_id'])
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, re.sub(r'[^A-Za-z0-9._-]', '_', model) + f'.r{repeat}')
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(txt)
    with open(base + '.prompt.txt', 'w', encoding='utf-8') as f:
        f.write(pr)
    with open(base + '.exchange.json', 'w', encoding='utf-8') as f:
        json.dump(rawobj, f, indent=1, ensure_ascii=False, default=str)
    ledger(run, 'call', role=rail['id'], case=case['case_id'], model=model, repeat=repeat, attempts=attempts, secs=round(time.time() - t0, 2),
           out_chars=len(txt), out_hash=h(txt), raw=os.path.relpath(base + '.txt', HERE), **{f'use_{k}': v for k, v in use.items()})
    if not txt.strip():
        ledger(run, 'empty', role=rail['id'], case=case['case_id'], model=model, repeat=repeat)
    if use.get('finish_reason') in ('length', 'error') or use.get('stop_reason') == 'max_tokens':
        ledger(run, 'truncated', role=rail['id'], case=case['case_id'], model=model, repeat=repeat,
               finish_reason=use.get('finish_reason') or use.get('stop_reason'))
    sc, det = ({}, {}) if case['truth'].get('council_only') else score(rail, case, txt)
    ledger(run, 'items', role=rail['id'], case=case['case_id'], model=model, repeat=repeat, detail=det)
    if council and wants_council(rail):
        sc.update(council_score(run, council, rail, case, txt, model, repeat))
    ledger(run, 'score', role=rail['id'], case=case['case_id'], model=model, repeat=repeat, failed=False, **sc)


def load_cases(src, roles):
    cs = []
    for r in roles:
        p = os.path.join(CASES, src, f'{r:02d}.jsonl')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                cs += [json.loads(l) for l in f if l.strip()]
    return cs


def case_hashes(src):
    d = os.path.join(CASES, src)
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, f), encoding='utf-8') as fh:
            out[f] = h(fh.read())
    return out


def preflight(models, src, roles):
    probs = []
    if any(m.startswith('plan:') for m in models) and subprocess.run(['which', 'claude'], capture_output=True).returncode:
        probs.append('claude binary not on PATH')
    ors = [m.split(':', 1)[1] for m in models if m.startswith('or:')]
    if ors:
        if not os.path.exists(OR_KEY):
            probs.append('OpenRouter key missing')
        else:
            try:
                zdr = json.loads(urllib.request.urlopen('https://openrouter.ai/api/v1/endpoints/zdr', timeout=60).read())
                zdr = zdr.get('data', zdr) if isinstance(zdr, dict) else zdr
                ok = {e.get('model_id') or e.get('model') for e in zdr if isinstance(e, dict)}
                mods = json.loads(urllib.request.urlopen('https://openrouter.ai/api/v1/models', timeout=60).read())['data']
                for m in mods:
                    _MAXTOK[m['id']] = (m.get('top_provider') or {}).get('max_completion_tokens')
                known = {m['id'] for m in mods}
                for m in ors:
                    if m not in known:
                        probs.append(f'{m}: unknown model id')
                    elif ok and m not in ok:
                        probs.append(f'{m}: no zero-retention endpoint')
                cred = json.loads(urllib.request.urlopen(urllib.request.Request('https://openrouter.ai/api/v1/credits',
                                  headers={'Authorization': 'Bearer ' + or_key()}), timeout=60).read())['data']
                left = (cred.get('total_credits') or 0) - (cred.get('total_usage') or 0)
                if left < 1:
                    probs.append(f'OpenRouter credit low: ${left:.2f}')
            except Exception as e:  # noqa: BLE001
                probs.append(f'OpenRouter check failed: {e!r}'[:200])
    if not load_cases(src, roles):
        probs.append(f'no cases in cases/{src}')
    return probs


def run(roles, models, src='synthetic', repeats=1, council=None, resume=None, workers=1, force=False):
    probs = preflight(models + (council or []), src, roles)
    if probs and not force:
        print('PREFLIGHT FAILED:', *probs, sep='\n  ')
        return None
    rid = resume or (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4])
    done = set()
    if resume:
        evs, _ = read_ledger()
        st = next((e for e in evs if e['run'] == rid and e['stage'] == 'run-start'), None)
        if not st or st.get('case_hashes') != case_hashes(src):
            print('no such run, or cases changed since it started -- refusing to resume')
            return None
        done = {(e['role'], e['case'], e['model'], e.get('repeat', 0)) for e in evs if e['run'] == rid and e['stage'] == 'score'}
    try:
        cv = subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        cv = None
    ledger(rid, 'run-resume' if resume else 'run-start', roles=roles, models=models, council=council, cases=src, repeats=repeats,
           workers=workers, host=platform.node(), python=platform.python_version(), claude_cli=cv, system_prompt=SYS,
           temperature=TEMP, lab_hash=h(open(__file__, encoding='utf-8').read()),
           rails_hash=h(open(os.path.join(HERE, 'rails.json'), encoding='utf-8').read()),
           case_hashes=case_hashes(src), preflight=probs, kind='mock' if models == ['mock'] else 'real')
    jobs = []
    for c in load_cases(src, roles):
        rail = RAILS[c['role']]
        if rail['scorer'] == 'mechanical':
            if (rail['id'], c['case_id'], 'none', 0) not in done:
                ledger(rid, 'score', role=rail['id'], case=c['case_id'], model='none', repeat=0, failed=False, **mechanical(rail['id'], c))
            continue
        if rail['scorer'] == 'none':
            continue
        for m in models:
            for rp in range(repeats):
                if (rail['id'], c['case_id'], m, rp) not in done:
                    jobs.append((rail, c, m, rp))
    random.Random(7).shuffle(jobs)
    stop = threading.Event()

    def work(j):
        if stop.is_set():
            return
        try:
            run_one(rid, *j, council)
        except LimitHit as e:
            stop.set()
            ledger(rid, 'paused-limit', role=j[0]['id'], case=j[1]['case_id'], model=j[2], note=str(e)[:300])
        except Exception as e:  # noqa: BLE001
            ledger(rid, 'error', role=j[0]['id'], case=j[1]['case_id'], model=j[2], repeat=j[3], where='run_one', error=repr(e)[:300],
                   trace=traceback.format_exc()[-1500:])
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(work, jobs))
    ledger(rid, 'run-paused' if stop.is_set() else 'run-end', jobs=len(jobs))
    if stop.is_set():
        print(f'PAUSED on a usage/credit limit -- resume later with: --resume {rid}')
    return rid


# ---------------- summary ----------------
MAIN = {'set_match': 'recall', 'conflict_match': 'recall', 'label_match': 'accuracy', 'fact_check': 'facts_kept'}
SHOW = ('recall', 'precision', 'verbatim_rate', 'accuracy', 'trap_accuracy', 'facts_kept', 'headline_right', 'forbidden_present',
        'invented_numbers', 'governs_right', 'council_kept', 'council_forbidden', 'council_spread')


def ci(vals, n=1000):
    if len(vals) < 3:
        return None
    rng = random.Random(1)
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def summary(rid=None, include_mock=False, path=None):
    evs, bad = read_ledger(path)
    starts = [e for e in evs if e['stage'] == 'run-start' and (include_mock or e.get('kind') != 'mock')]
    if rid is None:
        if not starts:
            print('no runs in ledger')
            return
        rid = starts[-1]['run']
    evs = [e for e in evs if e['run'] == rid]
    agg = {}
    for e in evs:
        if e['stage'] not in ('score', 'call', 'empty', 'truncated'):
            continue
        k = (e.get('role'), e.get('model'))
        a = agg.setdefault(k, {'scored': 0, 'failed': 0, 'usd': 0.0, 'usd_missing': 0, 'lat': [], 'm': {}, 'empty': 0, 'trunc': 0,
                               'notional': False})
        if e['stage'] == 'call':
            if e.get('use_usd') is None:
                a['usd_missing'] += 1
            else:
                a['usd'] += e['use_usd']
            a['notional'] |= bool(e.get('use_usd_is_notional'))
            lat = e.get('use_duration_api_ms') or e.get('use_gen_latency_ms')
            if lat:
                a['lat'].append(lat / 1000)
        elif e['stage'] == 'empty':
            a['empty'] += 1
        elif e['stage'] == 'truncated':
            a['trunc'] += 1
        elif e.get('failed'):
            a['failed'] += 1
            main = MAIN.get(RAILS[e['role']]['scorer'])
            if main:
                a['m'].setdefault(main, []).append(0.0)
        else:
            a['scored'] += 1
            for m in SHOW:
                if e.get(m) is not None and not isinstance(e.get(m), (list, dict)):
                    a['m'].setdefault(m, []).append(float(e[m]))
    judge_usd = sum(e.get('use_usd') or 0 for e in evs if e['stage'] == 'judge')
    print(f'run {rid}: {len(evs)} events · unreadable ledger lines: {bad} · judge cost {judge_usd:.3f}')
    for (role, model), a in sorted(agg.items(), key=lambda x: (x[0][0] or 0, str(x[0][1]))):
        if role not in RAILS:
            continue
        att = a['scored'] + a['failed']
        parts = []
        for m, v in sorted(a['m'].items()):
            c = ci(v)
            parts.append(f"{m}={sum(v)/len(v):.2f}" + (f"[{c[0]:.2f}-{c[1]:.2f}]" if c else ''))
        lat = f"{sorted(a['lat'])[len(a['lat'])//2]:.1f}s" if a['lat'] else '-'
        tag = ' (self-check)' if RAILS[role]['scorer'] == 'mechanical' else ''
        print(f"  {role:>2} {RAILS[role]['name'][:24]:24} {str(model)[:30]:30} cov={a['scored']}/{att} empty={a['empty']} trunc={a['trunc']} "
              f"usd{'~' if a['notional'] else ''}={a['usd']:.3f} missing={a['usd_missing']} lat={lat} {' '.join(parts)}{tag}")


# ---------------- combinations: which MIX of models is best ----------------
def merge_outputs(rail, txts):
    """union for list jobs (readers, gaps, conflicts); majority vote for labels; returns a combined answer text."""
    if rail['scorer'] in ('set_match',):
        seen, out = set(), []
        for t in txts:
            for q in as_items(extract_json(t)[0]):
                k = norm(q)
                if k and k not in seen:
                    seen.add(k); out.append({'quote': q})
        return json.dumps(out, ensure_ascii=False)
    if rail['scorer'] == 'conflict_match':
        out = []
        for t in txts:
            o = extract_json(t)[0]
            out += o if isinstance(o, list) else next((v for v in o.values() if isinstance(v, list)), []) if isinstance(o, dict) else []
        return json.dumps(out, ensure_ascii=False)
    if rail['scorer'] == 'label_match':
        votes = {}
        for t in txts:
            for k, v in as_labels(extract_json(t)[0]).items():
                votes.setdefault(k, []).append(json.dumps(v, sort_keys=True, ensure_ascii=False))
        return json.dumps([{'item_id': k, 'label': json.loads(max(set(v), key=v.count))} for k, v in votes.items()], ensure_ascii=False)
    return '\n'.join(txts)                      # fact_check: union of statements


def combos(rid, size=2, top=8, path=None):
    """score every pair/triple of models per role from SAVED outputs (no new calls): recall/accuracy and summed cost."""
    import itertools
    evs, _ = read_ledger(path)
    st = next(e for e in evs if e['run'] == rid and e['stage'] in ('run-start',))
    cases = {c['case_id']: c for c in load_cases(st['cases'], list(RAILS))}
    calls = {}
    for e in evs:
        if e['run'] == rid and e['stage'] == 'call' and e.get('repeat', 0) == 0:
            calls.setdefault((e['role'], e['case']), {})[e['model']] = (os.path.join(HERE, e['raw']), e.get('use_usd') or 0)
    roles = sorted({r for r, _ in calls})
    report = []
    for role in roles:
        rail = RAILS[role]
        main = MAIN.get(rail['scorer'])
        if not main or rail['id'] in (17, 25):
            continue
        models = sorted({m for (r, _), d in calls.items() if r == role for m in d})
        res = []
        for k in range(1, size + 1):
            for combo in itertools.combinations(models, k):
                vals, cost = [], 0.0
                for (r, cid), d in calls.items():
                    if r != role:
                        continue
                    if not all(m in d for m in combo):
                        vals.append(0.0); continue        # a member failed: the mix failed on this case
                    txt = merge_outputs(rail, [open(d[m][0], encoding='utf-8').read() for m in combo])
                    sc, _ = score(rail, cases[cid], txt)
                    vals.append(sc.get(main, 0.0) or 0.0)
                    cost += sum(d[m][1] for m in combo)
                if vals:
                    c = ci(vals)
                    res.append((sum(vals) / len(vals), c, cost, combo))
        res.sort(key=lambda x: (-x[0], x[2]))
        best = res[0][0] if res else 0
        print(f"\n{role:>2} {rail['name']} ({main}); best {best:.2f}")
        for v, c, cost, combo in res[:top]:
            tag = ' <= within 5% of best' if v >= best * 0.95 else ''
            print(f"   {v:.2f}" + (f" [{c[0]:.2f}-{c[1]:.2f}]" if c else '') + f"  ${cost:.3f}  {' + '.join(combo)}{tag}")
        cheapest = min((x for x in res if x[0] >= best * 0.95), key=lambda x: x[2], default=None)
        if cheapest:
            report.append({'role': role, 'best': res[0][3], 'best_score': round(best, 3), 'cheapest_within_5pct': cheapest[3],
                           'cheapest_score': round(cheapest[0], 3), 'cheapest_cost': round(cheapest[2], 4)})
    json.dump(report, open(os.path.join(HERE, f'combos-{rid}.json'), 'w'), indent=1)
    print(f"\nwritten combos-{rid}.json")


def dryrun():
    global LEDGER
    LEDGER = os.path.join(HERE, 'ledger-dryrun.jsonl')
    rid = run(sorted(r for r in RAILS if RAILS[r]['scorer'] != 'none'), ['mock'], 'synthetic', repeats=1, council=['mock'], force=True)
    summary(rid, include_mock=True, path=LEDGER)


def rejudge(rid, council):
    evs, _ = read_ledger()
    st = next((e for e in evs if e['run'] == rid and e['stage'] == 'run-start'), None)
    if not st:
        sys.exit('no such run')
    if st.get('case_hashes') != case_hashes(st['cases']):
        sys.exit('cases changed since the run -- refusing to rejudge')
    cases = {c['case_id']: c for c in load_cases(st['cases'], list(RAILS))}
    for e in evs:
        if e['run'] == rid and e['stage'] == 'call' and wants_council(RAILS[e['role']]):
            try:
                txt = open(os.path.join(HERE, e['raw']), encoding='utf-8').read()
                res = council_score(rid, council, RAILS[e['role']], cases[e['case']], txt, e['model'], e.get('repeat', 0))
                ledger(rid, 'rejudge', role=e['role'], case=e['case'], model=e['model'], repeat=e.get('repeat', 0), **res)
            except LimitHit as ex:
                ledger(rid, 'paused-limit', where='rejudge', note=str(ex)[:300])
                break
            except Exception as ex:  # noqa: BLE001
                ledger(rid, 'judge-error', role=e['role'], case=e['case'], candidate=e['model'], error=repr(ex)[:300])
    summary(rid)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('run'); p.add_argument('--roles', required=True); p.add_argument('--models', required=True)
    p.add_argument('--cases', default='synthetic'); p.add_argument('--repeats', type=int, default=1); p.add_argument('--council', default='')
    p.add_argument('--resume'); p.add_argument('--workers', type=int, default=1); p.add_argument('--force', action='store_true')
    p = sp.add_parser('summary'); p.add_argument('rid', nargs='?'); p.add_argument('--include-mock', action='store_true')
    p = sp.add_parser('preflight'); p.add_argument('--models', required=True); p.add_argument('--cases', default='synthetic')
    p = sp.add_parser('rejudge'); p.add_argument('rid'); p.add_argument('--council', required=True)
    p = sp.add_parser('combos'); p.add_argument('rid'); p.add_argument('--size', type=int, default=2); p.add_argument('--top', type=int, default=8)
    sp.add_parser('dryrun')
    a = ap.parse_args()
    if a.cmd == 'run':
        roles = [int(x) for x in a.roles.split(',')] if a.roles != 'all' else sorted(RAILS)
        print(run(roles, a.models.split(','), a.cases, a.repeats, [x for x in a.council.split(',') if x], a.resume, a.workers, a.force))
    elif a.cmd == 'summary':
        summary(a.rid, a.include_mock)
    elif a.cmd == 'preflight':
        print(preflight(a.models.split(','), a.cases, list(RAILS)) or 'OK')
    elif a.cmd == 'rejudge':
        rejudge(a.rid, a.council.split(','))
    elif a.cmd == 'combos':
        combos(a.rid, a.size, a.top)
    elif a.cmd == 'dryrun':
        dryrun()
