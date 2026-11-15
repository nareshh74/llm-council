import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API_BASE } from '../api';

const DIAGRAM = /^diagram:([0-9a-f]{12})$/;

const urlTransform = (url) => (DIAGRAM.test(url) ? url : defaultUrlTransform(url));

const components = {
  img({ src, alt }) {
    const m = DIAGRAM.exec(src || '');
    if (!m) return <img src={src} alt={alt} />;
    const url = `${API_BASE}/api/diagrams/${m[1]}`;
    return (
      <span className="diagram">
        <iframe className="diagram-frame" src={url} title={alt || 'diagram'} />
        <a className="diagram-open" href={url} target="_blank" rel="noreferrer">
          {alt || 'Open diagram'} (open full size)
        </a>
      </span>
    );
  },
};

export default function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={urlTransform}>
      {children}
    </ReactMarkdown>
  );
}
