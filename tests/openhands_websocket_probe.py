"""Check real event WebSocket authentication, replay and live messaging."""
import asyncio
import json
import sys
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed


async def collect_ids(ws, expected):
    received = set()
    while not expected.issubset(received):
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if event.get('id'):
            received.add(event['id'])
    return received


async def main(data):
    base = f"ws://127.0.0.1:{data['port']}/sockets/events/{data['conversation_id']}"
    expected = {event['id'] for event in data['events']}
    assert expected

    async with websockets.connect(base, open_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'session_api_key': 'wrong-key'}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=10)
            raise AssertionError('invalid authentication was accepted')
        except ConnectionClosed as error:
            assert error.rcvd is not None and error.rcvd.code == 4001

    async with websockets.connect(base + '?resend_mode=all', open_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'session_api_key': 'fixture-session-key'}))
        received = await collect_ids(ws, expected)
        assert expected.issubset(received)

    cutoff = max(event['timestamp'] for event in data['events'])
    recent = {event['id'] for event in data['events'] if event['timestamp'] >= cutoff}
    older = expected - recent
    assert older, 'fixture needs events with distinct timestamps'
    query = urlencode({'resend_mode': 'since', 'after_timestamp': cutoff})
    async with websockets.connect(base + '?' + query, open_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'session_api_key': 'fixture-session-key'}))
        received = await collect_ids(ws, recent)
        assert received.isdisjoint(older), 'old events replayed after cutoff'
        try:
            extra = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
            assert extra.get('id') not in older, 'old event replayed after cutoff'
        except TimeoutError:
            pass
        await ws.send(json.dumps({'role': 'user', 'content': 'websocket fixture message'}))
        seen_user = seen_agent = False
        deadline = asyncio.get_running_loop().time() + 20
        while not (seen_user and seen_agent):
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, 'live events timed out'
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if event.get('kind') == 'MessageEvent':
                if event.get('source') == 'user' and 'websocket fixture message' in json.dumps(event):
                    seen_user = True
                if event.get('source') == 'agent' and 'fixture reply' in json.dumps(event):
                    seen_agent = True
    print('websocket authentication, replay and live messaging passed')


if __name__ == '__main__':
    asyncio.run(main(json.load(sys.stdin)))
