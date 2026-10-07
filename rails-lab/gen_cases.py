#!/usr/bin/env python3
"""Synthetic test set v2 for the rails lab (6 Oct 2026, after the independent review).

Fixes from the review: fully synthetic filler (no corpus text, frozen in _bank.json) · several INDEPENDENT variants of the
invented module (values re-drawn per variant) so each role has 5+ cases · long documents for the reader · speaker test
built on AI paraphrase traps, not on visible labels · complete truth sets with 'also_ok' extras · facts written as full
propositions with required tokens (numbers kept) · 'forbidden' superseded/trap claims per case · explicit output enums.
Output: cases/synthetic/NN.jsonl (one file per rail) + cases/synthetic/_bank.json (everything needed to audit a case).
"""
import os, json, random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'cases', 'synthetic')
os.makedirs(OUT, exist_ok=True)
CASES_PER_ROLE = {r: 30 if r in (9, 10, 11, 12, 13, 14, 15, 16, 21, 23) else 6 for r in range(1, 26)}
N_VARIANTS = max(CASES_PER_ROLE.values())   # variant v feeds only the roles with more than v cases
# a new variant whose answer repeats an earlier case of one of these roles is re-drawn. Roles 10, 16 and 23 are left out:
# their answers barely depend on the drawn values (3, 2 and 1 possible answers), so re-drawing cannot make them unique.
UNIQUE_ROLES = (9, 10, 11, 12, 13, 14, 15, 16, 21, 23)
N_ORIGINAL = 6   # variants 0-5 keep their original values; only their extra statements (below) may be re-drawn

# Roles 10, 16 and 23 barely depend on the drawn values, so each of their cases also draws two statements of its own,
# inserted into its text: exceptions for role 10, and statements that leave something undefined (gaps) for roles 16 and 23.
# Each entry is (statement, gap, gap tokens, options for {x}, options for {y}).
EXCEPTIONS = [("SIG_X is halved unless funding is above {x} percent", None, None, ['0.05', '0.1', '0.2', '0.3'], None),
              ("SIG_X is not scored on {x}s, except after a {y} percent gap", None, None, ['Saturday', 'Sunday'], ['2', '3', '5']),
              ("SIG_X only counts when the {x} candle has closed", None, None, ['1 hour', '4 hour', '12 hour'], None),
              ("override: if Phi is below {x}, SIG_X is ignored", None, None, ['10', '20', '30'], None),
              ("no matter what the bands say, SIG_X is 0 for {x} hours after a liquidation cascade", None, None, ['2', '4', '6'], None),
              ("except during {x}, SIG_X keeps its last reading", None, None, ['the Asian session', 'the funding window', 'exchange maintenance'], None),
              ("ignore SIG_X when volume is under {x} percent of the {y} day average", None, None, ['40', '50', '60'], ['7', '14', '30'])]
GAPS = [("in {x} mode SIG_X reads the bands differently", "what {x} mode changes is never stated", ['{x}', 'mode'], ['turbo', 'quiet', 'sweep', 'night'], None),
        ("SIG_X uses the lookback window from the {x} template", "how long the lookback window is is never stated", ['lookback'], ['old', 'shared', 'backup'], None),
        ("when the {x} filter is on, some SIG_X bands are skipped", "which bands the {x} filter skips is never stated", ['{x}', 'filter'], ['volatility', 'session', 'spread'], None),
        ("SIG_X gets a bonus point on a clean {x}", "what counts as a clean {x} is never stated", ['{x}'], ['retest', 'sweep', 'squeeze', 'reclaim'], None),
        ("SIG_X resets at the {x} rollover", "what SIG_X resets to at the {x} rollover is never stated", ['{x}', 'rollover'], ['weekly', 'monthly', 'quarterly'], None),
        ("SIG_X sends an alert once it passes the {x} threshold", "the value of the {x} threshold is never stated", ['{x}', 'threshold'], ['alert', 'warning', 'trigger'], None),
        ("a divergence on the {x} counts double for SIG_X", "what counts as a divergence on the {x} is never stated", ['divergence', '{x}'], ['RSI', 'MFI', 'OBV', 'CVD'], None),
        ("SIG_X is paused during {x}", "how long SIG_X stays paused during {x} is never stated", ['{x}'], ['news events', 'low liquidity', 'exchange maintenance'], None)]

