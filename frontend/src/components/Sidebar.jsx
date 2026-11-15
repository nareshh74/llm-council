import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const shown = q
    ? conversations.filter((c) => (c.title || 'New Conversation').toLowerCase().includes(q))
    : conversations;

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
        <input
          className="conversation-search"
          type="search"
          placeholder="Search conversations"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="conversation-list">
        {shown.length === 0 ? (
          <div className="no-conversations">
            {conversations.length === 0 ? 'No conversations yet' : 'No matching conversations'}
          </div>
        ) : (
          shown.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-title">
                {conv.title || 'New Conversation'}
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages
              </div>
              {conv.folder && (
                <div className="conversation-folder" title={conv.folder}>
                  {conv.folder.split(/[\\/]/).filter(Boolean).pop()}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
