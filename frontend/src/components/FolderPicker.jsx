import { useState } from 'react';
import { api } from '../api';
import './FolderPicker.css';

export default function FolderPicker({ folder, onChange }) {
  const [listing, setListing] = useState(null);
  const [error, setError] = useState('');

  const open = async (path = '') => {
    try {
      setListing(await api.browse(path));
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  const choose = async (path) => {
    try {
      await onChange(path);
      setListing(null);
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  if (!listing) {
    return (
      <div className="folder-picker">
        <span className="folder-current">
          {folder ? `Folder: ${folder}` : 'No folder: plain chat'}
        </span>
        <button className="folder-btn" onClick={() => open(folder || '')}>
          {folder ? 'Change folder' : 'Choose folder'}
        </button>
        {folder && (
          <button className="folder-btn" onClick={() => choose(null)}>
            Clear
          </button>
        )}
        {error && <span className="folder-error">{error}</span>}
      </div>
    );
  }

  return (
    <div className="folder-picker open">
      <div className="folder-path">
        {listing.path || 'Choose a location'}
        {listing.parent && (
          <button className="folder-btn" onClick={() => open(listing.parent)}>
            Up
          </button>
        )}
        {listing.path && (
          <button className="folder-btn primary" onClick={() => choose(listing.path)}>
            Use this folder
          </button>
        )}
        <button className="folder-btn" onClick={() => setListing(null)}>
          Cancel
        </button>
      </div>
      <div className="folder-list">
        {listing.dirs.length === 0 && <div className="folder-empty">No subfolders</div>}
        {listing.dirs.map((d) => (
          <div key={d.path} className="folder-item" onClick={() => open(d.path)}>
            {d.name}
          </div>
        ))}
      </div>
      {error && <div className="folder-error">{error}</div>}
    </div>
  );
}