# ---------- fully synthetic filler: trading-desk chatter with no module vocabulary ----------
FILL_A = ["Morning, quick one before the call.", "Charts are loading slowly again today.", "I moved the screenshots into the weekly folder.",
          "Coffee first, then the session notes.", "The exchange app logged me out twice this morning.", "Remind me to back up the drive later.",
          "I tried the new layout on the second monitor.", "Funding rates looked quiet overnight.", "Let's keep the meeting short today.",
          "The internet keeps dropping in the afternoon.", "I renamed the folders so they sort by date.", "Volume felt thin over the weekend."]
FILL_B = ["Not much changed since yesterday's review.", "I'll write it up properly after lunch.", "We can revisit the layout next week.",
          "Nothing urgent, just tidying up.", "I want the notes cleaner before the next session.", "Most of this is housekeeping.",
          "The spreadsheet totals still need checking.", "I'll check the calendar for the next catch-up.", "Let's park that for now.",
          "Remind me to update the template.", "The export finished but the file names are messy.", "I need a better system for screenshots."]
FILL_C = ["Also, the dog needs a walk at four.", "Someone suggested a different note-taking app.", "The power cut lasted about twenty minutes.",
          "I found the old trading journal in a box.", "The new keyboard is much quieter.", "I'm thinking of moving the desk by the window.",
          "Battery on the laptop is getting worse.", "We should label the cables properly.", "The headphones finally arrived.",
          "Weekend plans are still open.", "I cleared out the downloads folder.", "Need to renew the domain this month."]


def filler(rng, n):
    out = []
    for _ in range(n):
        sents = [rng.choice(FILL_A), rng.choice(FILL_B), rng.choice(FILL_C), rng.choice(FILL_B)]
        rng.shuffle(sents)
        out.append(' '.join(sents) * rng.choice([1, 1, 2]))
    return out


