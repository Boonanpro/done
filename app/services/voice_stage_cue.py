"""Small fact cards; codes keep leading zeroes and are never guessed."""
import re

DIGITS = str.maketrans('〇零一二三四五六七八九０１２３４５６７８９', '001234567890123456789')

def clean(cue):
    if not isinstance(cue, dict): return None
    label = str(cue.get('label') or '').strip()[:60]
    value = str(cue.get('value') or '').strip()[:80]
    choices = [str(v).strip()[:120] for v in (cue.get('choices') or [])[:4]] if isinstance(cue.get('choices'),list) else []
    if not value and not choices: return None
    # Only digit-by-digit codes, never prose such as 千二百円.
    if re.fullmatch(r'[〇零一二三四五六七八九０-９\d\s]+', value): value = re.sub(r'\s+', '', value.translate(DIGITS))
    return {'label':label,'value':value,'detail':str(cue.get('detail') or '').strip()[:140],'choices':choices}

def from_words(text):
    match = re.search(r'(確認番号|承認番号|認証コード|ワンタイムパスワード)[はが：:\s]*[「『]?([0-9０-９〇零一二三四五六七八九\s]{4,20})[」』]?(?:です|を|。|[.!])', text)
    if not match: return None
    digits = re.sub(r'\s+','',match[2].translate(DIGITS))
    if not 4 <= len(digits) <= 8: return None
    return clean({'label':match[1],'value':digits})
