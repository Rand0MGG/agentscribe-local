"""Resume interrupted pinned archives without redownloading verified components."""
import hashlib
import io

import pytest

from linguaflow import llama_install


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Length': str(len(body)), **(headers or {})}


@pytest.mark.p1
def test_interrupted_component_resumes_then_is_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(llama_install, 'cache_root', lambda: tmp_path)
    body = b'A'*1024**2 + b'B'*1234
    digest = hashlib.sha256(body).hexdigest()
    requests = []

    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell():
                raise ConnectionError('fixture connection interrupted')
            return super().read(size)

    def fetch(request, timeout):
        requests.append(request.get_header('Range'))
        if len(requests)==1:
            return Interrupted(body)
        offset = 1024**2
        return Response(body[offset:], 206,
                        {'Content-Range': f'bytes {offset}-{len(body)-1}/{len(body)}'})

    monkeypatch.setattr(llama_install.urllib.request, 'urlopen', fetch)
    with pytest.raises(ConnectionError):
        llama_install.cached_archive('fixture.zip',digest)
    assert (tmp_path/'fixture.zip.part').stat().st_size==1024**2
    result = llama_install.cached_archive('fixture.zip',digest)
    assert result.read_bytes()==body and requests==[None,f'bytes={1024**2}-']
    assert llama_install.cached_archive('fixture.zip',digest)==result
    assert len(requests)==2


@pytest.mark.p1
@pytest.mark.parametrize('honor_range', [True,False])
def test_archive_range_handling_never_appends_a_full_response(tmp_path, monkeypatch, honor_range):
    monkeypatch.setattr(llama_install,'cache_root',lambda:tmp_path)
    body=b'complete archive bytes'
    (tmp_path/'fixture.zip.part').write_bytes(body[:5])
    def fetch(request, timeout):
        assert request.get_header('Range')=='bytes=5-'
        if honor_range:
            return Response(body[5:],206,{'Content-Range':f'bytes 5-{len(body)-1}/{len(body)}'})
        return Response(body)
    monkeypatch.setattr(llama_install.urllib.request,'urlopen',fetch)
    result=llama_install.cached_archive('fixture.zip',hashlib.sha256(body).hexdigest())
    assert result.read_bytes()==body


@pytest.mark.p1
def test_mismatched_resume_range_preserves_partial_and_never_publishes(tmp_path,monkeypatch):
    monkeypatch.setattr(llama_install,'cache_root',lambda:tmp_path)
    partial=tmp_path/'fixture.zip.part'
    partial.write_bytes(b'keep')
    monkeypatch.setattr(llama_install.urllib.request,'urlopen',
                        lambda *args,**kwargs:Response(b'bad',206,{'Content-Range':'bytes 0-2/3'}))
    with pytest.raises(ValueError,match='续传范围'):
        llama_install.cached_archive('fixture.zip','0'*64)
    assert partial.read_bytes()==b'keep' and not (tmp_path/'fixture.zip').exists()
