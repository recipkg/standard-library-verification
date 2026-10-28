"""Exercise the Canvas session socket against a disposable real server."""
import asyncio
import json
import sys

import websockets
from websockets.exceptions import ConnectionClosed


async def connect(uri):
    ws = await websockets.connect(uri, open_timeout=10)
    await ws.send(json.dumps({'type': 'auth', 'session_api_key': 'fixture-session-key'}))
    return ws


async def frame(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=12))


async def replay(uri, cursor, expected):
    async with await connect(uri + f'?after_seq={cursor}') as ws:
        sync = await frame(ws)
        assert sync['type'] == 'sync' and sync['from_seq'] == cursor, sync
        received = {}
        while not expected.issubset(received):
            item = await frame(ws)
            if item['type'] == 'durable':
                event_id = item['event']['id']
                assert item['seq'] > cursor and event_id not in received, item
                received[event_id] = item['seq']
        assert set(received) == expected, received
        return sync, received


async def main(data):
    uri = f"ws://127.0.0.1:{data['port']}/sockets/session/{data['conversation_id']}"
    expected = {event['id'] for event in data['events']}
    assert expected
    if data['mode'] == 'snapshot':
        sync, received = await replay(uri, -1, expected)
        assert sync['through_seq'] == max(received.values())
        print(json.dumps(received))
        return

    async with websockets.connect(uri, open_timeout=10) as ws:
        await ws.send(json.dumps({'type': 'auth', 'session_api_key': 'wrong-key'}))
        try:
            await frame(ws)
            raise AssertionError('invalid authentication was accepted')
        except ConnectionClosed as error:
            assert error.rcvd is not None and error.rcvd.code == 4001

    # No cursor requests live events only, even when history exists.
    async with await connect(uri) as ws:
        sync = await frame(ws)
        assert sync['type'] == 'sync' and sync.get('from_seq') is None
        deadline = asyncio.get_running_loop().time() + 0.4
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                item = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                assert item['type'] != 'durable', 'unexpected history without cursor'
            except TimeoutError:
                break

    previous = data['snapshot']
    sync, restored = await replay(uri, -1, expected)
    assert restored == previous, 'durable sequence changed across normal restart'
    through = sync['through_seq']
    cursor = sorted(restored.values())[len(restored) // 2]
    tail = {event_id for event_id, seq in restored.items() if seq > cursor}
    tail_sync, tail_received = await replay(uri, cursor, tail)
    assert tail_sync['through_seq'] == through
    assert tail_received == {event_id: previous[event_id] for event_id in tail}

    async with await connect(uri + f'?after_seq={through}') as ws:
        sync = await frame(ws)
        assert sync['type'] == 'sync' and sync['from_seq'] == through
        await ws.send('not-json')
        error = await frame(ws)
        while error['type'] != 'error':
            error = await frame(ws)
        assert error['type'] == 'error', error
        await ws.send(json.dumps({'role': 'user', 'content': 'session fixture message'}))
        live = {}
        deadline = asyncio.get_running_loop().time() + 20
        seen_user = seen_agent = False
        while not (seen_user and seen_agent):
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, 'live session events timed out'
            item = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if item['type'] == 'durable':
                event = item['event']
                assert item['seq'] > through
                live[event['id']] = item['seq']
                if event.get('kind') == 'MessageEvent':
                    seen_user |= event.get('source') == 'user' and 'session fixture message' in json.dumps(event)
                    seen_agent |= event.get('source') == 'agent' and 'fixture reply' in json.dumps(event)
    # Reconnect from the old cursor; both newly persisted message IDs must replay.
    _, replayed = await replay(uri, through, set(live))
    assert all(replayed[event_id] == seq for event_id, seq in live.items())
    print(json.dumps({'result': 'session authentication, restart, cursor and live messaging passed'}))


if __name__ == '__main__':
    asyncio.run(main(json.load(sys.stdin)))
