import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { McpIntegrations } from './McpIntegrations';

const config = { server_id: 'mcp_1', scope: { tenant_id: 't', actor_id: 'u', agent_id: 'klara' }, name: 'Research tools', transport: 'stdio', command: 'python', args: ['server.py'], endpoint: null, credential_ref: null, env_ref_names: [], enabled: true, created_at: '', updated_at: '' };
const disconnected = { schema_version: 'klara.mcp-state.v1', servers: [{ config, connection: { server_id: 'mcp_1', status: 'disconnected', reconnect_count: 0, catalog: null } }], audit: [{ event_id: 'a1', server_id: 'mcp_1', operation: 'configured', outcome: 'success', occurred_at: '2026-08-13T00:00:00Z', details: {} }] };
const connected = { ...disconnected, servers: [{ config, connection: { server_id: 'mcp_1', status: 'connected', reconnect_count: 0, catalog: { protocol_version: '2025-11-25', server_name: 'fixture', server_version: '1', capabilities: { tools: {} }, tools: [{ name: 'echo' }], resources: [{ name: 'Guide', uri: 'fixture://guide' }], prompts: [{ name: 'brief' }] } } }] };

afterEach(() => vi.restoreAllMocks());

it('renders negotiated capabilities after an approved connect', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(json(disconnected))
    .mockResolvedValueOnce(json(connected.servers[0].connection))
    .mockResolvedValueOnce(json(connected));
  render(<McpIntegrations onBackToChat={() => undefined} onOpenPermissions={() => undefined} />);
  expect(await screen.findByText('Research tools')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(fetchMock.mock.calls[1][0]).toBe('/api/mcp/mcp_1/connect'));
  expect(await screen.findByText('echo')).toBeInTheDocument();
  expect(screen.getByText('Guide')).toBeInTheDocument();
  expect(screen.getByText('brief')).toBeInTheDocument();
});

it('shows the fail-closed approval path without claiming execution', async () => {
  const openPermissions = vi.fn();
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(json(disconnected))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: 'permission_required' } }), { status: 403 }))
    .mockResolvedValueOnce(json(disconnected));
  render(<McpIntegrations onBackToChat={() => undefined} onOpenPermissions={openPermissions} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));
  expect(await screen.findByText(/waiting for your approval/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Open permissions/i }));
  expect(openPermissions).toHaveBeenCalledTimes(1);
  expect(screen.getByText('disconnected')).toBeInTheDocument();
});

function json(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
