import assert from 'node:assert/strict';

import worker, {
  SERVICE_NAME,
  SERVICE_VERSION,
  WIDGET_MIME,
  WIDGET_URI,
  clearO3ReplyCardMemory,
  handleO3ReplyCardRequest,
} from './worker.js';

async function rpc(method, params = {}, options = {}) {
  const request = new Request(options.url || 'https://o3-mcp.example.test/mcp', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(options.accept ? { accept: options.accept } : {}),
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: options.id || 1,
      method,
      params,
    }),
  });
  return handleO3ReplyCardRequest(request);
}

clearO3ReplyCardMemory();

const health = await worker.fetch(new Request('https://o3-mcp.example.test/health'));
assert.equal(health.status, 200);
assert.deepEqual(await health.json(), {
  status: 'ok',
  service: SERVICE_NAME,
  version: SERVICE_VERSION,
});

const fallbackHealth = await worker.fetch(
  new Request('https://mcp.example.test/o3/health')
);
assert.equal(fallbackHealth.status, 200);

const initialized = await rpc('initialize', { protocolVersion: '2025-06-18' });
assert.equal(initialized.status, 200);
assert.ok(initialized.headers.get('mcp-session-id'));
assert.equal((await initialized.json()).result.serverInfo.name, SERVICE_NAME);

const toolsResponse = await rpc('tools/list');
const tools = (await toolsResponse.json()).result.tools;
assert.equal(tools.length, 1);
assert.equal(tools[0].name, 'o3_reply_card');
assert.equal(JSON.stringify(tools).includes('render_thinking_block'), false);
assert.equal(JSON.stringify(tools).includes('thinking'), false);

const body = '如果你能看到这段话，说明 Cloudflare 回复卡正文可见。';
const writeResponse = await rpc('tools/call', {
  name: 'o3_reply_card',
  arguments: {
    action: 'write_reply',
    session_id: 'worker-test',
    title: 'o3 回复测试',
    user_anchor: '测试 Cloudflare Worker',
    body,
    continuity_state: '本轮完成 Worker 写卡测试。',
    footer: '本轮结束',
    skin: 'winter',
  },
});
const writeResult = (await writeResponse.json()).result;
assert.equal(writeResult.isError, false);
assert.ok(writeResult.content[0].text.includes('O3_REPLY_CARD_CONTEXT_BEGIN'));
assert.ok(writeResult.content[0].text.includes(body));
assert.equal(writeResult.structuredContent.body, body);
assert.equal(writeResult._meta.body, body);

const readResponse = await rpc('tools/call', {
  name: 'o3_reply_card',
  arguments: {
    action: 'read_context',
    session_id: 'worker-test',
    history_limit: 10,
  },
});
const readResult = (await readResponse.json()).result;
assert.ok(readResult.content[0].text.includes(body));
assert.ok(readResult.content[0].text.includes('本轮完成 Worker 写卡测试。'));

const tooLong = await rpc('tools/call', {
  name: 'o3_reply_card',
  arguments: {
    action: 'write_reply',
    session_id: 'worker-test',
    body: 'x'.repeat(8001),
  },
});
const tooLongResult = (await tooLong.json()).result;
assert.equal(tooLongResult.isError, true);
assert.ok(tooLongResult.content[0].text.includes('hard maximum is 8000'));
assert.ok(tooLongResult.content[0].text.includes('did not truncate or store'));

for (let index = 0; index < 12; index += 1) {
  const response = await rpc('tools/call', {
    name: 'o3_reply_card',
    arguments: {
      action: 'write_reply',
      session_id: 'ring-test',
      body: 'body-' + index,
      continuity_state: 'state-' + index,
    },
  });
  assert.equal(response.status, 200);
}
const ringRead = await rpc('tools/call', {
  name: 'o3_reply_card',
  arguments: {
    action: 'read_context',
    session_id: 'ring-test',
    history_limit: 10,
  },
});
const ringText = (await ringRead.json()).result.content[0].text;
assert.equal(ringText.includes('\nstate-0\n'), false);
assert.equal(ringText.includes('\nstate-1\n'), false);
assert.ok(ringText.includes('state-2'));
assert.ok(ringText.includes('state-11'));
assert.equal(ringText.includes('body-8'), false);
assert.ok(ringText.includes('body-9'));
assert.ok(ringText.includes('body-10'));
assert.ok(ringText.includes('body-11'));

const isolated = await rpc('tools/call', {
  name: 'o3_reply_card',
  arguments: {
    action: 'read_context',
    session_id: 'different-session',
  },
});
assert.equal((await isolated.json()).result.content[0].text.includes(body), false);

const resourcesResponse = await rpc('resources/list');
const resources = (await resourcesResponse.json()).result.resources;
assert.equal(resources.length, 1);
assert.equal(resources[0].uri, WIDGET_URI);
assert.equal(resources[0].mimeType, WIDGET_MIME);

const resourceResponse = await rpc('resources/read', { uri: WIDGET_URI });
const resource = (await resourceResponse.json()).result.contents[0];
assert.equal(resource.uri, WIDGET_URI);
assert.equal(resource.mimeType, WIDGET_MIME);
assert.ok(resource.text.includes('o3 回复用'));
assert.ok(resource.text.includes('openai:set_globals'));

const sseResponse = await rpc(
  'ping',
  {},
  { accept: 'application/json, text/event-stream' }
);
assert.equal(sseResponse.headers.get('content-type'), 'text/event-stream');
assert.ok((await sseResponse.text()).includes('event: message'));

const fallbackTools = await rpc(
  'tools/list',
  {},
  { url: 'https://mcp.elementeracoast.com/o3/mcp' }
);
assert.equal((await fallbackTools.json()).result.tools[0].name, 'o3_reply_card');

console.log('Cloudflare Worker contract: OK');