# ---------- the invented module, parameterised so every variant has different values ----------
def make_variant(v, attempt=0):
    seed = 1000 + v + 100000 * attempt   # attempt 0 keeps the original seeds, so variants 0-5 are unchanged
    rng = random.Random(seed)
    cap_old, cap_new = rng.choice([(5, 4), (6, 4), (5, 3), (6, 5)])
    floor_old, floor_new = rng.choice([(4, 3), (6, 4), (8, 6), (12, 8)])
    expiry = rng.choice([1, 2, 3])
    ma = rng.choice([9, 12, 20])
    closes = rng.choice([2, 3])
    weight = rng.choice(['half', 'a quarter', 'double'])
    inputs = rng.choice([('RSI', 'OBV'), ('RSI', 'MFI'), ('Stoch RSI', 'OBV')])
    states = rng.choice([('building', 'active', 'fading', 'dead'), ('forming', 'live', 'weakening', 'off')])
    d = lambda day: f"2026-09-{day:02d}"
    S = lambda s: s  # readability
    bank = [
     ("f01", "DAVID", d(10), f"SIG_X is the pressure signal, sometimes I call it PX", "CURRENT", "identity"),
     ("f02", "DAVID", d(10), f"SIG_X scores from 0 to {cap_new} per direction per band", "CURRENT", "rule"),
     ("f03", "DAVID", d(11), f"the inputs for SIG_X are the {inputs[0]} and the {inputs[1]}, nothing else", "CURRENT", "input"),
     ("f04", "DAVID", d(11), f"SIG_X goes up one point for every band where the {inputs[1]} makes a higher low", "CURRENT", "rule"),
     ("f05", "DAVID", d(12), f"the floor for SIG_X is the {floor_old} hour interval", "SUPERSEDED", "parameter"),
     ("f06", "DAVID", d(20), f"change of plan, the floor for SIG_X is now the {floor_new} hour interval", "CURRENT", "parameter"),
     ("f07", "DAVID", d(25), f"ignore all SIG_X readings below the {expiry} hour, they were noise", "CURRENT", "expiry"),
     ("f08", "DAVID", d(13), f"unless the weekly close is below the range low, then SIG_X is 0 no matter what", "CURRENT", "exception"),
     ("f09", "DAVID", d(14), f"SIG_X has four states: {states[0]}, {states[1]}, {states[2]} and {states[3]}", "CURRENT", "state"),
     ("f10", "DAVID", d(14), f"it goes from {states[1]} to {states[2]} after {closes} closes below the {ma} MA", "CURRENT", "transition"),
     ("f11", "DAVID", d(15), f"SIG_X feeds into Phi at {weight} weight", "CURRENT", "interface"),
     ("f12", "DAVID", d(15), f"quality for SIG_X is 0 when the chart is choppy, otherwise 1 or 2", "CURRENT", "quality"),
     ("f13", "DAVID", d(16), f"SIG_X is capped at {cap_old}", "SUPERSEDED", "rule"),
     ("f14", "DAVID", d(22), f"no, SIG_X is capped at {cap_new}, that is final", "CURRENT", "rule"),
     ("f15", "DAVID", d(17), f"I write it as PX_B2({floor_new}H,{inputs[1][0]}), bull, score 2, on the {floor_new} hour, from the {inputs[1]}", "CURRENT", "notation"),
     ("f16", "DAVID", d(18), f"show SIG_X as a bar on the global dashboard", "CURRENT", "display"),
     ("f17", "DAVID", d(18), f"I record SIG_X at the end of each band read", "CURRENT", "capture"),
    ]
    traps = [  # AI paraphrases that CLAIM to be David's words, and a third party: must not be taken as David
     ("t01", "ARIS-LEAD", d(16), f"So to confirm what you said, SIG_X caps at {cap_old} and also uses the MACD"),
     ("t02", "ARIS-LEAD", d(21), f"You said SIG_X needs {closes + 1} closes below the {ma} MA before it moves on"),
     ("t03", "3RD", d(19), "Rohit reckons SIG_X should run on the daily too"),
    ]
    p = dict(cap_old=cap_old, cap_new=cap_new, floor_old=floor_old, floor_new=floor_new, expiry=expiry, ma=ma, closes=closes,
             weight=weight, inputs=inputs, states=states)
    return {'v': v, 'seed': seed, 'params': p, 'bank': bank, 'traps': traps}


def draw(rng, pool, n=2):
    """n different templates from pool, each with its own drawn values: [(statement, gap fact or None)]"""
    out = []
    for stmt, gap, tokens, xs, ys in rng.sample(pool, n):
        fill = dict(x=rng.choice(xs), y=rng.choice(ys) if ys else '')
        fact = {'prop': gap.format(**fill), 'tokens': [w for t in tokens for w in t.format(**fill).lower().split()]} if gap else None
        out.append((stmt.format(**fill), fact))
    return out


def with_statements(rng, facts, stmts):
    """the findings text with extra David statements inserted at random places"""
    lines = [line(f) for f in facts]
    for i, st in enumerate(stmts):
        lines.insert(rng.randint(0, len(lines)), line((f"x{i}", 'DAVID', f"2026-09-{rng.randint(10, 25):02d}", st)))
    return '\n'.join(lines)


HDR = {'DAVID': 'David', 'ARIS-LEAD': 'Aris', '3RD': 'Rohit (forwarded)'}
line = lambda f: f"**{HDR[f[1]]}** · {f[2]}\n{f[3]}\n"


def build_doc(rng, facts, n_fill):
    parts = filler(rng, n_fill)
    for f in facts:
        parts.insert(rng.randint(0, len(parts)), line(f))
    return '\n\n'.join(parts)


def T(*toks):  # required tokens for a fact (numbers kept)
    return [str(t).lower() for t in toks]


