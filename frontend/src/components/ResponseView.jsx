import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'

// Centralized Markdown renderer so we can swap to v0's <Response>
// component later with a single change. Today this uses react-markdown
// with GFM + sanitization and styles tables via .md-table.
export default function ResponseView({ children, components, className }){
  const mdSanitize = React.useMemo(() => ({
    tagNames: ['p','strong','em','del','a','ul','ol','li','code','pre','blockquote','hr','table','thead','tbody','tr','th','td'],
    attributes: { a:['href','title','target','rel'], code:['className'], th:['align'], td:['align'], table:['className'] },
    protocols: { href:['http','https','mailto','tel'] }
  }), [])

  return (
    <div className={className || 'md-root'}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, mdSanitize]]}
        components={{
          table: ({ node, ...props }) => <table className="md-table" {...props} />,
          ...(components || {})
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

