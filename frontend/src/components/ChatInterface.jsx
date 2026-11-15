import { useState, useEffect, useRef } from 'react';
import Markdown from './Markdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import FolderPicker from './FolderPicker';
import Activity from './Activity';
import './ChatInterface.css';

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`);
  if (Number.isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return d.toDateString() === new Date().toDateString()
    ? time
    : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${time}`;
}

function messageText(msg) {
  return msg.role === 'user' ? msg.content || '' : msg.stage3?.response || '';
}

export default function ChatInterface({
  conversation,
  onSendMessage,
  onSetFolder,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState({ key: '', index: 0 });
  const messagesEndRef = useRef(null);
  const q = search.trim().toLowerCase();
  const matches = q
    ? (conversation?.messages || []).flatMap((m, i) =>
        messageText(m).toLowerCase().includes(q) ? [i] : []
      )
    : [];
  const searchKey = `${conversation?.id}|${q}`;
  const current = position.key === searchKey ? Math.min(position.index, Math.max(matches.length - 1, 0)) : 0;
  const currentMsg = matches[current];

  useEffect(() => {
    if (currentMsg !== undefined) {
      document
        .querySelector(`[data-msg-index="${currentMsg}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [currentMsg, searchKey]);

  const step = (delta) => {
    if (matches.length) {
      setPosition({ key: searchKey, index: (current + delta + matches.length) % matches.length });
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (!q) scrollToBottom();
  }, [conversation, q]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      {conversation.messages.length === 0 ? (
        <FolderPicker folder={conversation.folder} onChange={onSetFolder} />
      ) : (
        conversation.folder && (
          <div className="folder-banner">Folder: {conversation.folder}</div>
        )
      )}
      {conversation.messages.length > 0 && (
        <div className="message-search">
          <input
            type="search"
            className="message-search-input"
            placeholder="Search in this conversation"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                step(e.shiftKey ? -1 : 1);
              }
            }}
          />
          {q && (
            <span className="message-search-count">
              {matches.length ? `${current + 1} of ${matches.length}` : 'No matches'}
            </span>
          )}
          <button className="folder-btn" disabled={!matches.length} onClick={() => step(-1)}>
            Prev
          </button>
          <button className="folder-btn" disabled={!matches.length} onClick={() => step(1)}>
            Next
          </button>
        </div>
      )}
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div
              key={index}
              data-msg-index={index}
              className={`message-group${matches.includes(index) ? ' search-hit' : ''}${
                currentMsg === index ? ' search-current' : ''
              }`}
            >
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <Markdown>{msg.content}</Markdown>
                    </div>
                  </div>
                  {formatTime(msg.created_at) && (
                    <div className="message-time">{formatTime(msg.created_at)}</div>
                  )}
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  <Activity
                    events={msg.activity}
                    live={isLoading && index === conversation.messages.length - 1}
                  />

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}
                  {formatTime(msg.created_at) && (
                    <div className="message-time">{formatTime(msg.created_at)}</div>
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        <textarea
          className="message-input"
          placeholder={conversation.messages.length === 0 ? "Ask your question... (Shift+Enter for new line, Enter to send)" : "Ask a follow-up... (Shift+Enter for new line, Enter to send)"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          rows={3}
        />
        <button
          type="submit"
          className="send-button"
          disabled={!input.trim() || isLoading}
        >
          Send
        </button>
      </form>
    </div>
  );
}
