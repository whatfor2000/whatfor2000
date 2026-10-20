#!/usr/bin/env python3
"""Commit Cosmos: GitHub GraphQL -> daily JSON + script-free SVG. Python 3.11+."""
import argparse
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import urllib.error
import urllib.request

QUERY = '''query($login:String!,$from:DateTime!,$to:DateTime!){
 user(login:$login){login contributionsCollection(from:$from,to:$to){
 totalCommitContributions
 contributionCalendar{weeks{contributionDays{date contributionCount}}}
 commitContributionsByRepository(maxRepositories:100){
 contributions(first:100){pageInfo{hasNextPage} nodes{occurredAt commitCount}}}
 }}}'''

def dates(start, end):
    return [start + dt.timedelta(days=i) for i in range((end-start).days+1)]

def graphql(token, login, start, end):
    body = json.dumps({'query': QUERY, 'variables': {'login': login,
        'from': str(start)+'T00:00:00Z', 'to': str(end)+'T23:59:59Z'}}).encode()
    req = urllib.request.Request('https://api.github.com/graphql', data=body,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'User-Agent':'commit-cosmos'})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'GitHub returned HTTP {exc.code}; check token access, expiry and API limits.') from None
    if result.get('errors'):
        raise ValueError('GitHub GraphQL: '+ '; '.join(e['message'] for e in result['errors']))
    if not result.get('data',{}).get('user'):
        raise ValueError('GitHub username was not found.')
    return result['data']['user']['contributionsCollection']

