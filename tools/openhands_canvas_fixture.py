"""Disposable loopback Canvas static host, Agent Server and scripted model.

This is an integration fixture, not a production proxy or a security sandbox.
Run with the candidate server's Python and an explicit prebuilt Canvas directory.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from aiohttp import ClientSession, web, WSMsgType

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

async def main(ROOT, BUILD):
    server_port, proxy_port, model_port = free_port(), free_port(), free_port()
    for name in ('home', 'work', 'tmux', 'conversations'):
        (ROOT / name).mkdir(exist_ok=True)
    env = {'PATH': os.defpath, 'HOME': str(ROOT / 'home'), 'TMPDIR': str(ROOT), 'LANG': 'C.UTF-8',
           'TMUX_TMPDIR': str(ROOT / 'tmux'), 'OPENHANDS_SUPPRESS_BANNER': '1',
           'OH_ENABLE_VSCODE': 'false', 'OH_PRELOAD_TOOLS': 'false',
           'OH_CONVERSATIONS_PATH': str(ROOT / 'conversations'), 'OH_SESSION_API_KEYS_0': 'fixture-session-key',
           'DO_NOT_TRACK': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'LITELLM_TELEMETRY': 'False'}
    log = (ROOT / 'server.log').open('w')
    server = subprocess.Popen([sys.executable, '-m', 'openhands.agent_server', '--host', '127.0.0.1',
                               '--port', str(server_port)], cwd=ROOT / 'work', env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    session = ClientSession()
    async def model(req):
        data = await req.json()
        with (ROOT / 'model-requests.jsonl').open('a') as out:
            out.write(json.dumps(data) + '\n')
        finish_available = any(t.get('function', {}).get('name') == 'finish' for t in data.get('tools', []))
        message = {'role':'assistant','content':'Canvas fixture reply'}
        if finish_available:
            message['tool_calls'] = [{'id':'call-finish-fixture','type':'function',
                                      'function':{'name':'finish','arguments':json.dumps({'message':'Canvas fixture reply'})}}]
        if data.get('stream'):
            response = web.StreamResponse(headers={'Content-Type':'text/event-stream'})
            await response.prepare(req)
            deltas = [{'role':'assistant','content':'Canvas fixture reply'}]
            if finish_available:
                deltas.append({'tool_calls':[{'index':0, **message['tool_calls'][0]}]})
            for delta in deltas + [None]:
                chunk = {'id':'fixture-response','object':'chat.completion.chunk','created':0,
                         'model':'gpt-4o-mini','choices':[{'index':0,'delta':delta or {},
                          'finish_reason':('tool_calls' if finish_available else 'stop') if delta is None else None}]}
                await response.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
            await response.write(b'data: [DONE]\n\n')
            await response.write_eof()
            return response
        return web.json_response({'id':'fixture-response', 'model':'gpt-4o-mini', 'created':0,
            'object':'chat.completion', 'choices':[{'index':0,
                'message':message, 'finish_reason':'tool_calls' if finish_available else 'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    async def handler(req):
        if req.path.startswith('/sockets/'):
            client = web.WebSocketResponse(); await client.prepare(req)
            async with session.ws_connect(f'http://127.0.0.1:{server_port}{req.rel_url}') as upstream:
                async def copy(src, dst):
                    async for msg in src:
                        if msg.type == WSMsgType.TEXT: await dst.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY: await dst.send_bytes(msg.data)
                    await dst.close()
                await asyncio.gather(copy(client, upstream), copy(upstream, client))
            return client
        if req.path.startswith('/api/') or req.path in ('/ready', '/alive', '/health', '/server_info'):
            headers = {k:v for k,v in req.headers.items() if k.lower() not in ('host','content-length','connection')}
            async with session.request(req.method, f'http://127.0.0.1:{server_port}{req.rel_url}',
                                       data=await req.read(), headers=headers) as upstream:
                return web.Response(status=upstream.status, body=await upstream.read(),
                                    headers={k:v for k,v in upstream.headers.items()
                                             if k.lower() not in ('transfer-encoding','content-length','connection')})
        path = (BUILD / req.path.lstrip('/')).resolve()
        if not path.is_relative_to(BUILD) or not path.is_file(): path = BUILD / 'index.html'
        if path.name == 'index.html':
            inject = '''<script>window.__AGENT_CANVAS_SESSION_API_KEY__="fixture-session-key";
            window.__AGENT_CANVAS_DO_NOT_TRACK__=true;
            localStorage.setItem("analytics-consent","false");
            localStorage.setItem("openhands-telemetry-consent","denied");
            localStorage.setItem("openhands-onboarded","1");
            localStorage.setItem("openhands-backends",JSON.stringify([{id:"default-local",name:"Local",host:location.origin,apiKey:"fixture-session-key",kind:"local"}]));</script>'''
            return web.Response(text=path.read_text().replace('</head>', inject + '</head>'), content_type='text/html')
        return web.FileResponse(path)
    model_app = web.Application(); model_app.router.add_post('/v1/chat/completions', model)
    proxy_app = web.Application(client_max_size=10*1024*1024); proxy_app.router.add_route('*', '/{path:.*}', handler)
    model_runner, proxy_runner = web.AppRunner(model_app), web.AppRunner(proxy_app)
    try:
        await model_runner.setup(); await proxy_runner.setup()
        await web.TCPSite(model_runner, '127.0.0.1', model_port).start()
        await web.TCPSite(proxy_runner, '127.0.0.1', proxy_port).start()
        for _ in range(300):
            if server.poll() is not None: raise RuntimeError(f'server exited {server.returncode}')
            try:
                async with session.get(f'http://127.0.0.1:{server_port}/ready') as response:
                    if response.status == 200: break
            except Exception: pass
            await asyncio.sleep(.1)
        else: raise RuntimeError('server readiness timed out')
        print(json.dumps({'canvas_url':f'http://127.0.0.1:{proxy_port}',
                          'model_base_url':f'http://127.0.0.1:{model_port}/v1',
                          'workspace':str(ROOT / 'work'), 'session_key':'fixture-session-key'}), flush=True)
        await asyncio.Event().wait()
    finally:
        await proxy_runner.cleanup(); await model_runner.cleanup(); await session.close()
        server.terminate()
        try: server.wait(timeout=15)
        except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=5)
        log.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', required=True, type=Path, help='prebuilt Canvas static directory')
    parser.add_argument('--temp-parent', type=Path, help='optional parent for disposable data')
    args = parser.parse_args()
    build = args.build_dir.resolve(strict=True)
    if not (build / 'index.html').is_file():
        parser.error('--build-dir must contain index.html')
    with tempfile.TemporaryDirectory(prefix='openhands-canvas-', dir=args.temp_parent) as temp:
        try:
            asyncio.run(main(Path(temp), build))
        except KeyboardInterrupt:
            pass
