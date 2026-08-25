import type { AssistantChatInput } from '../api/types'

export interface AssistantChatPayloadOptions {
  history: Array<{ role: 'user' | 'assistant'; content: string }>
  allowNetworkSearch: boolean
  queryTypeOverride?: string
  assistantSessionId?: string
  maxTokens?: number
}

/**
 * Build the multi-agent chat request body shared by the streaming call and
 * its non-streaming fallback. The per-request `allow_network_search` opt-in
 * must always be present: the HCT-430 double gate means the deployment switch
 * alone can never trigger a search, and a checkbox that fails to reach the
 * request body silently disables the whole feature.
 */
export function buildAssistantChatInput(options: AssistantChatPayloadOptions): AssistantChatInput {
  return {
    messages: options.history.map(entry => ({ role: entry.role, content: entry.content })),
    max_tokens: options.maxTokens ?? 1024,
    agent_mode: 'multi_agent',
    allow_network_search: options.allowNetworkSearch,
    query_type_override: options.queryTypeOverride,
    assistant_session_id: options.assistantSessionId || undefined,
  }
}