def collect(token, login, start, end, metric, request=graphql):
    c = request(token, login, start, end)
    if metric == 'contributions':
        return {d['date']:d['contributionCount'] for w in c['contributionCalendar']['weeks']
                for d in w['contributionDays'] if str(start)<=d['date']<=str(end)}
    repos = c['commitContributionsByRepository']
    counts = {}
    for repo in repos:
        for n in repo['contributions']['nodes']:
            day = n['occurredAt'][:10]
            if str(start)<=day<=str(end):
                counts[day] = counts.get(day,0)+n['commitCount']
    truncated = len(repos)>=100 or any(r['contributions']['pageInfo']['hasNextPage'] for r in repos)
    if truncated:
        if start == end:
            raise ValueError('Daily API coverage limit reached. Use --metric contributions instead.')
        mid = start + dt.timedelta(days=(end-start).days//2)
        left = collect(token,login,start,mid,metric,request)
        right = collect(token,login,mid+dt.timedelta(days=1),end,metric,request)
        return {**left, **right}
    if sum(counts.values()) != c['totalCommitContributions']:
        raise ValueError('Commit totals do not reconcile with visible daily data. Check token permissions or use --metric contributions.')
    return counts

def orbital(count, peak):
    activity = math.log1p(count)/math.log1p(max(peak,1))
    return 0.19 + 0.74*(1-activity), 1.2+5*activity, activity

def make_data(login, start, end, metric='commits', demo=False, counts=None):
    rng = random.Random(8675309)
    if demo:
        counts={str(d):(0 if rng.random()<0.34 else int(rng.expovariate(1/7))+1) for d in dates(start,end)}
    return {'schemaVersion':1,'username':login,'metric':metric,'demo':demo,
        'generatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
        'from':str(start),'to':str(end),
        'days':[{'date':str(d),'count':(counts or {}).get(str(d),0)} for d in dates(start,end)]}

def svg(data):
    esc=html.escape
    days=data['days']; peak=max((d['count'] for d in days),default=0)
    total=sum(d['count'] for d in days); active=sum(d['count']>0 for d in days)
    metric=data['metric']; name=esc(data['username'])
    stamp='DEMO DATA' if data['demo'] else 'GITHUB / '+metric.upper()
    out=[f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="760" viewBox="0 0 1280 760" role="img" aria-labelledby="title desc">
<title id="title">Commit Cosmos — {name}</title><desc id="desc">{stamp}. {total} {metric}, {active} active days. Each planet is one day; higher activity is closer to the sun. {data['from']} to {data['to']}.</desc>
<defs>
<radialGradient id="bg"><stop stop-color="#102738"/><stop offset="1" stop-color="#050910"/></radialGradient>
<radialGradient id="sun"><stop stop-color="#fffbd1"/><stop offset=".6" stop-color="#ffc95c"/><stop offset="1" stop-color="#e97c28"/></radialGradient>
<radialGradient id="halo"><stop stop-color="#f5ac42" stop-opacity=".33"/><stop offset="1" stop-color="#f5ac42" stop-opacity="0"/></radialGradient>
<radialGradient id="cyan" cx="30%" cy="25%" r="78%"><stop stop-color="#e5ffff"/><stop offset=".28" stop-color="#68e6ef"/><stop offset=".65" stop-color="#14798e"/><stop offset="1" stop-color="#052330"/></radialGradient>
<radialGradient id="gold" cx="30%" cy="25%" r="78%"><stop stop-color="#fffbc4"/><stop offset=".3" stop-color="#ffd57a"/><stop offset=".7" stop-color="#ad6f29"/><stop offset="1" stop-color="#33221a"/></radialGradient>
<radialGradient id="blue" cx="30%" cy="25%" r="78%"><stop stop-color="#afd6f2"/><stop offset=".4" stop-color="#3b708d"/><stop offset="1" stop-color="#102333"/></radialGradient>
</defs>
<rect x="1" y="1" width="1278" height="758" rx="22" fill="url(#bg)" stroke="#183242"/>
<g fill="#c6edff">''']
    rng=random.Random(42)
    for _ in range(330):
        out.append(f'<circle cx="{rng.randrange(25,1250)}" cy="{rng.randrange(130,650)}" r="{rng.uniform(.3,1):.2f}" opacity="{rng.uniform(.08,.4):.2f}"/>')
    out.append('</g><g fill="none" stroke="#397387" stroke-opacity=".25">')
    for r in range(100,551,50):
        out.append(f'<ellipse cx="640" cy="394" rx="{r}" ry="{r*.43}"/>')
    out.append('</g><circle cx="640" cy="394" r="135" fill="url(#halo)"/>')
    planets=[]
    for i,day in enumerate(days):
        radius,size,t=orbital(day['count'],peak)
        angle=i/max(len(days),1)*math.tau-.9
        x=640+550*radius*math.cos(angle); depth=math.sin(angle)
        y=394+550*radius*depth*.43
        planets.append((depth,x,y,size,t,day))
    def planet(p):
        _,x,y,size,t,day=p
        color='gold' if t>.85 else 'cyan' if t>.28 else 'blue'
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{size:.2f}" fill="url(#{color})" opacity="{.35 if day["count"]==0 else 1}"><title>{day["date"]}: {day["count"]} {metric}</title></circle>'
    for p in sorted(planets):
        if p[0]<0: out.append(planet(p))
    out.append('<circle cx="640" cy="394" r="28" fill="url(#sun)" stroke="#ffe4a2"/>')
    for p in sorted(planets):
        if p[0]>=0: out.append(planet(p))
    out.append(f'''<g font-family="Arial, sans-serif">
<text x="44" y="53" fill="#8fe7f1" font-size="12" letter-spacing="4">C O R N O S O F T / ORBITAL ACTIVITY</text>
<text x="42" y="95" fill="#edfaff" font-size="31" letter-spacing="5">COMMIT COSMOS</text>
<text x="44" y="124" fill="#7296ac" font-size="15">@{name} · {data['from']} — {data['to']}</text>
<text x="1236" y="54" text-anchor="end" fill="#8fe7f1" font-size="12" letter-spacing="2">{stamp}</text>
<text x="1236" y="92" text-anchor="end" fill="#edfaff" font-size="24">{total:,} {metric}</text>
<text x="1236" y="120" text-anchor="end" fill="#7296ac" font-size="14">{active} active days · peak {peak}</text>
<path d="M44 672H1236" stroke="#183242"/>
<text x="44" y="708" fill="#7296ac" font-size="13">ONE PLANET = ONE DAY</text>
<text x="1236" y="708" text-anchor="end" fill="#9beef1" font-size="13">MORE ACTIVITY → CLOSER TO THE SUN</text>
<text x="44" y="737" fill="#476477" font-size="11">{'Illustrative sample; run the workflow to load your real activity.' if data['demo'] else 'GitHub contribution rules and token visibility apply. Updated '+data['generatedAt'][:10]+' UTC.'}</text>
</g></svg>''')
    return '\n'.join(out)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--username',default=os.getenv('COSMOS_USERNAME','whatfor2000'))
    p.add_argument('--metric',choices=['commits','contributions'],default='commits')
    p.add_argument('--year',type=int)
    p.add_argument('--demo',action='store_true')
    p.add_argument('--out',default='dist')
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?',a.username):
        p.error('Invalid GitHub username.')
    today=dt.datetime.now(dt.timezone.utc).date()
    start=dt.date(a.year,1,1) if a.year else today-dt.timedelta(days=364)
    end=min(dt.date(a.year,12,31),today) if a.year else today
    if start>end: p.error('Future years are not supported.')
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if not a.demo and not token: p.error('Set GH_TOKEN or GITHUB_TOKEN. Use --demo for an offline preview.')
    try:
        counts=None if a.demo else collect(token,a.username,start,end,a.metric)
        data=make_data(a.username,start,end,a.metric,a.demo,counts)
        target=Path(a.out); target.mkdir(parents=True,exist_ok=True)
        for filename,content in [('data.json',json.dumps(data,indent=2)),('cosmos.svg',svg(data))]:
            temp=target/(filename+'.tmp'); temp.write_text(content,encoding='utf-8'); temp.replace(target/filename)
        print(f'Generated {len(data["days"])} days for {a.username} ({"DEMO" if a.demo else a.metric}).')
    except (ValueError,urllib.error.URLError) as exc:
        print(str(exc),file=sys.stderr); return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
