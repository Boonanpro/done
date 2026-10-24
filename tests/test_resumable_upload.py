"""Exercise real disk transport without sending chat messages or using accounts."""
import hashlib
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import resumable_upload_routes as transfer


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "ROOT", tmp_path)
    monkeypatch.setattr(transfer, "STAGING", tmp_path / ".transfers")
    async def identity(request, room_id):
        if request.headers.get("x-user") == "denied":
            raise HTTPException(403)
        return request.headers.get("x-user", "owner")
    monkeypatch.setattr(transfer, "identity", identity)
    app = FastAPI()
    app.include_router(transfer.router)
    return TestClient(app)


def start(client, size, name="clip.mp4"):
    response = client.post("/transfers", json={"filename": name, "size": size, "content_type": "video/mp4"})
    assert response.status_code == 200, response.text
    return "/transfers/" + response.json()["id"]


def test_142mb_resume_and_integrity(client):
    size = 142 * 1024 * 1024
    path = start(client, size)
    block = bytes(range(256)) * (transfer.CHUNK // 256)
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = block[:min(len(block), size-offset)]
        response = client.put(path, params={"offset": offset}, content=chunk)
        assert response.status_code == 200, response.text
        digest.update(chunk)
        offset += len(chunk)
        # Simulate losing the response: query offset before continuing.
        assert client.get(path).json()["offset"] == offset
    result = client.post(path + "/complete")
    assert result.status_code == 200, result.text
    assert client.post(path + "/complete").json() == result.json()
    saved = transfer.ROOT / result.json()["url"].rsplit("/", 1)[1]
    with saved.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256") if hasattr(hashlib, "file_digest") else None
        if actual is None:
            actual=hashlib.sha256()
            while chunk:=source.read(transfer.CHUNK): actual.update(chunk)
    assert actual.digest() == digest.digest()


def test_partial_chunk_retry_ownership_and_order(client):
    path = start(client, 20)
    assert client.put(path+"?offset=0", content=b"short").status_code == 400
    assert client.get(path).json()["offset"] == 0
    assert client.post(path+"/complete").status_code == 409
    assert client.get(path, headers={"x-user":"other"}).status_code == 403
    assert client.put(path+"?offset=1",content=b"x"*20).status_code == 409
    assert client.put(path+"?offset=0",content=b"x"*21).status_code == 413
    assert client.put(path+"?offset=0",content=b"x"*20).status_code == 200
    assert client.put(path+"?offset=0",content=b"x"*20).status_code == 409
    assert client.post(path+"/complete").status_code == 200


def test_limits_type_expiry(client):
    assert client.post('/transfers',json={"filename":"clip.mp4","size":transfer.MAX_SIZE+1}).status_code == 422
    assert client.post('/transfers',json={"filename":"bad.exe","size":1}).status_code == 415
    path=start(client,1)
    meta=transfer.STAGING/(path.rsplit('/',1)[1]+'.json')
    data=json.loads(meta.read_text());data['created']=0;meta.write_text(json.dumps(data))
    assert client.get(path).status_code==410
    start(client,1)
    assert not meta.exists()


def test_collab_guest_finalize_and_idempotent_record(client, monkeypatch, tmp_path):
    from app.api import collab_routes
    from datetime import datetime, timezone
    records=[]
    class Service:
        async def save_file_record(self, **fields):
            record={**fields,"id":"record","created_at":datetime.now(timezone.utc)}
            records.append(record)
            return record
    monkeypatch.setattr(collab_routes,"UPLOAD_DIR",tmp_path/'collab')
    monkeypatch.setattr(collab_routes,"get_collab_service",Service)
    monkeypatch.setattr(collab_routes,"_decode_guest_token",lambda token:{"room_id":"room1"} if token=='guest' else None)
    client.headers['X-Guest-Token']='guest'
    response=client.post('/transfers',json={"filename":"audio.m4a","size":23,"room_id":"room1","content_type":"audio/mp4"})
    path='/transfers/'+response.json()['id']
    assert client.put(path+'?offset=0',content=b'a'*23).status_code==200
    result=client.post(path+'/complete')
    assert result.status_code==200,result.text
    assert result.json()['uploaded_by']=='guest'
    assert client.post(path+'/complete').json()==result.json()
    assert len(records)==1
