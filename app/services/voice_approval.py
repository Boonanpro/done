"""Short-lived proof binding a semantic voice approval to one proposal.

The voice intake issues it only after classifying the current user reply. This
avoids racing the asynchronous transcript save or re-parsing intent with regex.
The job state machine still checks proposal ID/revision and consumes the grant.
"""
import hashlib
import time
from jose import jwt, JWTError
from app.services.auth_service import get_jwt_secret

def issue(user_id, room_id, job_id, proposal_id, text):
    return jwt.encode({'sub':user_id,'room':room_id,'job':job_id,'proposal':proposal_id,
        'text':hashlib.sha256(text.encode()).hexdigest(),'exp':int(time.time())+60,
        'aud':'voice-confirmation'},get_jwt_secret()+'_voice_confirmation',algorithm='HS256')

def valid(token, user_id, room_id, job_id, proposal_id, text):
    try:
        claims=jwt.decode(token,get_jwt_secret()+'_voice_confirmation',algorithms=['HS256'],audience='voice-confirmation')
        return all(claims.get(k)==v for k,v in {'sub':user_id,'room':room_id,'job':job_id,
            'proposal':proposal_id,'text':hashlib.sha256(text.encode()).hexdigest()}.items())
    except (JWTError,TypeError,ValueError):return False
