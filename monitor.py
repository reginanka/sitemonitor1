import os
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from logutils import logtobuffer, sendlogtochannel
from sitecontent import getschedulecontent, takescreenshotbetweenelements
from telegramhandler import sendnotification

APIBASEURL = os.getenv('APIBASEURL')
URL = os.environ.get('URL')
SUBSCRIBE = os.environ.get('SUBSCRIBE')

QUEUES = [(i, j) for i in range(1, 7) for j in range(1, 2)][1:]

DATADIR = Path('data')
DATADIR.mkdir(exist_ok=True)

CURRENTFILE = DATADIR / 'current.json'
PREVIOUSFILE = DATADIR / 'previous.json'
HASHFILE = DATADIR / 'lasthash.json'


def fetchschedule(chergaid: int, pidchergaid: int) -> Tuple[List[Dict], bool]:
    """ . , iserror. """
    resp: Optional[requests.Response] = None
    try:
        params = {'chergaid': chergaid, 'pidchergaid': pidchergaid}
        resp = requests.get(APIBASEURL, params=params, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
        
        if text.startswith('[') and text.endswith(']'):
            data = json.loads(text)
        elif text.startswith('{'):
            text = f'[{text}]'
            data = json.loads(text)
            
        if isinstance(data, list):
            return data, False
            
        logtobuffer(f'{chergaid}.{pidchergaid}')
        return [], False
        
    except Exception as e:
        body = resp.text[:200] if resp is not None else ''
        logtobuffer(f'{chergaid}.{pidchergaid} {e}: {body}')
        return [], True


def fetchallschedules() -> Tuple[Dict[str, List[Dict]], Dict[str, bool]]:
    """ . """
    allschedules: Dict[str, List[Dict]] = {}
    haserror: Dict[str, bool] = {}
    
    logtobuffer('🔄')
    
    for chergaid, pidchergaid in QUEUES:
        queuekey = f'{chergaid}.{pidchergaid}'
        schedule, iserror = fetchschedule(chergaid, pidchergaid)
        allschedules[queuekey] = schedule
        haserror[queuekey] = iserror
        
        errornote = '❌ API' if iserror else ''
        logtobuffer(f'{queuekey}: {len(schedule)} {errornote}')
    
    return allschedules, haserror


def savejson(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def loadjson(path: Path):
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def calculatehash(obj) -> str:
    jsonstr = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(jsonstr.encode('utf-8')).hexdigest()


def normalizerecord(rec: Dict, chergaid: int, pidchergaid: int) -> Dict:
    date = rec.get('date', '')
    span = rec.get('span', '')
    color = rec.get('color', '').strip().lower()
    return {
        'cherga': chergaid,
        'pidcherga': pidchergaid,
        'queuekey': f'{chergaid}.{pidchergaid}',
        'date': date,
        'span': span,
        'color': color,
    }


def buildstate(rawschedules: Dict[str, List[Dict]], haserror: Dict[str, bool]):
    """ normbyqueue, mainhashes, spanhashes """
    normbyqueue: Dict[str, List[Dict]] = {}
    mainhashes: Dict[str, str] = {}
    spanhashes: Dict[str, Dict[str, Dict[str, str]]] = {}
    
    for queuekey, schedule in rawschedules.items():
        if haserror.get(queuekey, False):
            continue
            
        chergaid, pidchergaid = map(int, queuekey.split('.'))
        normlist: List[Dict] = []
        
        for rec in schedule:
            nrec = normalizerecord(rec, chergaid, pidchergaid)
            normlist.append(nrec)
        
        normlist.sort(key=lambda r: (r['date'], r['span']))
        normbyqueue[queuekey] = normlist
        
        # mainhashdata = [{'date': r['date'], 'span': r['span'], 'color': r['color']} for r in normlist]
        mainhashdata = [[r['date'], r['span'], r['color']] for r in normlist]
        mainhashes[queuekey] = calculatehash(mainhashdata)
        
        # sh: Dict[str, Dict[str, str]] = {}
        sh: Dict[str, Dict[str, str]] = {}
        for rec in normlist:
            d = rec['date']
            span = rec['span']
            if d not in sh:
                sh[d] = {}
            sh[d][span] = calculatehash(color=rec['color'])
        
        spanhashes[queuekey] = sh
    
    return normbyqueue, mainhashes, spanhashes


def loadlaststate():
    """ lasthash.json + previous.json """
    hashdata = loadjson(HASHFILE)
    prevnorm = loadjson(PREVIOUSFILE)
    return (
        hashdata.get('timestamp'),
        hashdata.get('mainhashes', {}),
        hashdata.get('spanhashes', {}),
        prevnorm,
    )


def savestate(mainhashes: Dict[str, str], spanhashes: Dict[str, Dict[str, Dict[str, str]]], timestamp: str) -> None:
    """ lasthash.json """
    data = {
        'timestamp': timestamp,
        'mainhashes': mainhashes,
        'spanhashes': spanhashes,
    }
    savejson(data, HASHFILE)


def parsespan(span: str) -> Tuple[str, str]:
    """ 00:00-00:30 → 00:00, 00:30 """
    if not span or '-' not in span:
        return '', ''
    
    start, end = span.split('-')
    if ':' in start:
        return start, end
    return f'{start.zfill(2)}:00', f'{end.zfill(2)}:00'


def groupspans(spanschanges: List[Dict]) -> List[Dict]:
    """ """
    result: List[Dict] = []
    current: Optional[Dict] = None
    
    for item in sorted(spanschanges, key=lambda x: x['span']):
        starttime, endtime = parsespan(item['span'])
        if not current:
            current = {'start': starttime, 'end': endtime, 'change': item['change']}
        elif (current['change'] == item['change'] and current['end'] == starttime):
            current['end'] = endtime
        else:
            result.append(current)
            current = {'start': starttime, 'end': endtime, 'change': item['change']}
    
    if current:
        result.append(current)
    
    return result


def builddiff(normbyqueue: Dict[str, List[Dict]], mainhashes: Dict[str, str], 
              spanhashes: Dict[str, Dict[str, Dict[str, str]]], laststate: Dict) -> Dict:
    """ """
    lastmain = laststate.get('mainhashes', {})
    lastspan = laststate.get('spanhashes', {})
    lastnorm = laststate.get('normbyqueue', {})
    
    diff = {
        'queues': [],
        'perqueue': {},
        'newdates': [],
    }
    
    for queuekey, curmainhash in mainhashes.items():
        oldmainhash = lastmain.get(queuekey)
        if oldmainhash is None:
            logtobuffer(f'{queuekey}: skip (no previous hash)')
            continue
        
        if oldmainhash == curmainhash:
            continue
        
        logtobuffer(f'{queuekey}: mainhash changed')
        
        cursh = spanhashes.get(queuekey, {})
        oldsh = lastspan.get(queuekey, {})
        
        # 🔥 ФІКС: обробка переходу з порожньої черги
        if not oldsh:
            newdates = sorted(cursh.keys())
            logtobuffer(f'{queuekey}: new data from empty state! {newdates}')
        else:
            newdates = sorted(d for d in cursh if d not in oldsh)
            logtobuffer(f'{queuekey}: cursh={spanhashes.get(queuekey)}, oldsh={lastspan.get(queuekey)}')
        
        if newdates:
            logtobuffer(f'{queuekey}: newdates {newdates}')
            if newdates[0] not in diff['newdates']:
                diff['newdates'].append(newdates[0])
        
        changeddates = {}
        curitems = normbyqueue.get(queuekey, [])
        olditemslist = lastnorm.get(queuekey, [])
        
        for d in cursh.keys():
            if d in newdates:
                continue
            
            curspans = cursh.get(d, {})
            oldspans = oldsh.get(d, {})
            changesfordate = []
            
            for span, curspanhash in curspans.items():
                oldspanhash = oldspans.get(span)
                if oldspanhash == curspanhash:
                    continue
                
                logtobuffer(f'  {span} {d}')
                
                newrec = next((r for r in curitems if r['date'] == d and r['span'] == span), None)
                oldrec = next((r for r in olditemslist if r['date'] == d and r['span'] == span), None)
                
                if newrec and oldrec:
                    logtobuffer(f'    color={oldrec["color"]} → {newrec["color"]}')
                    if newrec['color'] != oldrec['color']:
                        change = 'added' if newrec['color'] == 'red' else 'removed'
                        changesfordate.append({'span': span, 'change': change})
                        logtobuffer(f'    {change}')
                else:
                    logtobuffer(f'    newrec={bool(newrec)}, oldrec={bool(oldrec)}')
            
            if changesfordate:
                grouped = groupspans(changesfordate)
                changeddates[d] = grouped
                logtobuffer(f'{d}: {len(changesfordate)} → {len(grouped)} groups')
        
        if newdates or changeddates:
            diff['queues'].append(queuekey)
            diff['perqueue'][queuekey] = {'newdates': newdates, 'changeddates': changeddates}
            logtobuffer(f'{queuekey} → diff')
        else:
            logtobuffer(f'{queuekey}: no actionable changes')
    
    return diff


def buildchangesnotification(diff: Dict, url: str, subscribe: str, updatestr: str) -> str:
    """ """
    queueswithchanges = []
    for q in sorted(diff['queues']):
        info = diff['perqueue'].get(q, {})
        if info.get('changeddates'):
            queueswithchanges.append(q)
    
    if not queueswithchanges:
        return ''
    
    queues = ', '.join(queueswithchanges)
    parts = []
    parts.append(f'🔄 {queues}!')
    parts.append('📅 changeddates...')
    
    updatedatestr = ''
    if updatestr:
        import re
        match = re.search(r'22\.2\.4', updatestr)
        if match:
            updatedatestr = f' ({match.group(1)}-{match.group(2)})'
    
    dateswithchanges = set()
    for q in queues:
        info = diff['perqueue'].get(q, {})
        for d in info.get('changeddates', {}).keys():
            dateswithchanges.add(d)
    
    for date in sorted(dateswithchanges):
        try:
            dt = datetime.strptime(date, '%Y-%m-%d')
            formatteddate = dt.strftime('%d.%m.%Y')
        except ValueError:
            formatteddate = date
        
        parts.append(f'📅 {formatteddate}')
        
        for queuekey in sorted(queues, key=lambda x: tuple(map(int, x.split('.')))):
            queueinfo = diff['perqueue'].get(queuekey, {})
            if date not in queueinfo.get('changeddates', {}):
                continue
            
            ranges = queueinfo['changeddates'][date]
            for r in ranges:
                start = r['start'].lstrip('0') or '00:00'
                end = r['end'].lstrip('0') or '00:00'
                if start.startswith(':'):
                    start = '0' + start
                if end.startswith(':'):
                    end = '0' + end
                
                if r['change'] == 'added':
                    action = '🟥'
                    parts.append(f'{queuekey}: {start}-{end} {action}')
                else:
                    action = '🟢'
                    parts.append(f'{queuekey}: {start}-{end}s {action}')
    
    parts.append('')
    parts.append(f'🔗 <a href="{url}">🔗</a> | <a href="{subscribe}">📱</a>')
    
    if updatedatestr:
        parts.append(updatedatestr)
    
    return '\n'.join(parts)


def buildnewschedulenotification(diff: Dict, normbyqueue: Dict[str, List[Dict]], url: str, subscribe: str, updatestr: str) -> str:
    """ """
    queueswithnewdates = []
    for q in sorted(diff['queues']):
        info = diff['perqueue'].get(q, {})
        if info.get('newdates'):
            queueswithnewdates.append(q)
    
    if not queueswithnewdates:
        return ''
    
    parts = []
    parts.append('🆕 !')
    parts.append('📅 newdates...')
    
    updatedatestr = ''
    if updatestr:
        import re
        match = re.search(r'22\.2\.4', updatestr)
        if match:
            updatedatestr = f' ({match.group(1)}-{match.group(2)})'
    
    for date in sorted(diff.get('newdates', [])):
        try:
            dt = datetime.strptime(date, '%Y-%m-%d')
            formatteddate = dt.strftime('%d.%m.%Y')
        except ValueError:
            formatteddate = date
        
        parts.append(f'📅 {formatteddate}')
        
        for queuekey in sorted(queueswithnewdates, key=lambda x: tuple(map(int, x.split('.')))):
            records = normbyqueue.get(queuekey, [])
            outages = [r for r in records if r['date'] == date and r['color'] == 'red']
            
            if outages:
                grouped = groupspans([{'span': o['span'], 'change': 'added'} for o in outages])
                
                timeranges = []
                for g in grouped:
                    start = g['start'].lstrip('0') or '00:00'
                    end = g['end'].lstrip('0') or '00:00'
                    if start.startswith(':'):
                        start = '0' + start
                    if end.startswith(':'):
                        end = '0' + end
                    timeranges.append(f'{start}-{end}')
                
                timesstr = ', '.join(timeranges)
                parts.append(f'{queuekey}: {timesstr}')
    
    parts.append('')
    parts.append(f'🔗 <a href="{url}">🔗</a> | <a href="{subscribe}">📱</a>')
    
    if updatedatestr:
        parts.append(updatedatestr)
    
    return '\n'.join(parts)


def sendnotificationsafe(message: str, imgpath: Optional[str] = None) -> bool:
    """ Telegram """
    CAPTIONLIMIT = 1024
    TEXTLIMIT = 4096
    
    msglen = len(message)
    logtobuffer(f'msglen={msglen}')
    
    if imgpath and msglen > CAPTIONLIMIT:
        logtobuffer(f'msglen>{CAPTIONLIMIT} caption, +{imgpath}')
        caption = message[:CAPTIONLIMIT-100] + '...'
        return sendnotification(caption, imgpath)
    
    if msglen > TEXTLIMIT:
        logtobuffer(f'msglen>{TEXTLIMIT}, truncate')
        message = message[:TEXTLIMIT-100] + '...'
        return sendnotification(message, None)
    
    if not imgpath and msglen > TEXTLIMIT:
        logtobuffer(f'msglen>{TEXTLIMIT}, truncate')
        message = message[:TEXTLIMIT-100] + '...'
        return sendnotification(message, imgpath)
    
    return sendnotification(message, imgpath)


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logtobuffer('=' * 60)
    logtobuffer(f'[{timestamp}]')
    logtobuffer('=' * 60)
    
    try:
        # 1. API
        currentschedules, haserror = fetchallschedules()
        if not currentschedules:
            logtobuffer('return (1. API empty)')
            return
        
        # 2. 
        normbyqueue, currentmainhashes, currentspanhashes = buildstate(currentschedules, haserror)
        logtobuffer(f'len(currentmainhashes)={len(currentmainhashes)}')
        
        # 3. current.json → previous.json
        if CURRENTFILE.exists():
            shutil.copy(CURRENTFILE, PREVIOUSFILE)
            logtobuffer('current.json → previous.json')
        savejson(normbyqueue, CURRENTFILE)
        logtobuffer('data→current.json')
        
        # 4. lasthash.json
        laststate = loadlaststate()
        logtobuffer('lasthash.json')
        
        # 5. diff
        diff = builddiff(normbyqueue, currentmainhashes, currentspanhashes, laststate)
        if not diff.get('queues') and not diff.get('newdates'):
            logtobuffer('no changes')
            savestate(currentmainhashes, currentspanhashes, timestamp)
            return
        
        logtobuffer(f'diff: {", ".join(diff.get("queues", []))}')
        
        # 6. 
        datecontent = getschedulecontent()
        logtobuffer('datecontent')
        
        # 7. 
        screenshotpath, screenshothash = takescreenshotbetweenelements()
        if not screenshotpath:
            logtobuffer('no screenshot')
        from pathlib import Path as Path
        imgpath = Path(screenshotpath) if screenshotpath else None
        logtobuffer(f'imgpath={imgpath}')
        
        # 8. 
        hasnewdates = bool(diff.get('newdates'))
        haschanges = any(qinfo.get('changeddates') for qinfo in diff.get('perqueue', {}).values())
        logtobuffer(f'hasnewdates={hasnewdates}, haschanges={haschanges}')
        
        if haschanges and not hasnewdates:
            logtobuffer('changes only')
            changesmsg = buildchangesnotification(diff, URL, SUBSCRIBE, datecontent or '')
            if changesmsg:
                ok = sendnotificationsafe(changesmsg, imgpath)
                if ok:
                    logtobuffer('✅ changes sent')
                else:
                    logtobuffer('❌ changes failed')
            else:
                logtobuffer('no changesmsg')
                
        elif hasnewdates and not haschanges:
            logtobuffer('newdates only')
            newmsg = buildnewschedulenotification(diff, normbyqueue, URL, SUBSCRIBE, datecontent or '')
            if newmsg:
                ok = sendnotificationsafe(newmsg, imgpath)
                if ok:
                    logtobuffer('✅ newdates sent')
                else:
                    logtobuffer('❌ newdates failed')
            else:
                logtobuffer('no newmsg')
                
        elif haschanges and hasnewdates:
            logtobuffer('both')
            changesmsg = buildchangesnotification(diff, URL, SUBSCRIBE, datecontent or '')
            if changesmsg:
                ok1 = sendnotificationsafe(changesmsg, imgpath)
                if ok1:
                    logtobuffer('✅ changes sent')
                else:
                    logtobuffer('❌ changes failed')
            
            logtobuffer('newdates msg')
            newmsg = buildnewschedulenotification(diff, normbyqueue, URL, SUBSCRIBE, datecontent or '')
            if newmsg:
                ok2 = sendnotificationsafe(newmsg, None)
                if ok2:
                    logtobuffer('✅ newdates sent')
                else:
                    logtobuffer('❌ newdates failed')
            else:
                logtobuffer('no newmsg')
        
        savestate(currentmainhashes, currentspanhashes, timestamp)
        logtobuffer('data→lasthash.json')
        
    except Exception as e:
        logtobuffer(f'❌ {e}')
    finally:
        sendlogtochannel(logtobuffer())


if __name__ == '__main__':
    main()