def main():
    def build(V, extra=0):
        cases = {r: [] for r in range(1, 26)}
        v, P, B, TR = V['v'], V['params'], V['bank'], V['traps']
        rng = random.Random(2000 + v)
        cid = lambda r: f"r{r:02d}-v{v}"
        trapsf = [(t[0], t[1], t[2], t[3], 'TRAP', 'trap') for t in TR]
        allf = B + trapsf
        findings = '\n'.join(line(f) for f in allf)
        # 1 bulk reader: short and LONG documents (long-context weakness only shows on long inputs)
        n_fill = [12, 40, 150, 300, 12, 450][v % 6]   # up to ~100k characters: long-context weakness only shows on long inputs
        sub = rng.sample(B, 8) + rng.sample(trapsf, 2)
        cases[1].append({'case_id': cid(1), 'role': 1, 'input': {'module': 'SIG_X', 'text': build_doc(rng, sub, n_fill)},
                         'truth': {'items': [f[3] for f in sub if f[1] == 'DAVID'], 'verbatim_required': True}})
        # 2 speaker: realistic turns; traps are AI turns that quote or paraphrase David as if they were his words
        pool = rng.sample(B, 5) + trapsf
        items = {f[0]: f[3] for f in pool}
        cases[2].append({'case_id': cid(2), 'role': 2, 'input': {'text': '\n'.join(line(f) for f in rng.sample(pool, len(pool))), 'items': items,
                         'labels_allowed': ['DAVID', 'ARIS-LEAD', '3RD']},
                         'truth': {'labels': {f[0]: f[1] for f in pool}, 'traps': ['t01', 't02']}})
        # 3 dictation garbles
        g = [(f"the sig ex was {P['states'][0]} on the {P['floor_new']} hour", 'SIG_X'), (f"the old b v made a higher low", 'OBV'),
             ("pea ex bull two", 'PX'), (f"feeds into fie at {P['weight']} weight", 'PHI'), (f"the {P['ma']} em a broke", f"{P['ma']} MA")]
        g = rng.sample(g, 4)
        cases[3].append({'case_id': cid(3), 'role': 3, 'input': {'module': 'SIG_X', 'terms_allowed': ['SIG_X', 'PX', 'OBV', 'RSI', 'PHI', f"{P['ma']} MA"],
                         'items': {f'g{i}': x for i, (x, _) in enumerate(g)}}, 'truth': {'labels': {f'g{i}': y for i, (_, y) in enumerate(g)}}})
        # 4 recency: status only
        rec = [f for f in B if f[0] in ('f05', 'f06', 'f13', 'f14', 'f02', 'f07')] + \
              [("f18", "DAVID", "2026-09-12", f"SIG_X readings on the {max(1, P['expiry'] - 1)} hour count too", "EXPIRED", "rule")]
        cases[4].append({'case_id': cid(4), 'role': 4, 'input': {'text': '\n'.join(line(f) for f in rec), 'items': {f[0]: f[3] for f in rec},
                         'labels_allowed': ['CURRENT', 'SUPERSEDED', 'EXPIRED']},
                         'truth': {'labels': {f[0]: f[4] for f in rec}, 'traps': ['f05', 'f13', 'f18']}})
        # 5 notation
        codes = []
        for _ in range(4):
            dr = rng.choice([('B', 'bull'), ('S', 'bear')]); sc = rng.randint(0, P['cap_new']); iv = rng.choice(['3H', '4H', '12H', '1D'])
            ind = rng.choice([('O', 'OBV'), ('R', 'RSI')])
            codes.append((f"PX_{dr[0]}{sc}({iv},{ind[0]})", f"{dr[1]}|{sc}|{iv}|{ind[1]}"))
        cases[5].append({'case_id': cid(5), 'role': 5, 'input': {'key': 'PX_<B=bull|S=bear><score>(<interval>,<O=OBV|R=RSI>)',
                         'answer_format': 'direction|score|interval|indicator  e.g. bull|2|4H|OBV', 'items': {f'n{i}': c for i, (c, _) in enumerate(codes)}},
                         'truth': {'labels': {f'n{i}': d_ for i, (_, d_) in enumerate(codes)}}})
        # 6 repairer: each altered quote must differ from its original
        rp = rng.sample(B, 4)
        passage = build_doc(rng, rp, 6)
        alt = []
        for f in rp:
            a = f[3].replace('SIG_X', 'SIGX', 1) if 'SIG_X' in f[3] else f[3].replace(' the ', ' a ', 1)
            if a == f[3]:
                a = f[3] + ' as well'
            assert a != f[3]
            alt.append({'quote': a, 'problem': 'quote not word-for-word'})
        alt.append({'quote': f"SIG_X also uses the stochastic", 'problem': 'quote not word-for-word'})
        cases[6].append({'case_id': cid(6), 'role': 6, 'input': {'text': passage, 'findings': alt},
                         'truth': {'items': [f[3] for f in rp], 'verbatim_required': True}})
        # 7 module tagger (label = set of modules)
        tag = {'m0': (B[10][3], ['PHI', 'SIG_X']), 'm1': (B[3][3], ['SIG_X']),
               'm2': ("the Wyckoff range low broke on the weekly close, so SIG_X is 0", ['SIG_X', 'WYCKOFF_STATE']),
               'm3': ("the momentum cloud flipped green on two timeframes", ['MOM']), 'm4': (B[15][3], ['GLOBAL_STATUS', 'SIG_X'])}
        cases[7].append({'case_id': cid(7), 'role': 7, 'input': {'modules_allowed': ['SIG_X', 'PHI', 'WYCKOFF_STATE', 'MOM', 'GLOBAL_STATUS'],
                         'answer_format': 'label = all modules touched, joined with +', 'items': {k: x[0] for k, x in tag.items()}},
                         'truth': {'labels': {k: '+'.join(sorted(x[1])) for k, x in tag.items()}, 'label_is_set': True}})
        # 8 duplicates: SAME = same meaning AND same values
        pairs = {'d0': (B[1][3], f"SIG_X runs from zero to {P['cap_new']}, per direction, per band", 'SAME'),
                 'd1': (B[4][3], B[5][3], 'DIFFERENT'), 'd2': (B[12][3], B[13][3], 'DIFFERENT'),
                 'd3': (B[9][3], f"{P['closes']} closes under the {P['ma']} MA moves it from {P['states'][1]} into {P['states'][2]}", 'SAME'),
                 'd4': (B[2][3], f"SIG_X reads the {P['inputs'][0]} and the MACD", 'DIFFERENT')}
        cases[8].append({'case_id': cid(8), 'role': 8, 'input': {'definition': 'SAME = same meaning AND same values; otherwise DIFFERENT',
                         'labels_allowed': ['SAME', 'DIFFERENT'], 'items': {k: {'a': x[0], 'b': x[1]} for k, x in pairs.items()}},
                         'truth': {'labels': {k: x[2] for k, x in pairs.items()}, 'traps': ['d1', 'd2', 'd4']}})
        # 9 contradictions: pairs + which governs (newest dated David statement; AI claims never govern)
        conf = [{'pair': [B[4][3], B[5][3]], 'governs': B[5][3]}, {'pair': [B[12][3], B[13][3]], 'governs': B[13][3]},
                {'pair': [TR[0][3], B[13][3]], 'governs': B[13][3]}, {'pair': [TR[0][3], B[2][3]], 'governs': B[2][3]},
                {'pair': [TR[1][3], B[9][3]], 'governs': B[9][3]}]
        cases[9].append({'case_id': cid(9), 'role': 9, 'input': {'text': findings, 'answer_format': 'list of {"quotes": [a, b], "governs": <quote>}'},
                         'truth': {'conflicts': conf}})
        # 10 exceptions / overrides
        xr = random.Random(f"{V['seed']}-extra" + (f"-{extra}" if extra else ''))   # own stream, so the draws above are unchanged
        ex = [st for st, _ in draw(xr, EXCEPTIONS)]
        cases[10].append({'case_id': cid(10), 'role': 10, 'input': {'text': with_statements(xr, allf, ex),
                          'definition': 'statements that cancel or override a rule (unless / except / no matter what / ignore)'},
                          'truth': {'items': [B[7][3], B[6][3]] + ex, 'also_ok': [B[11][3]]}})
        # 11-15 defining: full propositions with required tokens; forbidden = superseded values and trap claims
        forb = [{'claim': f"capped at {P['cap_old']}", 'tokens': T('capped', P['cap_old'])}, {'claim': f"{P['floor_old']} hour floor", 'tokens': T(P['floor_old'], 'hour', 'floor')},
                {'claim': 'uses the MACD', 'tokens': T('macd')}, {'claim': f"{P['closes'] + 1} closes", 'tokens': T(P['closes'] + 1, 'closes')}]
        facts11 = [{'prop': f"SIG_X scores 0 to {P['cap_new']} per direction per band", 'tokens': T(0, P['cap_new'], 'band')},
                   {'prop': f"one point per band where the {P['inputs'][1]} makes a higher low", 'tokens': T(P['inputs'][1], 'higher', 'low')},
                   {'prop': f"the floor is the {P['floor_new']} hour interval", 'tokens': T(P['floor_new'], 'hour')},
                   {'prop': f"SIG_X is capped at {P['cap_new']}", 'tokens': T('capped', P['cap_new'])},
                   {'prop': "a weekly close below the range low forces SIG_X to 0", 'tokens': T('weekly', 'close', 'range', 'low', 0)},
                   {'prop': f"readings below the {P['expiry']} hour are ignored", 'tokens': T(P['expiry'], 'hour')}]
        defs = {11: (facts11, f"SIG_X is capped at {P['cap_new']}"),
                12: (facts11[:2] + facts11[3:5], f"SIG_X is capped at {P['cap_new']}"),
                13: ([{'prop': f"states: {', '.join(P['states'])}", 'tokens': T(*P['states'])},
                      {'prop': f"{P['states'][1]} to {P['states'][2]} after {P['closes']} closes below the {P['ma']} MA", 'tokens': T(P['states'][1], P['states'][2], P['closes'], P['ma'])}],
                     f"{P['states'][1]} to {P['states'][2]} after {P['closes']} closes below the {P['ma']} MA"),
                14: ([{'prop': f"inputs are the {P['inputs'][0]} and the {P['inputs'][1]}", 'tokens': T(*' '.join(P['inputs']).split())},
                      {'prop': f"feeds Phi at {P['weight']} weight", 'tokens': T('phi', *P['weight'].split())}], f"feeds Phi at {P['weight']} weight"),
                15: ([{'prop': 'SIG_X is the pressure signal', 'tokens': T('pressure', 'signal')}, {'prop': 'PX is another name for SIG_X', 'tokens': T('px')},
                      {'prop': f"{P['states'][2]} is a state", 'tokens': T(P['states'][2])}], 'SIG_X is the pressure signal')}
        for r, (facts, head) in defs.items():
            cases[r].append({'case_id': cid(r), 'role': r, 'input': {'module': 'SIG_X', 'text': findings},
                             'truth': {'facts': facts, 'headline': head, 'forbidden': forb}})
        # 16 gaps: required gaps + acceptable extra gaps
        gaps = [{'prop': 'what SIG_X does on the daily band is never stated', 'tokens': T('daily')},
                {'prop': 'how quality 1 differs from quality 2 is never stated', 'tokens': T('quality', 1, 2)}]
        extra = [{'prop': f"what moves SIG_X from {P['states'][0]} to {P['states'][1]}", 'tokens': T(P['states'][0])},
                 {'prop': f"what moves it from {P['states'][2]} to {P['states'][3]}", 'tokens': T(P['states'][3])}]
        dg = draw(xr, GAPS)   # the drawn gaps are required; the fixed gaps are still real gaps, so they count as extras
        cases[16].append({'case_id': cid(16), 'role': 16, 'input': {'module': 'SIG_X', 'text': with_statements(xr, allf, [st for st, _ in dg])},
                          'truth': {'facts': [g for _, g in dg], 'also_ok_facts': gaps + extra}})
        # 17 search planner: judged by the council (searches must go beyond echoing the gap)
        cases[17].append({'case_id': cid(17), 'role': 17, 'input': {'gaps': [x['prop'] for x in gaps]},
                          'truth': {'facts': [{'prop': 'searches for the daily timeframe using other words (1D, day chart, daily close)', 'tokens': T('1d')},
                                              {'prop': 'searches for what separates quality levels (clean, wick, noisy)', 'tokens': T('wick')}], 'council_only': True}})
        # 18 saturation
        sat = {'s0': (f"SIG_X runs 0 to {P['cap_new']} per band", 'KNOWN'), 's1': ("on the monthly SIG_X is never used", 'NEW'),
               's2': (f"one point for each band where the {P['inputs'][1]} makes a higher low", 'KNOWN'),
               's3': (f"SIG_X resets to {P['states'][0]} after a {P['states'][3]} state lasts a week", 'NEW')}
        cases[18].append({'case_id': cid(18), 'role': 18, 'input': {'known': [B[1][3], B[3][3]], 'labels_allowed': ['NEW', 'KNOWN'], 'items': {k: x[0] for k, x in sat.items()}},
                          'truth': {'labels': {k: x[1] for k, x in sat.items()}}})
        # 19 mechanical self-check
        cases[19].append({'case_id': cid(19), 'role': 19, 'input': {'text': findings}, 'truth': {'bank': [[f[3], f[1]] for f in allf]}})
        # 20 faithfulness
        fj = {'q0': (B[3][3], f"SIG_X gains a point per band with a {P['inputs'][1]} higher low", 'SUPPORTED'),
              'q1': (B[10][3], "SIG_X feeds into Phi at full weight", 'UNSUPPORTED'),
              'q2': (B[7][3], "a weekly close below the range low forces SIG_X to 0", 'SUPPORTED'),
              'q3': (B[2][3], "SIG_X also uses the MACD", 'UNSUPPORTED')}
        cases[20].append({'case_id': cid(20), 'role': 20, 'input': {'labels_allowed': ['SUPPORTED', 'UNSUPPORTED'], 'items': {k: {'quote': x[0], 'claim': x[1]} for k, x in fj.items()}},
                          'truth': {'labels': {k: x[2] for k, x in fj.items()}, 'traps': ['q1', 'q3']}})
        # 21 spec reviewer: planted wrong values + missing exceptions (all required)
        rules = [f"SIG_X scores from 0 to {P['cap_new']} per direction per band.", f"The floor is the {P['floor_old']} hour interval.",
                 f"SIG_X is capped at {P['cap_old']}.", f"It moves from {P['states'][1]} to {P['states'][2]} after {P['closes']} closes below the {P['ma']} MA.",
                 f"It feeds Phi at {P['weight']} weight."]
        cases[21].append({'case_id': cid(21), 'role': 21, 'input': {'findings': findings, 'rules': rules},
                          'truth': {'facts': [{'prop': f"the floor should be {P['floor_new']} hours, not {P['floor_old']}", 'tokens': T('floor', P['floor_new'])},
                                              {'prop': f"the cap should be {P['cap_new']}, not {P['cap_old']}", 'tokens': T('cap', P['cap_new'])},
                                              {'prop': 'the weekly-close-below-range-low exception is missing', 'tokens': T('weekly')},
                                              {'prop': f"the rule to ignore readings below {P['expiry']} hour is missing", 'tokens': T('ignore')}]}})
        # 22 mechanical number check (self-check)
        cases[22].append({'case_id': cid(22), 'role': 22, 'input': {'findings': findings, 'rules': rules + ["SIG_X uses a 14 period RSI."]},
                          'truth': {'flag': ["SIG_X uses a 14 period RSI."]}})
        # 23 question writer: must ask the open issues; must NOT re-ask settled points
        qg = draw(xr, GAPS)   # drawn apart from role 16's, so the two roles do not share topics
        cases[23].append({'case_id': cid(23), 'role': 23, 'input': {'module': 'SIG_X', 'text': with_statements(xr, allf, [st for st, _ in qg]),
                          'settled': [B[13][3], B[5][3]]},
                          'truth': {'facts': [g for _, g in qg], 'headline': qg[0][1]['prop'],
                                    # re-asked = a question that names the point and asks to change/confirm it or offers another value
                                    'forbidden': [{'claim': 're-asks the cap', 'tokens': T('cap'), 'topic': ['cap', 'caps', 'capped'], 'settled': str(P['cap_new'])},
                                                  {'claim': 're-asks the floor', 'tokens': T('floor'), 'topic': ['floor', 'floors'], 'settled': str(P['floor_new'])}]}})
        # 24 question critic (multi-label truth allowed)
        qs = {'c0': (f"You said on 22 Sep that SIG_X is capped at {P['cap_new']}. Should the cap be {P['cap_new']} or {P['cap_old']}?", ['REASKS_SETTLED']),
              'c1': ("What about the thing?", ['NO_CONTEXT']),
              'c2': ("You said SIG_X runs per band but never said what happens on the daily (12 Sep). On a daily higher low, should SIG_X score? Recommended: yes, same as other bands.", ['GOOD']),
              'c3': ("Should the PX_B2 delta-hedged convexity parameter be recalibrated? Also should quality be 3 levels and should the floor move?", ['MANY_DECISIONS', 'JARGON'])}
        cases[24].append({'case_id': cid(24), 'role': 24, 'input': {'labels_allowed': ['GOOD', 'REASKS_SETTLED', 'NO_CONTEXT', 'JARGON', 'MANY_DECISIONS', 'NO_RECOMMENDATION'],
                          'items': {k: x[0] for k, x in qs.items()}}, 'truth': {'labels': {k: x[1] for k, x in qs.items()}}})
        # 25 answer integrator: judged by the council (echo-proofing needs meaning, not tokens)
        cases[25].append({'case_id': cid(25), 'role': 25, 'input': {'rules': [f"SIG_X is capped at {P['cap_new']}.", 'Daily band: OPEN.', 'Quality 1 vs 2: OPEN.'],
                          'answers': {'daily': 'yes, the daily scores the same as the other bands', 'quality': 'quality 2 means clean closes, 1 means one wick through'}},
                          'truth': {'facts': [{'prop': 'the daily band now scores like the other bands (no longer OPEN)', 'tokens': T('daily')},
                                              {'prop': 'quality 2 = clean closes, quality 1 = one wick through', 'tokens': T('wick')},
                                              {'prop': f"the cap stays at {P['cap_new']}", 'tokens': T(P['cap_new'])}], 'council_only': True}})
        return {r: cs[0] for r, cs in cases.items()}

    cases, variants = {r: [] for r in range(1, 26)}, []
    seen = {r: set() for r in UNIQUE_ROLES}
    for v in range(N_VARIANTS):
        for attempt in range(1000):
            # an original variant keeps its values and re-draws only its extra statements; a new one re-draws everything
            orig = v < N_ORIGINAL
            V = make_variant(v, 0 if orig else attempt)
            V['extra'] = attempt if orig else 0
            built = build(V, V['extra'])
            keys = {r: json.dumps(built[r]['truth'], sort_keys=True) for r in UNIQUE_ROLES if v < CASES_PER_ROLE[r]}
            if all(k not in seen[r] for r, k in keys.items()):
                break
        else:
            raise SystemExit(f'variant {v}: no draw with unique answers after 1000 attempts')
        for r, k in keys.items():
            seen[r].add(k)
        variants.append(V)
        for r, c in built.items():
            cases[r].append(c)
    for r in cases:
        cases[r] = cases[r][:CASES_PER_ROLE[r]]
    for r, cs in cases.items():
        with open(os.path.join(OUT, f'{r:02d}.jsonl'), 'w', encoding='utf-8') as fh:
            for c in cs:
                fh.write(json.dumps(c, ensure_ascii=False) + '\n')
    with open(os.path.join(OUT, '_bank.json'), 'w', encoding='utf-8') as fh:
        json.dump({'variants': variants, 'filler': {'A': FILL_A, 'B': FILL_B, 'C': FILL_C}}, fh, ensure_ascii=False, indent=1)
    print('cases per role:', {r: len(c) for r, c in cases.items()}, '| longest role-1 doc chars:', max(len(c['input']['text']) for c in cases[1]))


if __name__ == '__main__':
    main()
