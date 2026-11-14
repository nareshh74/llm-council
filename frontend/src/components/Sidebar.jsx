import { useState, useEffect } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}) {
  const [folder, setFolder] = useState('');
  const [error, setError] = useState('');

  const create = async () => {
    const err = await onNewConversation(folder.trim());
    setError(err || '');
    if (!err) setFolder('');
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <input
          className="folder-input"
          placeholder="Folder (optional)"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
        />
        {error && <div className="folder-error">{error}</div>}
        <button className="new-conversation-btn" onClick={create}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
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
